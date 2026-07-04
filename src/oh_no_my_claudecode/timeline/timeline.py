"""Pure, deterministic timeline construction and rendering.

This module never reads the clock, the filesystem, or the network. It takes a
list of :class:`~oh_no_my_claudecode.models.MemoryEntry` objects and folds them
into an ordered, period-grouped narrative. The command layer
(:mod:`oh_no_my_claudecode.timeline.commands`) is responsible for loading the
memories and for supplying any ``now`` needed to parse a relative ``--since``.

Design notes
------------
- **Deterministic**: same input list → identical :class:`Timeline`, identical
  markdown. Entries are sorted by ``created_at`` ascending with a stable
  secondary key (``id``) so ties never reorder between runs.
- **Never fabricates**: a memory with a missing/``None`` ``created_at`` is
  bucketed into a distinct ``"undated"`` period and a note records how many were
  undated — we never invent a timestamp.
- **Offline**: no ``datetime.now`` call lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # pragma: no cover - typing only
    from rich.console import Console

    from oh_no_my_claudecode.models import MemoryEntry

GroupBy = Literal["day", "week"]

# Sentinel period label for memories that have no usable timestamp. Sorts last.
UNDATED_LABEL = "undated"


@dataclass(frozen=True)
class TimelineEntry:
    """One milestone on the timeline — a single memory rendered as a one-liner."""

    ts: datetime | None
    kind: str
    title: str
    summary: str


@dataclass
class Period:
    """A contiguous bucket of milestones sharing a period label (e.g. a day)."""

    label: str
    entries: list[TimelineEntry] = field(default_factory=list)


@dataclass
class Timeline:
    """The full ordered narrative: periods ascending, plus counts and notes."""

    periods: list[Period] = field(default_factory=list)
    total: int = 0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers (pure)
# ---------------------------------------------------------------------------


def _normalize_ts(ts: datetime | None) -> datetime | None:
    """Return an aware UTC datetime, or ``None`` when *ts* is missing.

    Naive datetimes are assumed to be UTC (matching the digest fallback path).
    """
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _kind_value(kind: object) -> str:
    """Return the string value of a memory kind, tolerating plain strings."""
    return getattr(kind, "value", None) or str(kind)


def _period_label(ts: datetime, group: GroupBy) -> str:
    """Return a deterministic period label for *ts* under *group*.

    - ``day``  → ``"2026-07-04"`` (ISO date).
    - ``week`` → ``"2026-W27"`` (ISO year + ISO week number, zero-padded).
    """
    if group == "week":
        iso = ts.isocalendar()
        return f"{iso.year:04d}-W{iso.week:02d}"
    return ts.date().isoformat()


def _parse_since(since: str, now: datetime) -> datetime | None:
    """Parse a ``--since`` token into an aware UTC cutoff, or ``None`` if invalid.

    Accepts either an ISO date (``2026-07-01``) or a relative ``<N>d`` window
    (``7d`` → 7 days before *now*). Uses only simple string ops — no regex — to
    stay clear of ReDoS.
    """
    token = since.strip()
    if not token:
        return None
    now = _normalize_ts(now) or now

    # Relative form: "<digits>d".
    if len(token) >= 2 and token[-1] in ("d", "D") and token[:-1].isdigit():
        days = int(token[:-1])
        return now - timedelta(days=days)

    # ISO date / datetime form.
    try:
        parsed = datetime.fromisoformat(token)
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(token), datetime.min.time())
        except ValueError:
            return None
    return _normalize_ts(parsed)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_timeline(
    memories: list[MemoryEntry],
    *,
    since: str | None = None,
    group: GroupBy = "day",
    now: datetime | None = None,
) -> Timeline:
    """Fold *memories* into an ordered, period-grouped :class:`Timeline`.

    Args:
        memories: The live-storage memory list (any order).
        since: Optional cutoff — an ISO date (``2026-07-01``) or a relative
            window (``30d``). Entries strictly before the cutoff are dropped.
            Undated entries are always dropped when a ``since`` filter is active
            (we cannot prove they fall inside the window, and never fabricate).
        group: Period granularity — ``"day"`` (default) or ``"week"``.
        now: Reference instant used only to resolve a relative ``since``. When
            ``since`` is relative and ``now`` is ``None``, the filter is skipped
            and a note explains why — this keeps the function clock-free.

    Returns:
        A :class:`Timeline` whose ``periods`` are ordered ascending, with the
        ``undated`` bucket (if any) placed last, and ``notes`` describing any
        filtering or bucketing that happened.
    """
    notes: list[str] = []

    cutoff: datetime | None = None
    if since is not None:
        if now is None:
            # Only relative forms need `now`; try to parse an absolute date anyway.
            cutoff = _parse_since(since, datetime(1970, 1, 1, tzinfo=UTC))
            if cutoff is None:
                notes.append(
                    f"could not apply --since {since!r} (needs a reference time or an ISO date); "
                    "showing full history"
                )
        else:
            cutoff = _parse_since(since, now)
            if cutoff is None:
                notes.append(f"could not parse --since {since!r}; showing full history")

    dated: list[tuple[datetime, TimelineEntry]] = []
    undated: list[TimelineEntry] = []
    undated_count = 0

    for mem in memories:
        ts = _normalize_ts(getattr(mem, "created_at", None))
        entry = TimelineEntry(
            ts=ts,
            kind=_kind_value(getattr(mem, "kind", "")),
            title=str(getattr(mem, "title", "")),
            summary=str(getattr(mem, "summary", "")),
        )
        if ts is None:
            undated_count += 1
            if cutoff is None:
                undated.append(entry)
            continue
        if cutoff is not None and ts < cutoff:
            continue
        dated.append((ts, entry))

    # Deterministic ascending order: primary created_at, secondary title, tertiary kind.
    dated.sort(key=lambda pair: (pair[0], pair[1].title, pair[1].kind))

    periods: list[Period] = []
    current: Period | None = None
    for ts, entry in dated:
        label = _period_label(ts, group)
        if current is None or current.label != label:
            current = Period(label=label)
            periods.append(current)
        current.entries.append(entry)

    if undated:
        # Stable order within the undated bucket.
        undated.sort(key=lambda e: (e.title, e.kind))
        periods.append(Period(label=UNDATED_LABEL, entries=list(undated)))

    if undated_count:
        if cutoff is None:
            notes.append(
                f"{undated_count} memor{'y' if undated_count == 1 else 'ies'} had no timestamp — "
                f"bucketed under '{UNDATED_LABEL}'"
            )
        else:
            plural = "y" if undated_count == 1 else "ies"
            notes.append(f"{undated_count} undated memor{plural} excluded by --since")

    total = sum(len(p.entries) for p in periods)
    return Timeline(periods=periods, total=total, notes=notes)


def render_markdown(tl: Timeline) -> str:
    """Render *tl* as a deterministic, readable markdown story."""
    lines: list[str] = ["# Repo evolution timeline", ""]

    for note in tl.notes:
        lines.append(f"> _{note}_")
    if tl.notes:
        lines.append("")

    if tl.total == 0:
        lines += ["_No history yet — the brain has no memories to narrate._", ""]
        return "\n".join(lines)

    lines.append(f"**{tl.total} milestone{'' if tl.total == 1 else 's'} across "
                 f"{len(tl.periods)} period{'' if len(tl.periods) == 1 else 's'}.**")
    lines.append("")

    for period in tl.periods:
        lines += [f"## {period.label}", ""]
        for entry in period.entries:
            lines.append(f"- `{entry.kind}` **{entry.title}** — {entry.summary}")
        lines.append("")

    return "\n".join(lines)


def render_summary(tl: Timeline, console: Console) -> None:
    """Render *tl* to *console* using Rich (no side effects beyond printing)."""
    from rich.text import Text

    if tl.total == 0:
        console.print("[dim]No history yet — the brain has no memories to narrate.[/dim]")
        for note in tl.notes:
            console.print(f"[dim]note: {note}[/dim]")
        return

    header = Text()
    header.append("Repo evolution timeline", style="bold")
    header.append(
        f"  ({tl.total} milestone{'' if tl.total == 1 else 's'}, "
        f"{len(tl.periods)} period{'' if len(tl.periods) == 1 else 's'})",
        style="dim",
    )
    console.print(header)
    for note in tl.notes:
        console.print(f"[yellow]note:[/yellow] [dim]{note}[/dim]")
    console.print("")

    for period in tl.periods:
        console.print(Text(period.label, style="bold cyan"))
        for entry in period.entries:
            line = Text("  • ")
            line.append(f"[{entry.kind}] ", style="magenta")
            line.append(entry.title, style="bold")
            if entry.summary:
                line.append(f" — {entry.summary}", style="dim")
            console.print(line)
        console.print("")
