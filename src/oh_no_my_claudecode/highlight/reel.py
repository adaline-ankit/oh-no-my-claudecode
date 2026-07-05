"""Pure, deterministic highlight-reel engine for onmc sessions.

Converts verified run receipts into a curated, ranked "best-of" recap —
like a sports highlight reel. Each moment is a punchy one-liner that
celebrates a specific achievement from the session.

Design principles
-----------------
- **Deterministic**: caller injects ``now``; no ``datetime.now()`` or
  ``random`` inside the engine.
- **Pure**: zero I/O. The only side-effects are in ``commands.py``.
- **Honest**: moments are drawn only from *verified* receipts.
  Unverified runs never appear in the reel.
- **Distinct from replay/timeline**: highlight is a CURATED, RANKED
  best-of — not a step-by-step replay or a chronological narrative.

Moment kinds
------------

``biggest_win``
    The verified run with the highest compound value score
    (wall time invested × a small bonus for cost, as a proxy for
    "we put real work in and it paid off"). Never trivial.

``boss_kill``
    The verified run that took the longest wall time (hardest task
    completed). Distinct from biggest_win when an expensive short run
    beats a long cheap one on value.

``longest_streak``
    Maximum number of consecutive calendar days (UTC) that contained
    at least one verified run. Surfaced as a moment when streak ≥ 2.

``most_efficient``
    Verified run with the best outcome-to-cost ratio — either the
    fastest verified run *with* a recorded cost, or the fastest
    overall when cost data is absent.

``fastest_merge``
    Verified run with the shortest wall time (quick wins matter).

Moment ranking
--------------
Moments are ranked by a fixed priority order so the reel always
surfaces the most spectacular achievement first. ``biggest_win``
and ``boss_kill`` are shown before streak/efficiency moments.

Empty inputs return an empty :class:`Reel` — the command renders a
"no highlights yet" message and exits 0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

#: Multiplier applied to normalised cost when computing value score.
#: Keeps cost influence mild relative to wall-time contribution.
_COST_WEIGHT: float = 0.3

#: Minimum streak length (days) to emit a streak moment.
_MIN_STREAK_DAYS: int = 2

#: Maximum words taken from a goal string for a moment label.
_MAX_GOAL_WORDS: int = 6

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Moment:
    """A single highlight moment.

    Fields
    ------
    kind:
        Machine-readable category. One of: ``"biggest_win"``,
        ``"boss_kill"``, ``"longest_streak"``, ``"most_efficient"``,
        ``"fastest_merge"``.
    emoji:
        A single representative emoji for the moment (plain text).
    headline:
        Short punchy description (one line, ≤ 120 chars).
    detail:
        Optional supporting metric (e.g. "42 s wall time").
    receipt_goal:
        Source receipt's goal string, or empty when not receipt-derived
        (e.g. streak moments).
    """

    kind: str
    emoji: str
    headline: str
    detail: str
    receipt_goal: str


@dataclass
class Reel:
    """A curated highlight reel of session moments.

    Fields
    ------
    moments:
        Ordered list of highlight moments, most spectacular first.
    total_verified:
        Count of verified receipts that fed the reel.
    total_receipts:
        Total receipts seen (verified + unverified).
    streak_days:
        Longest consecutive-day streak of verified runs found.
    """

    moments: list[Moment] = field(default_factory=list)
    total_verified: int = 0
    total_receipts: int = 0
    streak_days: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "total_verified": self.total_verified,
            "total_receipts": self.total_receipts,
            "streak_days": self.streak_days,
            "moments": [
                {
                    "kind": m.kind,
                    "emoji": m.emoji,
                    "headline": m.headline,
                    "detail": m.detail,
                    "receipt_goal": m.receipt_goal,
                }
                for m in self.moments
            ],
        }


# ---------------------------------------------------------------------------
# Internal helpers (pure)
# ---------------------------------------------------------------------------


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO-8601 UTC timestamp; return None on failure."""
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


def _receipt_time(r: dict[str, Any]) -> datetime | None:
    """Return the best available timestamp for a receipt."""
    return _parse_iso(str(r.get("ended_at") or "")) or _parse_iso(
        str(r.get("started_at") or "")
    )


def _wall_seconds(r: dict[str, Any]) -> float:
    """Wall time in seconds from a receipt; 0.0 if absent or invalid."""
    raw = r.get("wall_seconds")
    try:
        return max(0.0, float(raw))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _cost_usd(r: dict[str, Any]) -> float | None:
    """Cost in USD from a receipt; None if absent or zero."""
    raw = r.get("cost_usd")
    if raw is None:
        return None
    try:
        val = float(raw)
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def _value_score(r: dict[str, Any]) -> float:
    """Compound value score for sorting "biggest win".

    Score = wall_seconds + cost_usd * COST_WEIGHT * 3600
    (cost normalised to equivalent seconds at $1/hr).
    Wall seconds is the dominant signal; cost is a mild bonus.
    """
    wall = _wall_seconds(r)
    cost = _cost_usd(r)
    bonus = (cost * _COST_WEIGHT * 3600.0) if cost is not None else 0.0
    return wall + bonus


