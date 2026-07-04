"""Tests for ``onmc membudget`` — memory-budget guard + consolidation suggester.

Coverage
--------
1.  Under-budget → over_budget=False, no flag.
2.  Over-budget → over_budget=True, flagged.
3.  Per-kind breakdown accuracy (byte counts + entry counts).
4.  MERGE_DUPLICATES suggestion when near-duplicate entries are seeded.
5.  DROP_STALE suggestion for orphaned / stale entries.
6.  MOVE_TO_TOPIC suggestion for verbose details field.
7.  Determinism: two calls on the same inputs produce identical reports.
8.  ``--json`` envelope: kind="membudget", report has expected keys.
9.  Empty store → graceful (0 bytes, no suggestions).
10. No false-positive MERGE suggestions for unrelated entries in the same kind.
11. No MERGE suggestions across different kinds even with identical text.
12. budget_used_pct computation is correct.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

from oh_no_my_claudecode.membudget.analyzer import (
    DEFAULT_LIMIT_BYTES,
    SuggestionKind,
    analyze,
)

# ---------------------------------------------------------------------------
# Minimal stub — no pydantic / DB required
# ---------------------------------------------------------------------------


@dataclass
class _Mem:
    """Minimal stand-in for MemoryEntry satisfying the MemoryLike protocol."""

    id: str
    kind: str
    title: str
    summary: str
    details: str
    staleness: str | None = None
    tags: list[str] = field(default_factory=list)


def _mem(
    mem_id: str = "m1",
    kind: str = "decision",
    title: str = "title",
    summary: str = "summary",
    details: str = "",
    staleness: str | None = None,
) -> _Mem:
    return _Mem(
        id=mem_id, kind=kind, title=title, summary=summary, details=details, staleness=staleness
    )


# ---------------------------------------------------------------------------
# 1. Under-budget
# ---------------------------------------------------------------------------


def test_under_budget() -> None:
    memories = [_mem("m1", details="small entry")]
    report = analyze(memories, limit=DEFAULT_LIMIT_BYTES)
    assert not report.over_budget
    assert report.total_bytes < DEFAULT_LIMIT_BYTES
    assert report.entry_count == 1


# ---------------------------------------------------------------------------
# 2. Over-budget
# ---------------------------------------------------------------------------


def test_over_budget_flagged() -> None:
    # Create a tiny limit so the entry overflows immediately.
    memories = [_mem("m1", title="hello", summary="world", details="some content")]
    report = analyze(memories, limit=1)  # 1 byte limit
    assert report.over_budget
    assert report.total_bytes > 1


# ---------------------------------------------------------------------------
# 3. Per-kind breakdown accuracy
# ---------------------------------------------------------------------------


def test_per_kind_breakdown() -> None:
    m1 = _mem("m1", kind="decision", title="alpha", summary="beta", details="gamma")
    m2 = _mem("m2", kind="decision", title="delta", summary="epsilon", details="zeta")
    m3 = _mem("m3", kind="gotcha", title="one", summary="two", details="three")

    report = analyze([m1, m2, m3], limit=DEFAULT_LIMIT_BYTES)

    kinds = {bd.kind: bd for bd in report.breakdown}
    assert "decision" in kinds
    assert "gotcha" in kinds
    assert kinds["decision"].entry_count == 2
    assert kinds["gotcha"].entry_count == 1

    # Byte totals must match computed values.
    expected_decision = (
        len(b"alpha") + len(b"beta") + len(b"gamma")
        + len(b"delta") + len(b"epsilon") + len(b"zeta")
    )
    assert kinds["decision"].byte_size == expected_decision

    total = sum(bd.byte_size for bd in report.breakdown)
    assert total == report.total_bytes


# ---------------------------------------------------------------------------
# 4. MERGE_DUPLICATES suggestion on near-duplicate entries
# ---------------------------------------------------------------------------


def test_merge_duplicates_suggestion_on_near_dupes() -> None:
    # Two entries with nearly identical text within the same kind.
    shared_text = "refactor the authentication middleware to use jwt tokens correctly"
    m1 = _mem("m1", kind="decision", title=shared_text, summary=shared_text, details="extra note")
    m2 = _mem("m2", kind="decision", title=shared_text, summary=shared_text, details="extra note")

    report = analyze([m1, m2], limit=DEFAULT_LIMIT_BYTES)

    merge_sugs = [s for s in report.suggestions if s.kind == SuggestionKind.MERGE_DUPLICATES]
    assert len(merge_sugs) >= 1

    entry_ids_flat = {eid for s in merge_sugs for eid in s.entry_ids}
    assert "m1" in entry_ids_flat
    assert "m2" in entry_ids_flat


# ---------------------------------------------------------------------------
# 5. DROP_STALE suggestion for orphaned / stale entries
# ---------------------------------------------------------------------------


def test_drop_stale_suggestion_for_orphaned() -> None:
    m1 = _mem("m1", title="active entry", staleness=None)
    m2 = _mem("m2", title="stale entry", staleness="stale")
    m3 = _mem("m3", title="orphaned entry", staleness="orphaned")

    report = analyze([m1, m2, m3], limit=DEFAULT_LIMIT_BYTES)

    drop_sugs = [s for s in report.suggestions if s.kind == SuggestionKind.DROP_STALE]
    assert len(drop_sugs) == 2

    flagged_ids = {eid for s in drop_sugs for eid in s.entry_ids}
    assert "m2" in flagged_ids
    assert "m3" in flagged_ids
    assert "m1" not in flagged_ids


# ---------------------------------------------------------------------------
# 6. MOVE_TO_TOPIC suggestion for verbose details
# ---------------------------------------------------------------------------


def test_move_to_topic_suggestion_on_verbose_details() -> None:
    large_details = "x" * 5000  # 5 KiB > default 4 KiB threshold
    m1 = _mem("m1", title="verbose entry", details=large_details)
    m2 = _mem("m2", title="normal entry", details="short")

    report = analyze([m1, m2], limit=DEFAULT_LIMIT_BYTES)

    move_sugs = [s for s in report.suggestions if s.kind == SuggestionKind.MOVE_TO_TOPIC]
    assert len(move_sugs) == 1
    assert "m1" in move_sugs[0].entry_ids


# ---------------------------------------------------------------------------
# 7. Determinism — two calls produce identical results
# ---------------------------------------------------------------------------


def test_determinism() -> None:
    shared = "deploy the feature flag service with redis caching and fallback logic"
    memories = [
        _mem("m1", kind="invariant", title=shared, summary=shared, details="note a"),
        _mem("m2", kind="invariant", title=shared, summary=shared, details="note a"),
        _mem("m3", kind="gotcha", title="gotcha entry", staleness="stale"),
        _mem("m4", kind="decision", details="x" * 5000),
    ]

    report1 = analyze(memories, limit=DEFAULT_LIMIT_BYTES)
    report2 = analyze(memories, limit=DEFAULT_LIMIT_BYTES)

    assert report1.total_bytes == report2.total_bytes
    assert report1.over_budget == report2.over_budget
    assert len(report1.suggestions) == len(report2.suggestions)
    for s1, s2 in zip(report1.suggestions, report2.suggestions, strict=True):
        assert s1.kind == s2.kind
        assert s1.entry_ids == s2.entry_ids


# ---------------------------------------------------------------------------
# 8. --json envelope via CLI (mocked storage)
# ---------------------------------------------------------------------------


def test_json_envelope_structure(tmp_path: Path) -> None:
    """CLI --json emits {kind: membudget, report: {...}} with required keys."""
    from typer.testing import CliRunner

    from oh_no_my_claudecode.cli import app

    runner = CliRunner()

    mock_storage = MagicMock()
    mock_storage.list_memories.return_value = []

    with (
        patch(
            "oh_no_my_claudecode.membudget.commands._load_storage",
            return_value=mock_storage,
        ),
        patch(
            "oh_no_my_claudecode.membudget.commands.discover_repo_root",
            return_value=tmp_path,
        ),
    ):
        result = runner.invoke(app, ["membudget", "check", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "membudget"
    rpt = data["report"]
    assert "total_bytes" in rpt
    assert "limit_bytes" in rpt
    assert "over_budget" in rpt
    assert "entry_count" in rpt
    assert "breakdown" in rpt
    assert "suggestions" in rpt
    assert "budget_used_pct" in rpt
    assert "merge_count" in rpt
    assert "move_count" in rpt
    assert "drop_count" in rpt


# ---------------------------------------------------------------------------
# 9. Empty store graceful
# ---------------------------------------------------------------------------


def test_empty_store_graceful() -> None:
    report = analyze([])
    assert report.total_bytes == 0
    assert not report.over_budget
    assert report.entry_count == 0
    assert report.suggestions == []
    assert report.breakdown == []
    assert report.budget_used_pct == 0.0


# ---------------------------------------------------------------------------
# 10. No false-positive MERGE for unrelated entries in same kind
# ---------------------------------------------------------------------------


def test_no_false_positive_merge_unrelated_same_kind() -> None:
    m1 = _mem(
        "m1",
        kind="decision",
        title="authentication jwt middleware setup",
        summary="implement oauth2",
    )
    m2 = _mem(
        "m2",
        kind="decision",
        title="database schema migration plan",
        summary="add user table index",
    )

    report = analyze([m1, m2], limit=DEFAULT_LIMIT_BYTES)
    merge_sugs = [s for s in report.suggestions if s.kind == SuggestionKind.MERGE_DUPLICATES]
    assert merge_sugs == []


# ---------------------------------------------------------------------------
# 11. No MERGE across different kinds (identical text, different kinds)
# ---------------------------------------------------------------------------


def test_no_merge_across_different_kinds() -> None:
    shared = "always use type annotations in python functions for clarity and safety"
    m1 = _mem("m1", kind="decision", title=shared, summary=shared, details="detail")
    m2 = _mem("m2", kind="gotcha", title=shared, summary=shared, details="detail")

    report = analyze([m1, m2], limit=DEFAULT_LIMIT_BYTES)
    merge_sugs = [s for s in report.suggestions if s.kind == SuggestionKind.MERGE_DUPLICATES]
    assert merge_sugs == []


# ---------------------------------------------------------------------------
# 12. budget_used_pct computation
# ---------------------------------------------------------------------------


def test_budget_used_pct() -> None:
    # 100 bytes of content, limit=1000 → 10.0%
    payload = "x" * 100
    m1 = _mem("m1", title="", summary="", details=payload)
    report = analyze([m1], limit=1000)
    # details alone is 100 bytes, title+summary are empty strings → 0 bytes each
    assert report.total_bytes == 100
    assert report.budget_used_pct == 10.0
