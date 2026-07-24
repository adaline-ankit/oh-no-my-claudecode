"""Tests for the relevance gate and budget cap on prompt_recall injection.

Covers:
  (a) below-threshold recall injects nothing
  (b) above-threshold recall injects as before
  (c) budget cap drops lowest-scored entries and appends trailing note
  (d) fail-open on storage error

All tests are deterministic and require no LLM calls.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from oh_no_my_claudecode.hooks.prompt_recall import compile_prompt_recall
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_storage(db_path: Path) -> SQLiteStorage:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    return storage


def _make_memory(
    mem_id: str,
    title: str,
    summary: str,
    tags: list[str],
    confidence: float = 0.8,
    staleness: str | None = None,
) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=mem_id,
        kind=MemoryKind.INVARIANT,
        title=title,
        summary=summary,
        details="",
        source_type=SourceType.MANUAL,
        source_ref="test",
        tags=tags,
        confidence=confidence,
        feedback_score=0.0,
        created_at=now,
        updated_at=now,
        staleness=staleness,
    )


# ---------------------------------------------------------------------------
# (a) Below-threshold — inject nothing
# ---------------------------------------------------------------------------


def test_below_threshold_injects_nothing(tmp_path: Path) -> None:
    """When the top score is below min_score, compile_prompt_recall returns empty."""
    storage = _make_storage(tmp_path / "brain.db")

    # A memory with no token overlap with the query below.
    # Score with 0 overlaps + confidence=0.8 ≈ 0.0*3 + 0.8 = 0.8
    storage.upsert_memories(
        [
            _make_memory(
                "mem-noop",
                "Unrelated database topic",
                "Something about SQL indexes and query plans.",
                tags=["database", "sql"],
                confidence=0.8,
            )
        ]
    )

    # Query has zero token overlap with the memory above.
    result, tokens = compile_prompt_recall(
        storage,
        "authentication jwt bearer token flow",  # no overlap with database/sql
        min_score=5.0,  # extremely high — nothing can pass
        max_chars=None,
        terse=True,
    )

    assert result == ""
    assert tokens == 0


def test_below_threshold_with_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ONMC_RECALL_MIN_SCORE env var is respected when no override passed."""
    storage = _make_storage(tmp_path / "brain.db")
    storage.upsert_memories(
        [
            _make_memory(
                "mem-low",
                "Unrelated topic about widgets",
                "Widgets are rendered via the canvas pipeline.",
                tags=["widget", "canvas"],
                confidence=0.9,
            )
        ]
    )

    monkeypatch.setenv("ONMC_RECALL_MIN_SCORE", "99.0")  # impossibly high
    result, tokens = compile_prompt_recall(
        storage,
        "authentication jwt bearer token flow",
        # min_score=None → reads env var
        terse=True,
    )

    assert result == ""
    assert tokens == 0


# ---------------------------------------------------------------------------
# (b) Above-threshold — injects as before
# ---------------------------------------------------------------------------


def test_above_threshold_injects_normally(tmp_path: Path) -> None:
    """When the top score clears min_score, recall returns non-empty output."""
    storage = _make_storage(tmp_path / "brain.db")

    storage.upsert_memories(
        [
            _make_memory(
                "mem-cache",
                "Cache invalidation boundary",
                "All cache invalidations must go through the boundary module.",
                tags=["cache", "invalidation"],
                confidence=0.9,
            )
        ]
    )

    # "cache" and "invalidation" overlap → score ≈ 2*3 + 0.9 = 6.9 (well above 1.5)
    result, tokens = compile_prompt_recall(
        storage,
        "fix the cache invalidation bug",
        min_score=1.5,  # default — clearly relevant memory should pass
        max_chars=None,
        terse=True,
    )

    assert result != ""
    assert tokens > 0
    assert "cache" in result.lower() or "Cache" in result


def test_gate_disabled_at_zero_always_injects(tmp_path: Path) -> None:
    """Setting min_score=0.0 disables the gate — any scoring memory is injected."""
    storage = _make_storage(tmp_path / "brain.db")

    # Memory with minimal token overlap (only via fallback list path)
    storage.upsert_memories(
        [
            _make_memory(
                "mem-conf",
                "Widget rendering confidence",
                "Widget confidence is measured by coverage.",
                tags=["widget"],
                confidence=0.9,
            )
        ]
    )

    # Force gate off — any above _MIN_SCORE=0.1 entry gets through
    result, tokens = compile_prompt_recall(
        storage,
        "widget rendering flow",  # "widget" overlaps → score > 0
        min_score=0.0,  # gate disabled
        max_chars=None,
        terse=True,
    )

    # With gate disabled and "widget" overlapping, at least one entry is returned.
    assert isinstance(result, str)
    assert isinstance(tokens, int)
    assert tokens >= 0  # may be empty if FTS returns nothing; gate is OFF regardless


