"""Pure, deterministic activity-heatmap construction and rendering.

This module never reads the clock, the filesystem, or the network. It takes a
list of receipt dicts (as returned by
:func:`oh_no_my_claudecode.ledger.accounting.load_receipts`) and folds them
into a GitHub-contributions-style calendar grid: a fixed number of weeks,
7 days each, where each cell's intensity reflects how many agent runs
completed that day. The command layer
(:mod:`oh_no_my_claudecode.heatmap.commands`) is responsible for loading the
receipts and for supplying ``today`` so the grid's window is fully injectable
and tests never depend on the real wall clock.

Design notes
------------
- **Deterministic**: same input list + same ``today`` → identical
  :class:`Heatmap`, identical rendering. Days are bucketed by calendar date
  (UTC) derived from a receipt's ``ended_at`` timestamp.
- **Never fabricates**: a receipt with a missing/unparseable ``ended_at`` is
  dropped from the grid (not guessed into a day) and counted in ``notes``.
- **Offline**: no ``datetime.now`` call lives here — ``today`` is a parameter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

# Block glyphs used to render intensity, lowest to highest.
_GLYPHS = ("·", "░", "▒", "▓", "█")  # · ░ ▒ ▓ █

_MONTH_ABBR = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)  # fmt: skip

_WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

DEFAULT_WEEKS = 12


@dataclass(frozen=True)
class DayCell:
    """One calendar day in the heatmap grid."""

    day: date
    count: int
    verified_count: int


@dataclass
class Heatmap:
    """The full calendar grid plus rollup totals."""

    days: list[DayCell] = field(default_factory=list)
    weeks: int = 0
    total_runs: int = 0
    active_days: int = 0
    busiest_day: DayCell | None = None
    current_streak: int = 0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers (pure)
# ---------------------------------------------------------------------------


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 UTC string; return None on failure or empty input."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _receipt_day(data: dict[str, Any]) -> date | None:
    """Return the calendar day (UTC) a receipt's run ended on, if knowable."""
    ts = _parse_iso(str(data.get("ended_at") or ""))
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).date()


def _week_start(day: date) -> date:
    """Return the Monday that starts *day*'s ISO week."""
    return day - timedelta(days=day.weekday())


def _intensity_level(count: int, max_count: int) -> int:
    """Map *count* to a glyph index 0-4 given the grid's *max_count*.

    0 always maps to level 0 (empty). Non-zero counts are bucketed into
    quartiles of ``[1, max_count]`` so the busiest day always reaches the
    top glyph.
    """
    if count <= 0 or max_count <= 0:
        return 0
    if max_count == 1:
        return 4
    # Scale count into 1..4 across the observed range.
    ratio = (count - 1) / (max_count - 1)
    level = 1 + round(ratio * 3)
    return max(1, min(4, level))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_heatmap(
    receipts: list[dict[str, Any]],
    *,
    today: date,
    weeks: int = DEFAULT_WEEKS,
) -> Heatmap:
    """Fold *receipts* into a *weeks*-wide calendar :class:`Heatmap`.

    Args:
        receipts: Receipt dicts (any order); each may carry ``ended_at`` and
            ``verified``.
        today: Reference "current" date — the grid's rightmost column always
            contains today's week. Passed in explicitly so this function never
            reads the wall clock.
        weeks: Number of weeks to include (default
            :data:`DEFAULT_WEEKS`). Values below 1 are clamped to 1.

    Returns:
        A :class:`Heatmap` whose ``days`` list is ordered oldest-to-newest and
        covers exactly ``weeks * 7`` calendar days ending on ``today``.
    """
    weeks = max(1, weeks)
    notes: list[str] = []

    window_start = _week_start(today - timedelta(weeks=weeks - 1))
    window_end = today

    counts: dict[date, int] = {}
    verified_counts: dict[date, int] = {}
    unparseable = 0

    for data in receipts:
        day = _receipt_day(data)
        if day is None:
            unparseable += 1
            continue
        if day < window_start or day > window_end:
            continue
        counts[day] = counts.get(day, 0) + 1
        if bool(data.get("verified", False)):
            verified_counts[day] = verified_counts.get(day, 0) + 1

    days: list[DayCell] = []
    cursor = window_start
    while cursor <= window_end:
        days.append(
            DayCell(
                day=cursor,
                count=counts.get(cursor, 0),
                verified_count=verified_counts.get(cursor, 0),
            )
        )
        cursor += timedelta(days=1)

    if unparseable:
        plural = "" if unparseable == 1 else "s"
        notes.append(f"{unparseable} receipt{plural} had no usable timestamp — excluded")

    total_runs = sum(c.count for c in days)
    active_days = sum(1 for c in days if c.count > 0)

    busiest_day: DayCell | None = None
    for cell in days:
        if busiest_day is None or cell.count > busiest_day.count:
            busiest_day = cell
    if busiest_day is not None and busiest_day.count == 0:
        busiest_day = None

    # Current streak: consecutive active days ending at `today`, walking
    # backwards. A streak requires today itself (or the most recent day in
    # the window) to be active; otherwise it's 0.
    current_streak = 0
    for cell in reversed(days):
        if cell.count > 0:
            current_streak += 1
        else:
            break

    return Heatmap(
        days=days,
        weeks=weeks,
        total_runs=total_runs,
        active_days=active_days,
        busiest_day=busiest_day,
        current_streak=current_streak,
        notes=notes,
    )


