"""Pure engine: run receipts -> XP, streak, level, and unlocked badges.

Methodology (honest description)
---------------------------------
Consumes the same receipt dicts :func:`oh_no_my_claudecode.ledger.accounting.load_receipts`
produces (schema_version "2") — no new schema, no new storage. The fields read:

- ``verified``     — honest success flag; XP and streaks are earned from
  verified runs ONLY. Unverified runs count toward total run stats but never
  earn XP or extend a streak.
- ``iterations``   — loop-convergence iteration count; used for the
  "One-Shot" badge (verified in a single iteration).
- ``ended_at`` / ``started_at`` — ISO-8601 UTC timestamps used to order runs
  chronologically for streak computation (``ended_at`` preferred).

Honesty constraints
~~~~~~~~~~~~~~~~~~~
- **No randomness.** All XP/badge/level definitions are fixed constants in
  this module.
- **Clock-free core.** Every function here is pure; the CLI layer is the only
  place that reads real receipts or the wall clock.
- **Zero-state is explicit.** Zero receipts (or zero verified receipts)
  produces an honest empty report, never a fabricated badge or streak.

XP formula
----------
Each verified receipt earns :data:`XP_PER_VERIFIED`. A one-shot run (verified
with ``iterations <= 1``) earns an additional :data:`XP_ONE_SHOT_BONUS`.
Unverified receipts earn 0 XP.

Level curve
-----------
Same triangular curve used elsewhere in onmc's gamification features: level
``L`` requires a total of ``L * (L + 1) * LEVEL_XP_FACTOR / 2`` XP. Level 1
starts at 0 XP.

Streak
------
Receipts are ordered by timestamp (``ended_at`` then ``started_at``;
receipts with neither sort last and cannot start or extend a streak). The
*current* streak is the number of trailing verified receipts in that order
(i.e. how many of the most recent runs, walking backwards, were verified
without interruption). The *longest* streak is the longest run of
consecutive verified receipts anywhere in the ordered sequence.

Badges
------
Thresholds are checked against aggregated facts (total verified, current/
longest streak, one-shot count, total runs). Each badge has a stable ``key``,
a human-readable ``label``, and — once unlocked — the timestamp of the
receipt that unlocked it (``None`` when unearned).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Tunable constants (deterministic, no magic — all named here)
# ---------------------------------------------------------------------------

#: XP earned per verified run.
XP_PER_VERIFIED = 10

#: Extra XP earned when a verified run converged in a single iteration.
XP_ONE_SHOT_BONUS = 5

#: Level curve factor: total XP to reach level L is L*(L+1)*FACTOR/2.
LEVEL_XP_FACTOR = 10

#: Total verified runs required for the "Marathoner" badge.
MARATHONER_VERIFIED_THRESHOLD = 25

#: Consecutive verified runs required for the "Perfect 10" badge.
PERFECT_STREAK_THRESHOLD = 10


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Achievement:
    """A single badge definition, unlocked or not.

    Fields
    ------
    key:
        Stable machine-readable identifier.
    label:
        Short human-readable name shown in the UI.
    description:
        One-sentence flavour text explaining how to earn it.
    unlocked_at:
        ISO-8601 timestamp of the receipt that unlocked this badge, or
        ``None`` when it has not been earned yet.
    """

    key: str
    label: str
    description: str
    unlocked_at: str | None = None

    @property
    def unlocked(self) -> bool:
        return self.unlocked_at is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "unlocked": self.unlocked,
            "unlocked_at": self.unlocked_at,
        }


@dataclass(frozen=True)
class AchievementsReport:
    """Aggregated achievements summary over a set of run receipts.

    Fields
    ------
    total_runs:
        Number of receipts considered (verified + unverified).
    verified_total:
        Number of receipts with ``verified=True``.
    total_xp:
        Sum of XP earned across all verified receipts.
    level:
        Current level derived from ``total_xp`` via the triangular curve.
    xp_into_level:
        XP earned past the floor of the current level.
    xp_to_next_level:
        XP still needed to reach ``level + 1``.
    current_streak:
        Trailing consecutive verified-run count (most recent runs first).
    longest_streak:
        Longest consecutive verified-run count anywhere in the ordered log.
    one_shot_count:
        Number of verified receipts that converged in a single iteration.
    badges:
        Every badge in the catalogue, each carrying its own unlocked state.
    """

    total_runs: int
    verified_total: int
    total_xp: int
    level: int
    xp_into_level: int
    xp_to_next_level: int
    current_streak: int
    longest_streak: int
    one_shot_count: int
    badges: tuple[Achievement, ...] = field(default_factory=tuple)

    @property
    def unlocked_badges(self) -> tuple[Achievement, ...]:
        return tuple(b for b in self.badges if b.unlocked)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_runs": self.total_runs,
            "verified_total": self.verified_total,
            "total_xp": self.total_xp,
            "level": self.level,
            "xp_into_level": self.xp_into_level,
            "xp_to_next_level": self.xp_to_next_level,
            "current_streak": self.current_streak,
            "longest_streak": self.longest_streak,
            "one_shot_count": self.one_shot_count,
            "badges": [b.to_dict() for b in self.badges],
            "unlocked_count": len(self.unlocked_badges),
        }


# ---------------------------------------------------------------------------
# Timestamp helpers (mirrors ledger.accounting's parsing, kept local so this
# module stays independently importable and pure)
# ---------------------------------------------------------------------------


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 UTC string; return None on failure or empty input."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _receipt_when(receipt: dict[str, Any]) -> datetime | None:
    """Return the receipt's timestamp (``ended_at`` preferred, then ``started_at``)."""
    return _parse_iso(str(receipt.get("ended_at") or "")) or _parse_iso(
        str(receipt.get("started_at") or "")
    )