def _short_goal(goal: str) -> str:
    """A concise label derived from a goal string.

    Takes the first _MAX_GOAL_WORDS significant words, title-cased.
    Falls back to "mystery task" when the goal is empty.
    """
    words = re.findall(r"[A-Za-z0-9]+", goal)
    significant = [w for w in words if len(w) >= 2][:_MAX_GOAL_WORDS]
    if not significant:
        return "mystery task"
    return " ".join(w.capitalize() for w in significant)


def _longest_streak(receipts: list[dict[str, Any]], now: datetime) -> int:
    """Longest run of consecutive UTC calendar days with a verified run.

    This is the global maximum streak over all time, not just the current
    streak (which would require it to extend to today).
    """
    dates: list[datetime] = []
    for r in receipts:
        ts = _receipt_time(r)
        if ts is not None:
            dates.append(ts)

    if not dates:
        return 0

    date_set = {d.date() for d in dates}
    if not date_set:
        return 0

    # Walk each unique date and extend the streak.
    best = 0
    for start in sorted(date_set):
        length = 0
        cur = start
        while cur in date_set:
            length += 1
            cur = cur + timedelta(days=1)
        best = max(best, length)

    # Also compute current (trailing) streak from now.
    today = now.date()
    if today in date_set:
        streak = 0
        cur = today
        while cur in date_set:
            streak += 1
            cur = cur - timedelta(days=1)
        best = max(best, streak)

    return best


# ---------------------------------------------------------------------------
# Moment builders (all pure)
# ---------------------------------------------------------------------------


def _biggest_win(verified: list[dict[str, Any]]) -> Moment | None:
    """Moment for the highest-value verified run."""
    if not verified:
        return None
    best = max(verified, key=_value_score)
    goal = str(best.get("goal") or "")
    label = _short_goal(goal)
    wall = _wall_seconds(best)
    cost = _cost_usd(best)
    parts = [f"{wall:.0f} s"]
    if cost is not None:
        parts.append(f"${cost:.4f}")
    detail = "  |  ".join(parts)
    return Moment(
        kind="biggest_win",
        emoji="trophy",
        headline=f"Biggest win: {label}",
        detail=detail,
        receipt_goal=goal,
    )


def _boss_kill(verified: list[dict[str, Any]]) -> Moment | None:
    """Moment for the verified run that took the longest wall time."""
    if not verified:
        return None
    hardest = max(verified, key=_wall_seconds)
    wall = _wall_seconds(hardest)
    if wall <= 0:
        return None
    goal = str(hardest.get("goal") or "")
    label = _short_goal(goal)
    mins = wall / 60.0
    detail = f"{mins:.1f} min wall time" if mins >= 1 else f"{wall:.0f} s wall time"
    return Moment(
        kind="boss_kill",
        emoji="skull",
        headline=f"Boss slain: {label}",
        detail=detail,
        receipt_goal=goal,
    )


def _streak_moment(streak: int) -> Moment | None:
    """Moment for a notable consecutive-day streak."""
    if streak < _MIN_STREAK_DAYS:
        return None
    if streak >= 7:
        headline = f"Week-long streak: {streak} days straight — unstoppable"
    elif streak >= 5:
        headline = f"5-day streak: {streak} days in a row — on fire"
    else:
        headline = f"{streak}-day streak: consistency compounds"
    return Moment(
        kind="longest_streak",
        emoji="fire",
        headline=headline,
        detail=f"{streak} consecutive days",
        receipt_goal="",
    )


def _most_efficient(verified: list[dict[str, Any]]) -> Moment | None:
    """Moment for the most cost-efficient verified run.

    Prefers the run with the best (lowest) cost-per-verified-second ratio.
    Falls back to the shortest run when cost data is absent.
    """
    if not verified:
        return None

    # Candidates with cost data.
    with_cost = [r for r in verified if _cost_usd(r) is not None]
    if with_cost:
        # Best = lowest cost among runs that actually did something (wall > 0).
        candidates = [r for r in with_cost if _wall_seconds(r) > 0]
        if not candidates:
            candidates = with_cost
        best = min(candidates, key=lambda r: (_cost_usd(r) or float("inf")))
        goal = str(best.get("goal") or "")
        label = _short_goal(goal)
        cost = _cost_usd(best)
        wall = _wall_seconds(best)
        detail = f"${cost:.4f}  |  {wall:.0f} s" if cost is not None else f"{wall:.0f} s"
        return Moment(
            kind="most_efficient",
            emoji="zap",
            headline=f"Most efficient: {label}",
            detail=detail,
            receipt_goal=goal,
        )

    # No cost data — surface fastest run instead.
    candidates = [r for r in verified if _wall_seconds(r) > 0]
    if not candidates:
        return None
    best = min(candidates, key=_wall_seconds)
    goal = str(best.get("goal") or "")
    label = _short_goal(goal)
    wall = _wall_seconds(best)
    return Moment(
        kind="most_efficient",
        emoji="zap",
        headline=f"Most efficient: {label}",
        detail=f"{wall:.0f} s — zero reported cost",
        receipt_goal=goal,
    )


