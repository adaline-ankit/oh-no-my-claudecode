"""Pure tests for the timeline builder + renderer (no real DB, no clock)."""

from __future__ import annotations

from datetime import UTC, datetime

from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.timeline import (
    Timeline,
    build_timeline,
    render_markdown,
)
from oh_no_my_claudecode.timeline.timeline import UNDATED_LABEL


def _mem(
    mem_id: str,
    *,
    created_at: datetime | None,
    kind: MemoryKind = MemoryKind.DECISION,
    title: str = "",
    summary: str = "",
) -> MemoryEntry:
    """Build an in-memory MemoryEntry; created_at may be forced to None."""
    ts = created_at if created_at is not None else datetime(2000, 1, 1, tzinfo=UTC)
    entry = MemoryEntry(
        id=mem_id,
        kind=kind,
        title=title or mem_id,
        summary=summary or f"summary for {mem_id}",
        details="details",
        source_type=SourceType.MANUAL,
        source_ref="ref",
        tags=[],
        confidence=1.0,
        created_at=ts,
        updated_at=ts,
    )
    if created_at is None:
        # Force the missing-timestamp path without tripping pydantic validation.
        object.__setattr__(entry, "created_at", None)
    return entry


def test_groups_into_ascending_periods_by_day() -> None:
    mems = [
        _mem("c", created_at=datetime(2026, 7, 4, 9, 0, tzinfo=UTC)),
        _mem("a", created_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC)),
        _mem("b", created_at=datetime(2026, 7, 1, 18, 0, tzinfo=UTC)),
    ]
    tl = build_timeline(mems, group="day")
    assert [p.label for p in tl.periods] == ["2026-07-01", "2026-07-04"]
    assert tl.total == 3
    # Within the first period, entries are ascending by created_at.
    first = tl.periods[0].entries
    assert [e.title for e in first] == ["a", "b"]


def test_within_period_deterministic_order() -> None:
    # Same day, out-of-order input → sorted by (ts, title).
    day = datetime(2026, 7, 4, tzinfo=UTC)
    mems = [
        _mem("z", created_at=day.replace(hour=10), title="zebra"),
        _mem("y", created_at=day.replace(hour=10), title="apple"),
    ]
    tl = build_timeline(mems)
    titles = [e.title for e in tl.periods[0].entries]
    assert titles == ["apple", "zebra"]


def test_group_by_week() -> None:
    mems = [
        _mem("a", created_at=datetime(2026, 7, 1, tzinfo=UTC)),  # W27
        _mem("b", created_at=datetime(2026, 7, 8, tzinfo=UTC)),  # W28
    ]
    tl = build_timeline(mems, group="week")
    assert [p.label for p in tl.periods] == ["2026-W27", "2026-W28"]


def test_since_filters_relative() -> None:
    now = datetime(2026, 7, 10, tzinfo=UTC)
    mems = [
        _mem("old", created_at=datetime(2026, 6, 1, tzinfo=UTC)),
        _mem("new", created_at=datetime(2026, 7, 9, tzinfo=UTC)),
    ]
    tl = build_timeline(mems, since="7d", group="day", now=now)
    assert tl.total == 1
    assert tl.periods[0].entries[0].title == "new"


def test_since_filters_iso_date() -> None:
    mems = [
        _mem("old", created_at=datetime(2026, 6, 1, tzinfo=UTC)),
        _mem("new", created_at=datetime(2026, 7, 9, tzinfo=UTC)),
    ]
    tl = build_timeline(mems, since="2026-07-01", now=datetime(2026, 7, 10, tzinfo=UTC))
    assert tl.total == 1
    assert tl.periods[0].entries[0].title == "new"


def test_bad_since_notes_and_keeps_all() -> None:
    mems = [_mem("a", created_at=datetime(2026, 7, 1, tzinfo=UTC))]
    tl = build_timeline(mems, since="not-a-date", now=datetime(2026, 7, 10, tzinfo=UTC))
    assert tl.total == 1
    assert any("could not parse" in n for n in tl.notes)


def test_undated_bucketed_and_noted() -> None:
    mems = [
        _mem("dated", created_at=datetime(2026, 7, 1, tzinfo=UTC)),
        _mem("ghost", created_at=None),
    ]
    tl = build_timeline(mems)
    assert tl.total == 2
    # Undated period comes last.
    assert tl.periods[-1].label == UNDATED_LABEL
    assert tl.periods[-1].entries[0].title == "ghost"
    assert any(UNDATED_LABEL in n for n in tl.notes)


def test_undated_excluded_when_since_active() -> None:
    mems = [
        _mem("dated", created_at=datetime(2026, 7, 9, tzinfo=UTC)),
        _mem("ghost", created_at=None),
    ]
    tl = build_timeline(mems, since="2026-07-01", now=datetime(2026, 7, 10, tzinfo=UTC))
    assert tl.total == 1
    assert all(p.label != UNDATED_LABEL for p in tl.periods)
    assert any("excluded by --since" in n for n in tl.notes)


def test_empty_brain_yields_empty_timeline_and_note() -> None:
    tl = build_timeline([])
    assert isinstance(tl, Timeline)
    assert tl.total == 0
    assert tl.periods == []
    md = render_markdown(tl)
    assert "No history yet" in md


def test_render_markdown_contains_labels_and_titles() -> None:
    mems = [
        _mem(
            "a",
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
            title="chose sqlite",
            kind=MemoryKind.DECISION,
        ),
        _mem(
            "b",
            created_at=datetime(2026, 7, 4, tzinfo=UTC),
            title="never force-push",
            kind=MemoryKind.INVARIANT,
        ),
    ]
    md = render_markdown(build_timeline(mems))
    assert "## 2026-07-01" in md
    assert "## 2026-07-04" in md
    assert "chose sqlite" in md
    assert "never force-push" in md
    assert "decision" in md
    assert "invariant" in md


def test_build_timeline_deterministic() -> None:
    mems = [
        _mem("c", created_at=datetime(2026, 7, 4, 9, tzinfo=UTC)),
        _mem("a", created_at=datetime(2026, 7, 1, 9, tzinfo=UTC)),
        _mem("b", created_at=datetime(2026, 7, 1, 18, tzinfo=UTC)),
    ]
    first = render_markdown(build_timeline(mems))
    second = render_markdown(build_timeline(list(reversed(mems))))
    assert first == second