def render_text(hm: Heatmap) -> str:
    """Render *hm* as a deterministic, GitHub-style block-glyph grid."""
    lines: list[str] = ["onmc heatmap — agent run activity", ""]

    for note in hm.notes:
        lines.append(f"note: {note}")
    if hm.notes:
        lines.append("")

    if not hm.days or hm.total_runs == 0:
        lines.append("No runs recorded yet in this window — the grid is empty.")
        return "\n".join(lines)

    # Group days into weeks (columns), each a list of up to 7 DayCells
    # starting Monday. hm.days is already ordered oldest -> newest and
    # window_start is always a Monday, so simple chunking works.
    columns: list[list[DayCell]] = [hm.days[i : i + 7] for i in range(0, len(hm.days), 7)]

    max_count = max((c.count for c in hm.days), default=0)

    # Month labels: one label per column where the month changes (or first column).
    month_row = ["    "]
    last_month: int | None = None
    for col in columns:
        first_day = col[0].day
        if last_month != first_day.month:
            month_row.append(_MONTH_ABBR[first_day.month - 1])
            last_month = first_day.month
        else:
            month_row.append("   ")
    lines.append(" ".join(month_row))

    # One row per weekday (Mon..Sun), one glyph per week column.
    for row_idx, weekday_label in enumerate(_WEEKDAY_LABELS):
        cells: list[str] = []
        for col in columns:
            if row_idx < len(col):
                cell = col[row_idx]
                level = _intensity_level(cell.count, max_count)
                cells.append(_GLYPHS[level])
            else:
                cells.append(" ")
        lines.append(f"{weekday_label} " + "  ".join(cells))

    lines.append("")
    legend = "  ".join(f"{g}={i}" for i, g in enumerate(_GLYPHS))
    lines.append(f"legend: {legend} (relative intensity, 0=none .. 4=busiest)")
    lines.append("")

    lines.append(f"total runs: {hm.total_runs}")
    lines.append(f"active days: {hm.active_days} / {len(hm.days)}")
    if hm.busiest_day is not None:
        lines.append(
            f"busiest day: {hm.busiest_day.day.isoformat()} ({hm.busiest_day.count} runs)"
        )
    else:
        lines.append("busiest day: n/a")
    streak_word = "day" if hm.current_streak == 1 else "days"
    lines.append(f"current streak: {hm.current_streak} {streak_word}")

    return "\n".join(lines)


__all__ = [
    "DEFAULT_WEEKS",
    "DayCell",
    "Heatmap",
    "build_heatmap",
    "render_text",
]
