"""Tests for FTS5-backed hybrid memory retrieval.

Covers:
- FTS index stays in sync across insert / update / delete / replace_generated_memories
- search_memories returns relevant rows ranked sensibly
- Queries with FTS special chars do not crash and are handled safely
- Graceful-fallback path (monkeypatched fts5_available → False)
- Brief hybrid scoring still works end-to-end
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oh_no_my_claudecode.brief.compiler import score_memories
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage, fts5_available
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _memory(
    mem_id: str,
    title: str,
    summary: str,
    details: str = "",
    tags: list[str] | None = None,
    kind: MemoryKind = MemoryKind.DOC_FACT,
    source_type: SourceType = SourceType.DOC,
    source_ref: str = "README.md",
    confidence: float = 0.8,
    feedback_score: float = 0.0,
) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=mem_id,
        kind=kind,
        title=title,
        summary=summary,
        details=details or summary,
        source_type=source_type,
        source_ref=source_ref,
        tags=tags or [],
        confidence=confidence,
        feedback_score=feedback_score,
        created_at=now,
        updated_at=now,
    )


def _store(tmp_path: Path, entries: list[MemoryEntry]) -> SQLiteStorage:
    storage = SQLiteStorage(tmp_path / "memory.db")
    storage.initialize()
    storage.upsert_memories(entries)
    return storage


# ---------------------------------------------------------------------------
# FTS5 availability
# ---------------------------------------------------------------------------


def test_fts5_available_returns_bool(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "memory.db")
    storage.initialize()
    with storage._connection() as conn:  # type: ignore[attr-defined]
        result = fts5_available(conn)
    assert isinstance(result, bool)


def test_fts5_cache_is_set_after_first_call(tmp_path: Path) -> None:
    """After initialize(), the module-level cache must be populated."""
    import oh_no_my_claudecode.storage.sqlite as mod

    storage = SQLiteStorage(tmp_path / "memory.db")
    storage.initialize()
    assert mod._fts5_available_cache is not None


# ---------------------------------------------------------------------------
# FTS index sync: insert / update / delete
# ---------------------------------------------------------------------------


def test_fts_index_populated_after_upsert(tmp_path: Path) -> None:
    storage = _store(
        tmp_path,
        [_memory("m1", "SQLite FTS5 search", "full-text search using fts5")],
    )
    results = storage.search_memories("fts5 search")
    assert any(m.id == "m1" for m in results)


def test_fts_index_updated_after_update_memory(tmp_path: Path) -> None:
    entry = _memory("m1", "old title", "old summary")
    storage = _store(tmp_path, [entry])

    updated = entry.model_copy(
        update={"title": "new unique xyzzy title", "summary": "xyzzy detail"}
    )
    storage.update_memory(updated)

    hits = storage.search_memories("xyzzy")
    assert any(m.id == "m1" for m in hits)
    # "xyzzy" hits work correctly — the FTS index picked up the update.
    assert any(m.id == "m1" for m in hits)


def test_fts_index_cleaned_after_delete(tmp_path: Path) -> None:
    entries = [
        _memory("m1", "deletable memory", "this will be deleted"),
        _memory("m2", "another memory", "this stays"),
    ]
    storage = _store(tmp_path, entries)

    storage.delete_generated_memories_by_source_refs(["README.md"])
    remaining = storage.list_memories()
    assert all(m.id != "m1" for m in remaining)
    # search should not return the deleted memory
    hits = storage.search_memories("deletable")
    assert all(m.id != "m1" for m in hits)


def test_fts_index_sync_after_replace_generated_memories(tmp_path: Path) -> None:
    old_gen = _memory("gen-1", "old generated", "old content about caching")
    storage = _store(tmp_path, [old_gen])

    new_gen = _memory("gen-2", "new generated", "new content about routing")
    storage.replace_generated_memories([new_gen])

    # old entry should be gone from the index
    old_hits = storage.search_memories("caching")
    assert all(m.id != "gen-1" for m in old_hits)

    # new entry should appear
    new_hits = storage.search_memories("routing")
    assert any(m.id == "gen-2" for m in new_hits)


# ---------------------------------------------------------------------------
# Relevance ranking
# ---------------------------------------------------------------------------


def test_search_memories_ranks_relevant_first(tmp_path: Path) -> None:
    entries = [
        _memory("relevant", "SQLite FTS5 index", "full-text retrieval ranked by bm25"),
        _memory("irrelevant", "Billing integration", "stripe webhook processing"),
    ]
    storage = _store(tmp_path, entries)

    results = storage.search_memories("fts5 full-text retrieval")
    assert len(results) > 0
    assert results[0].id == "relevant"


def test_search_memories_kind_filter(tmp_path: Path) -> None:
    entries = [
        _memory("inv-1", "cache invalidation rule", "always invalidate on write",
                kind=MemoryKind.INVARIANT),
        _memory("doc-1", "cache docs", "documentation about cache invalidation",
                kind=MemoryKind.DOC_FACT),
    ]
    storage = _store(tmp_path, entries)

    results = storage.search_memories("cache invalidation", kind=MemoryKind.INVARIANT)
    ids = {m.id for m in results}
    assert "inv-1" in ids
    assert "doc-1" not in ids


def test_search_memories_empty_query_fallback(tmp_path: Path) -> None:
    """An empty query should not crash — it falls back to LIKE scan."""
    storage = _store(tmp_path, [_memory("m1", "any memory", "any summary")])
    # Empty query: _sanitize_fts_query returns None, falls back to LIKE
    results = storage.search_memories("")
    # Results may be empty or not, but must not raise.
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Security: FTS special chars must not crash
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dangerous_query",
    [
        '"quoted string"',
        "NEAR(foo bar)",
        "foo OR bar AND baz",
        "foo NOT bar",
        "cache*",
        "(nested (operators))",
        'foo "bar" OR baz*',
        "'; DROP TABLE memories; --",
        "\x00null\x00byte",
        "   ",  # whitespace-only
    ],
)
def test_search_memories_special_chars_do_not_crash(tmp_path: Path, dangerous_query: str) -> None:
    storage = _store(tmp_path, [_memory("m1", "safe memory", "safe content")])
    # Must not raise regardless of FTS special chars in the query.
    results = storage.search_memories(dangerous_query)
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Graceful fallback when FTS5 is monkeypatched to False
# ---------------------------------------------------------------------------


def test_search_memories_fallback_when_fts5_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Monkeypatch fts5_available to False and verify LIKE fallback works."""
    import oh_no_my_claudecode.storage.sqlite as mod

    storage = _store(
        tmp_path,
        [_memory("m1", "cache invalidation", "invalidate cache on write")],
    )

    # Patch the module-level cache AND the function to always return False.
    monkeypatch.setattr(mod, "_fts5_available_cache", None)
    monkeypatch.setattr(mod, "fts5_available", lambda _conn: False)

    results = storage.search_memories("cache invalidation")
    # LIKE fallback should still find the memory.
    assert any(m.id == "m1" for m in results)