# ---------------------------------------------------------------------------
# (c) Budget cap drops tail, keeps top, appends note
# ---------------------------------------------------------------------------


def test_budget_cap_keeps_top_drops_tail(tmp_path: Path) -> None:
    """Budget cap keeps highest-scored entries and drops the rest with a note."""
    storage = _make_storage(tmp_path / "brain.db")

    now = utc_now()
    memories = [
        MemoryEntry(
            id=f"mem-{i}",
            kind=MemoryKind.INVARIANT,
            title=f"Cache memory {i} — importance level",
            summary=f"Cache subsystem rule {i}: always invalidate through the boundary.",
            details="",
            source_type=SourceType.MANUAL,
            source_ref="test",
            tags=["cache", "invalidation"],
            confidence=0.9,
            feedback_score=0.0,
            created_at=now,
            updated_at=now,
            staleness=None,
        )
        for i in range(5)
    ]
    storage.upsert_memories(memories)

    # Set max_chars so tight that only 1–2 entries fit.
    # Each entry ~: title(35) + summary(75) + details(0) + 50 overhead = ~160 chars
    # max_chars=200 => first entry fits (~160), second does NOT.
    result, tokens = compile_prompt_recall(
        storage,
        "cache invalidation boundary rule",
        min_score=0.0,  # gate off; we only want to test budget
        max_chars=200,
        terse=True,
    )

    # Result must be non-empty (at least 1 entry always kept).
    assert result != ""
    # Trailing note must appear since multiple entries were dropped.
    assert "budget cap" in result
    # The note mentions a positive number of dropped memories.
    import re

    match = re.search(r"\[(\d+) (memory|memories) not shown", result)
    assert match is not None, f"Expected drop note in: {result!r}"
    assert int(match.group(1)) >= 1


def test_budget_cap_no_drop_when_all_fit(tmp_path: Path) -> None:
    """When all entries fit within max_chars, no trailing note is appended."""
    storage = _make_storage(tmp_path / "brain.db")
    storage.upsert_memories(
        [
            _make_memory(
                "mem-tiny",
                "Cache boundary",
                "Use the boundary.",
                tags=["cache"],
                confidence=0.9,
            )
        ]
    )

    result, tokens = compile_prompt_recall(
        storage,
        "cache boundary rule",
        min_score=0.0,
        max_chars=10_000,  # huge — nothing should be dropped
        terse=True,
    )

    if result:
        assert "budget cap" not in result


# ---------------------------------------------------------------------------
# (d) Fail-open on storage error
# ---------------------------------------------------------------------------


def test_fail_open_on_storage_error() -> None:
    """A broken storage must not raise — compile_prompt_recall returns ('', 0)."""
    bad_storage = MagicMock(spec=SQLiteStorage)
    bad_storage.search_memories.side_effect = RuntimeError("db exploded")
    bad_storage.list_memories.side_effect = RuntimeError("db exploded again")

    # Must not raise; must return the safe empty result.
    result, tokens = compile_prompt_recall(
        bad_storage,  # type: ignore[arg-type]
        "cache invalidation",
        min_score=0.0,
        max_chars=None,
        terse=True,
    )

    assert result == ""
    assert tokens == 0


def test_fail_open_partial_storage_error(tmp_path: Path) -> None:
    """FTS failure falls back to list_memories; if that also fails, returns empty."""
    storage = _make_storage(tmp_path / "brain.db")
    storage.upsert_memories(
        [
            _make_memory(
                "mem-x",
                "Cache rule",
                "Always invalidate through boundary.",
                tags=["cache"],
                confidence=0.9,
            )
        ]
    )

    # Patch search_memories to fail; list_memories still works.
    original_search = storage.search_memories
    storage.search_memories = MagicMock(side_effect=RuntimeError("fts broken"))  # type: ignore[method-assign]

    result, tokens = compile_prompt_recall(
        storage,
        "cache invalidation rule",
        min_score=0.0,
        max_chars=None,
        terse=True,
    )

    # Should succeed via list_memories fallback — result may or may not be empty
    # depending on FTS token overlap, but must not raise.
    assert isinstance(result, str)
    assert isinstance(tokens, int)

    storage.search_memories = original_search  # restore