def _is_verified(receipt: dict[str, Any]) -> bool:
    return bool(receipt.get("verified"))


def _is_one_shot(receipt: dict[str, Any]) -> bool:
    """True when a verified receipt converged in a single iteration."""
    if not _is_verified(receipt):
        return False
    iterations = receipt.get("iterations")
    if not isinstance(iterations, int | float):
        return False
    return iterations <= 1


def _order_receipts(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order receipts chronologically by timestamp.

    Receipts with no parseable timestamp sort last (stable), in their
    original relative order, so they can never be mistaken for the most
    recent run when computing the current streak.
    """
    dated = [r for r in receipts if _receipt_when(r) is not None]
    undated = [r for r in receipts if _receipt_when(r) is None]
    dated.sort(key=lambda r: _receipt_when(r) or datetime.min)
    return [*dated, *undated]


# ---------------------------------------------------------------------------
# XP / level curve
# ---------------------------------------------------------------------------


def _xp_for_receipt(receipt: dict[str, Any]) -> int:
    """XP earned from a single receipt; 0 for unverified runs."""
    if not _is_verified(receipt):
        return 0
    xp = XP_PER_VERIFIED
    if _is_one_shot(receipt):
        xp += XP_ONE_SHOT_BONUS
    return xp


def _total_xp_for_level(level: int) -> int:
    """Total XP required to *reach* ``level`` (level 1 == 0 XP)."""
    n = level - 1
    return int(n * (n + 1) * LEVEL_XP_FACTOR / 2)


def _level_from_xp(total_xp: int) -> int:
    """Inverse of :func:`_total_xp_for_level`: the level ``total_xp`` falls into."""
    if total_xp <= 0:
        return 1
    # Solve n*(n+1)*FACTOR/2 <= total_xp for the largest integer n >= 0,
    # then level = n + 1.
    n = int((-1 + math.sqrt(1 + 8 * total_xp / LEVEL_XP_FACTOR)) / 2)
    # Guard against floating-point rounding at the boundary.
    while _total_xp_for_level(n + 2) <= total_xp:
        n += 1
    while n > 0 and _total_xp_for_level(n + 1) > total_xp:
        n -= 1
    return n + 1


# ---------------------------------------------------------------------------
# Streak computation
# ---------------------------------------------------------------------------


def _current_streak(ordered: list[dict[str, Any]]) -> int:
    """Trailing consecutive verified-run count, walking back from the newest."""
    streak = 0
    for receipt in reversed(ordered):
        if _is_verified(receipt):
            streak += 1
        else:
            break
    return streak


def _longest_streak(ordered: list[dict[str, Any]]) -> int:
    """Longest run of consecutive verified receipts anywhere in the sequence."""
    longest = 0
    running = 0
    for receipt in ordered:
        if _is_verified(receipt):
            running += 1
            longest = max(longest, running)
        else:
            running = 0
    return longest


# ---------------------------------------------------------------------------
# Badge catalogue
# ---------------------------------------------------------------------------
#
# Each entry is checked, in order, against the running facts *after* each
# receipt is processed chronologically — so ``unlocked_at`` reflects the
# timestamp of the receipt that first satisfied the condition. ``check``
# receives the facts dict accumulated so far (inclusive of the current
# receipt).

_BADGE_CATALOGUE: list[dict[str, Any]] = [
    {
        "key": "first_blood",
        "label": "First Blood",
        "description": "Landed your first verified run.",
        "check": lambda facts: facts["verified_total"] >= 1,
    },
    {
        "key": "one_shot",
        "label": "One-Shot",
        "description": "Landed a verified run in a single iteration.",
        "check": lambda facts: facts["one_shot_count"] >= 1,
    },
    {
        "key": "perfect_streak",
        "label": "Perfect 10",
        "description": f"Strung together {PERFECT_STREAK_THRESHOLD} verified runs in a row.",
        "check": lambda facts: facts["running_streak"] >= PERFECT_STREAK_THRESHOLD,
    },
    {
        "key": "marathoner",
        "label": "Marathoner",
        "description": f"Completed {MARATHONER_VERIFIED_THRESHOLD}+ verified runs.",
        "check": lambda facts: facts["verified_total"] >= MARATHONER_VERIFIED_THRESHOLD,
    },
]


def _compute_badges(ordered: list[dict[str, Any]]) -> tuple[Achievement, ...]:
    """Walk receipts chronologically, unlocking badges the first moment they qualify."""
    unlocked_at: dict[str, str | None] = {entry["key"]: None for entry in _BADGE_CATALOGUE}

    verified_total = 0
    one_shot_count = 0
    running_streak = 0

    for receipt in ordered:
        if _is_verified(receipt):
            verified_total += 1
            running_streak += 1
        else:
            running_streak = 0
            continue

        if _is_one_shot(receipt):
            one_shot_count += 1

        facts = {
            "verified_total": verified_total,
            "one_shot_count": one_shot_count,
            "running_streak": running_streak,
        }
        when = _receipt_when(receipt)
        stamp = when.isoformat() if when is not None else None

        for entry in _BADGE_CATALOGUE:
            key = entry["key"]
            if unlocked_at[key] is not None:
                continue
            if entry["check"](facts):
                unlocked_at[key] = stamp

    return tuple(
        Achievement(
            key=entry["key"],
            label=entry["label"],
            description=entry["description"],
            unlocked_at=unlocked_at[entry["key"]],
        )
        for entry in _BADGE_CATALOGUE
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_report(receipts: list[dict[str, Any]]) -> AchievementsReport:
    """Compute an :class:`AchievementsReport` from a list of receipt dicts.

    Pure: no I/O, no wall-clock reads, no randomness. Safe on an empty list
    (returns an all-zero report with every badge locked).
    """
    ordered = _order_receipts(receipts)

    total_runs = len(ordered)
    verified_total = sum(1 for r in ordered if _is_verified(r))
    total_xp = sum(_xp_for_receipt(r) for r in ordered)
    one_shot_count = sum(1 for r in ordered if _is_one_shot(r))

    level = _level_from_xp(total_xp)
    xp_into_level = total_xp - _total_xp_for_level(level)
    xp_to_next_level = _total_xp_for_level(level + 1) - total_xp

    current_streak = _current_streak(ordered)
    longest_streak = _longest_streak(ordered)
    badges = _compute_badges(ordered)

    return AchievementsReport(
        total_runs=total_runs,
        verified_total=verified_total,
        total_xp=total_xp,
        level=level,
        xp_into_level=xp_into_level,
        xp_to_next_level=xp_to_next_level,
        current_streak=current_streak,
        longest_streak=longest_streak,
        one_shot_count=one_shot_count,
        badges=badges,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_text(report: AchievementsReport) -> str:
    """Render *report* as a plain-text achievements card.

    Deterministic, dependency-free (no Rich) so it is safe to use as the
    fallback renderer and directly assertable in tests.
    """
    if report.total_runs == 0:
        return "No verified runs yet — earn your first badge with `onmc loop` or `onmc swarm`."

    lines = [
        f"Level {report.level}  |  {report.total_xp} XP total"
        f"  |  {report.xp_to_next_level} XP to next level",
        f"Runs: {report.verified_total}/{report.total_runs} verified",
        f"Streak: {report.current_streak} current  |  {report.longest_streak} longest",
    ]

    unlocked = report.unlocked_badges
    if unlocked:
        lines.append(f"\nBadges unlocked ({len(unlocked)}/{len(report.badges)}):")
        for badge in unlocked:
            lines.append(f"  [{badge.key}] {badge.label} — {badge.description}")
            lines.append(f"      unlocked {badge.unlocked_at}")
    else:
        lines.append("\nNo badges unlocked yet — earn your first badge!")

    locked = [b for b in report.badges if not b.unlocked]
    if locked:
        lines.append(f"\nLocked ({len(locked)}):")
        for badge in locked:
            lines.append(f"  [{badge.key}] {badge.label} — {badge.description}")

    return "\n".join(lines)


__all__ = [
    "XP_ONE_SHOT_BONUS",
    "XP_PER_VERIFIED",
    "LEVEL_XP_FACTOR",
    "MARATHONER_VERIFIED_THRESHOLD",
    "PERFECT_STREAK_THRESHOLD",
    "Achievement",
    "AchievementsReport",
    "build_report",
    "render_text",
]
