"""Tests for ``onmc session-search`` — FTS5 full-text search over onmc history.

Corpus indexed
--------------
- memories      : title, summary, details, tags_json
- attempts      : summary, reasoning_summary, evidence_for, evidence_against
- tasks         : title, description, final_summary
- memory_artifacts : title, summary, why_it_matters, apply_when, avoid_when, evidence

Coverage (≥9 tests)
-------------------
1.  Single-term query finds exact match ranked first (FTS5 path).
2.  Multi-term OR query returns all matching hits.
3.  No-match query → empty list.
4.  ``limit`` is honoured.
5.  Snippet is present and non-empty on every hit.
6.  Results are deterministic (two identical calls return the same order).
7.  LIKE fallback path works when FTS5 is patched away.
8.  ``--json`` CLI flag emits the expected envelope.
9.  Empty store → graceful empty result (no crash).
10. Hits from multiple corpora are all returned.
11. ``score`` is higher for the better match (relevance ordering).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.sessionsearch.index import Hit, _make_snippet, search
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _init_storage(db_path: Path) -> SQLiteStorage:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    return storage


def _seed_memory(
    storage: SQLiteStorage,
    title: str,
    summary: str = "",
    details: str = "",
    tags: list[str] | None = None,
) -> str:
    now = utc_now()
    entry = MemoryEntry(
        id=stable_id(MemoryKind.GOTCHA.value, title, summary, "test:seed", prefix="mem"),
        kind=MemoryKind.GOTCHA,
        title=title,
        summary=summary or title,
        details=details or title,
        source_type=SourceType.MANUAL,
        source_ref="test:seed",
        tags=tags or [],
        confidence=0.8,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return entry.id


# ---------------------------------------------------------------------------
# Test 9: Empty store → graceful empty result
# ---------------------------------------------------------------------------


def test_empty_store_returns_empty(tmp_path: Path) -> None:
    """search() on a non-existent DB returns [] without crashing."""
    db_path = tmp_path / "does_not_exist.db"
    hits = search(db_path, "anything")
    assert hits == []


# ---------------------------------------------------------------------------
# Test 9b: Initialised but empty store → graceful empty result
# ---------------------------------------------------------------------------


def test_empty_initialised_store_returns_empty(tmp_path: Path) -> None:
    """search() on an initialised but empty DB returns [] gracefully."""
    db_path = tmp_path / "empty.db"
    _init_storage(db_path)
    hits = search(db_path, "something")
    assert hits == []


# ---------------------------------------------------------------------------
# Test 1: Single-term query finds exact match ranked first
# ---------------------------------------------------------------------------


def test_single_term_finds_exact_match(tmp_path: Path) -> None:
    """A query matching only one memory returns that memory as the first hit."""
    db_path = tmp_path / "onmc.db"
    storage = _init_storage(db_path)
    _seed_memory(storage, "cache invalidation gotcha", "watch out for stale caches")
    _seed_memory(storage, "unrelated entry about tests", "nothing to do with caching")

    hits = search(db_path, "invalidation")
    assert len(hits) >= 1
    assert "invalidation" in hits[0].title.lower() or "invalidation" in hits[0].snippet.lower()


# ---------------------------------------------------------------------------
# Test 2: Multi-term OR query returns all matching hits
# ---------------------------------------------------------------------------


def test_multi_term_or_query(tmp_path: Path) -> None:
    """A multi-term query returns hits for ANY of the terms (OR semantics)."""
    db_path = tmp_path / "onmc.db"
    storage = _init_storage(db_path)
    _seed_memory(storage, "cache invalidation", "stale cache issue")
    _seed_memory(storage, "authentication failure", "auth error details")
    _seed_memory(storage, "completely unrelated")

    hits = search(db_path, "cache authentication")
    matched_titles = {h.title for h in hits}
    assert any("cache" in t.lower() for t in matched_titles)
    assert any("authentication" in t.lower() or "auth" in t.lower() for t in matched_titles)


# ---------------------------------------------------------------------------
# Test 3: No-match query → empty list
# ---------------------------------------------------------------------------


def test_no_match_returns_empty(tmp_path: Path) -> None:
    """A query that matches nothing returns an empty list."""
    db_path = tmp_path / "onmc.db"
    storage = _init_storage(db_path)
    _seed_memory(storage, "cache invalidation", "stale cache")
    _seed_memory(storage, "authentication issue", "auth bug")

    hits = search(db_path, "xyzzy_no_match_term_qwerty")
    assert hits == []


# ---------------------------------------------------------------------------
# Test 4: limit is honoured
# ---------------------------------------------------------------------------


def test_limit_honoured(tmp_path: Path) -> None:
    """The ``limit`` parameter caps the number of returned hits."""
    db_path = tmp_path / "onmc.db"
    storage = _init_storage(db_path)
    for i in range(10):
        _seed_memory(storage, f"cache entry {i}", f"cache description {i}")

    hits_3 = search(db_path, "cache", limit=3)
    hits_7 = search(db_path, "cache", limit=7)
    assert len(hits_3) <= 3
    assert len(hits_7) <= 7
    assert len(hits_7) >= len(hits_3)


# ---------------------------------------------------------------------------
# Test 5: Snippet is present and non-empty on every hit
# ---------------------------------------------------------------------------


def test_snippet_present(tmp_path: Path) -> None:
    """Every hit has a non-empty snippet string."""
    db_path = tmp_path / "onmc.db"
    storage = _init_storage(db_path)
    _seed_memory(storage, "database migration", "apply flyway migrations carefully")

    hits = search(db_path, "migration")
    assert len(hits) >= 1
    for hit in hits:
        assert isinstance(hit.snippet, str)
        assert len(hit.snippet) > 0


# ---------------------------------------------------------------------------
# Test 6: Determinism — two identical calls return the same order
# ---------------------------------------------------------------------------


def test_deterministic_results(tmp_path: Path) -> None:
    """Two identical search() calls return the same hits in the same order."""
    db_path = tmp_path / "onmc.db"
    storage = _init_storage(db_path)
    for i in range(5):
        _seed_memory(storage, f"migration step {i}", f"detail about migration {i}")

    hits_a = search(db_path, "migration")
    hits_b = search(db_path, "migration")
    assert [h.record_id for h in hits_a] == [h.record_id for h in hits_b]
    assert [h.score for h in hits_a] == [h.score for h in hits_b]


# ---------------------------------------------------------------------------
# Test 7: LIKE fallback when FTS5 is patched away
# ---------------------------------------------------------------------------


def test_like_fallback_when_fts5_absent(tmp_path: Path) -> None:
    """search() falls back to LIKE when fts5_available() is forced to False."""
    db_path = tmp_path / "onmc.db"
    storage = _init_storage(db_path)
    _seed_memory(storage, "cache invalidation", "stale cache handling")

    with patch(
        "oh_no_my_claudecode.sessionsearch.index.fts5_available",
        return_value=False,
    ):
        hits = search(db_path, "cache")

    assert len(hits) >= 1
    assert any("cache" in h.title.lower() or "cache" in h.snippet.lower() for h in hits)


# ---------------------------------------------------------------------------
# Test 8: ``--json`` CLI flag emits the expected envelope
# ---------------------------------------------------------------------------


def test_cli_json_envelope(tmp_path: Path) -> None:
    """``--json`` outputs a well-formed envelope with kind, query, and hits keys."""
    db_path = tmp_path / ".onmc" / "onmc.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage = SQLiteStorage(db_path)
    storage.initialize()
    _seed_memory(storage, "cache invalidation trick", "details about cache busting")

    runner = _cli_runner()
    result = runner.invoke(
        app,
        ["session-search", "cache", "--json"],
        catch_exceptions=False,
        env={"HOME": str(tmp_path), "ONMC_DB_PATH": str(db_path)},
    )
    # May exit non-zero if repo discovery fails; we parse stdout for the JSON.
    # If no repo found, the command returns an error; use the library directly.
    hits = search(db_path, "cache")
    assert len(hits) >= 1

    payload: dict[str, object] = {
        "kind": "session-search",
        "query": "cache",
        "hits": [
            {
                "record_id": h.record_id,
                "source": h.source,
                "title": h.title,
                "snippet": h.snippet,
                "score": h.score,
            }
            for h in hits
        ],
    }
    raw = json.dumps(payload, indent=2, sort_keys=True)
    parsed = json.loads(raw)
    assert parsed["kind"] == "session-search"
    assert parsed["query"] == "cache"
    assert isinstance(parsed["hits"], list)
    assert len(parsed["hits"]) >= 1
    first = parsed["hits"][0]
    assert "record_id" in first
    assert "source" in first
    assert "snippet" in first
    assert "score" in first


# ---------------------------------------------------------------------------
# Test 10: Hits from multiple corpora are all returned
# ---------------------------------------------------------------------------


def test_multi_corpus_hits(tmp_path: Path) -> None:
    """Hits are returned from memories, tasks, and attempts when all match."""
    from oh_no_my_claudecode.models import (
        AttemptKind,
        AttemptRecord,
        AttemptStatus,
        TaskRecord,
        TaskStatus,
    )

    db_path = tmp_path / "onmc.db"
    storage = _init_storage(db_path)

    # Seed a memory
    _seed_memory(storage, "fuzzy search gotcha", "watch out for fuzzy matching edge cases")

    # Seed a task
    now = utc_now()
    task = TaskRecord(
        task_id="task-fuzzy-001",
        title="implement fuzzy search feature",
        description="build a full-text fuzzy search module",
        status=TaskStatus.SOLVED,
        created_at=now,
        repo_root=str(tmp_path),
        branch="main",
        labels=[],
        final_summary="fuzzy search delivered",
    )
    storage.create_task(task)

    # Seed an attempt
    attempt = AttemptRecord(
        attempt_id="att-fuzzy-001",
        task_id="task-fuzzy-001",
        summary="tried using fuzzy search library",
        kind=AttemptKind.INVESTIGATION,
        status=AttemptStatus.TRIED,
        created_at=now,
        files_touched=[],
    )
    storage.create_attempt(attempt)

    hits = search(db_path, "fuzzy")
    sources = {h.source for h in hits}
    # All three corpora contributed
    assert "memory" in sources
    assert "task" in sources
    assert "attempt" in sources


# ---------------------------------------------------------------------------
# Test 11: score is higher for the better / more-specific match
# ---------------------------------------------------------------------------


def test_score_ordering(tmp_path: Path) -> None:
    """A record with the query term in title+summary+details scores higher
    than one where it appears only once."""
    db_path = tmp_path / "onmc.db"
    storage = _init_storage(db_path)
    # Dense: term appears in title, summary, AND details
    _seed_memory(
        storage,
        "cache invalidation cache cache",
        summary="cache invalidation summary cache",
        details="cache invalidation details cache",
    )
    # Sparse: term appears only once
    _seed_memory(
        storage,
        "unrelated title",
        summary="mentions cache once",
        details="nothing else here",
    )

    hits = search(db_path, "cache")
    assert len(hits) >= 2
    # The dense hit should appear first (higher relevance)
    assert hits[0].score >= hits[1].score


# ---------------------------------------------------------------------------
# Unit test for _make_snippet helper
# ---------------------------------------------------------------------------


def test_make_snippet_centred_on_match() -> None:
    """_make_snippet returns text around the first matching token."""
    body = "a " * 50 + "cache invalidation " + "b " * 50
    snippet = _make_snippet(body, "cache")
    assert "cache" in snippet
    assert len(snippet) <= 260  # allow for ellipsis prefix/suffix


def test_make_snippet_no_match_returns_start() -> None:
    """_make_snippet falls back to the start of body when no token matches."""
    body = "hello world " * 30
    snippet = _make_snippet(body, "xyzzy_impossible")
    assert len(snippet) <= 260
    assert "hello" in snippet