def _fastest_merge(verified: list[dict[str, Any]]) -> Moment | None:
    """Moment for the shortest-wall-time verified run (quick wins)."""
    if not verified:
        return None
    candidates = [r for r in verified if _wall_seconds(r) > 0]
    if not candidates:
        return None
    fastest = min(candidates, key=_wall_seconds)
    wall = _wall_seconds(fastest)
    goal = str(fastest.get("goal") or "")
    label = _short_goal(goal)
    return Moment(
        kind="fastest_merge",
        emoji="lightning",
        headline=f"Speed run: {label}",
        detail=f"{wall:.0f} s wall time",
        receipt_goal=goal,
    )


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


def build_reel(
    receipts: list[dict[str, Any]],
    *,
    now: datetime,
    limit: int = 5,
    since: datetime | None = None,
) -> Reel:
    """Build a curated session highlight reel from run receipts.

    Parameters
    ----------
    receipts:
        Receipt dicts from
        :func:`oh_no_my_claudecode.ledger.accounting.load_receipts`.
        Malformed / partial entries are skipped defensively.
    now:
        Current UTC datetime (injected for determinism — never read from
        wall clock inside this function).
    limit:
        Maximum number of moments to include in the reel (default 5).
    since:
        Optional cutoff: only receipts at/after this datetime are
        considered. ``None`` includes all receipts.

    Returns
    -------
    Reel
        A curated reel. Safe to call with empty inputs — returns an empty
        reel with ``total_receipts == 0``.
    """
    total_receipts = 0
    verified: list[dict[str, Any]] = []

    for r in receipts:
        if not isinstance(r, dict):
            continue
        total_receipts += 1
        if not bool(r.get("verified", False)):
            continue
        if since is not None:
            ts = _receipt_time(r)
            if ts is None or ts.astimezone(UTC) < since.astimezone(UTC):
                continue
        verified.append(r)

    streak = _longest_streak(verified, now)

    # Build candidate moments in priority order.
    candidates: list[Moment | None] = [
        _biggest_win(verified),
        _boss_kill(verified),
        _streak_moment(streak),
        _most_efficient(verified),
        _fastest_merge(verified),
    ]

    # De-duplicate by kind only; different kinds may celebrate the same run
    # (e.g. the marathon session is legitimately both biggest_win and boss_kill).
    seen_kinds: set[str] = set()
    moments: list[Moment] = []
    for m in candidates:
        if m is None:
            continue
        if m.kind in seen_kinds:
            continue
        seen_kinds.add(m.kind)
        moments.append(m)
        if len(moments) >= limit:
            break

    return Reel(
        moments=moments,
        total_verified=len(verified),
        total_receipts=total_receipts,
        streak_days=streak,
    )


# ---------------------------------------------------------------------------
# Rendering (pure text)
# ---------------------------------------------------------------------------

_EMOJI_MAP: dict[str, str] = {
    "trophy": "🏆",
    "skull": "💀",
    "fire": "🔥",
    "zap": "⚡",
    "lightning": "⚡",
}


def _emoji(name: str) -> str:
    """Return the Unicode emoji for a name, with ASCII fallback."""
    return _EMOJI_MAP.get(name, name)


def render_markdown(reel: Reel) -> str:
    """Render the reel as a shareable Markdown block.

    Returns a plain-text fallback string when the reel is empty.
    """
    if not reel.moments:
        return (
            "## onmc highlight reel\n\n"
            "_No highlights yet — run `onmc loop` or `onmc swarm` "
            "to start earning verified completions._\n"
        )

    lines = [
        "## onmc highlight reel",
        "",
        f"> {reel.total_verified} verified run(s)  "
        f"|  {reel.streak_days}-day streak",
        "",
    ]
    for m in reel.moments:
        emoji = _emoji(m.emoji)
        lines.append(f"**{emoji} {m.headline}**")
        if m.detail:
            lines.append(f"  _{m.detail}_")
        lines.append("")

    lines.append(
        "_generated by [onmc](https://github.com/adaline-ankit/oh-no-my-claudecode)_"
    )
    return "\n".join(lines)