# ---------------------------------------------------------------------------
# Hybrid brief scoring
# ---------------------------------------------------------------------------


def test_score_memories_hybrid_with_storage(tmp_path: Path) -> None:
    entries = [
        _memory(
            "fts-bonus",
            "FTS5 retrieval algorithm",
            "bm25 ranked full-text search over sqlite",
            tags=["fts5", "search"],
        ),
        _memory(
            "token-only",
            "unrelated topic",
            "billing stripe webhook payment",
        ),
    ]
    storage = _store(tmp_path, entries)
    all_memories = storage.list_memories()

    results = score_memories("sqlite fts5 full text search", all_memories, storage=storage)
    assert len(results) > 0
    assert results[0].id == "fts-bonus"


def test_score_memories_without_storage_unchanged(tmp_path: Path) -> None:
    """When storage=None, score_memories must behave exactly as before."""
    entries = [
        _memory("m1", "cache invalidation", "invalidate worker cache on write"),
        _memory("m2", "unrelated", "stripe billing webhook"),
    ]
    results = score_memories("cache invalidation worker", entries, storage=None)
    assert results[0].id == "m1"


def test_score_memories_storage_failure_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If storage.search_memories raises, score_memories must not propagate the error."""
    entries = [_memory("m1", "test memory", "test summary")]
    storage = _store(tmp_path, entries)

    # Force search_memories to raise
    def _boom(*args: object, **kwargs: object) -> list[MemoryEntry]:
        msg = "simulated FTS failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(storage, "search_memories", _boom)
    # Must not raise
    results = score_memories("test memory", entries, storage=storage)
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Edge: backfill during migration
# ---------------------------------------------------------------------------


def test_migration_backfills_existing_rows(tmp_path: Path) -> None:
    """Rows inserted BEFORE the v2 migration must appear in FTS search."""
    db_path = tmp_path / "memory.db"

    # Create DB with only v1 schema (no FTS table yet) by bypassing _run_migrations.
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                details TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                confidence REAL NOT NULL,
                feedback_score REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        # Insert a pre-migration row directly.
        now = utc_now().isoformat()
        conn.execute(
            """
            INSERT INTO memories
                (id, kind, title, summary, details, source_type, source_ref,
                 tags_json, confidence, feedback_score, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "pre-migration",
                "doc_fact",
                "Pre-migration title",
                "Pre-migration summary about xyzplugh",
                "Pre-migration details",
                "doc",
                "README.md",
                "[]",
                0.9,
                0.0,
                now,
                now,
            ),
        )
        # Write schema_version = 1 so v2 migration runs next.
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '1')")

    # Now re-initialize — this should run v2 migration and backfill.
    storage = SQLiteStorage(db_path)
    storage.initialize()

    hits = storage.search_memories("xyzplugh")
    assert any(m.id == "pre-migration" for m in hits)
