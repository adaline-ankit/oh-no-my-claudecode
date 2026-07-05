"""Pure RPG-gamification engine for onmc.

Converts verified run receipts + open work-items into a quest log with
XP, levels, achievements, streaks, boss-fights, and loot.

Design principles
-----------------
- **Deterministic**: caller injects ``now``; no ``datetime.now()`` or
  ``random`` inside the engine.
- **Pure**: zero I/O.  The only side-effects are in ``commands.py``.
- **Honest**: XP is earned only from *verified* receipts.  Unverified
  runs contribute 0 XP (they're noted in the log but not rewarded).

XP formula
----------
Each verified receipt earns::

    xp = BASE_XP_PER_VERIFIED + round(wall_seconds / SECONDS_PER_BONUS_XP)

``wall_seconds`` is capped at ``MAX_WALL_SECONDS`` so a single marathon
run cannot dwarf the rest of the log.

Level curve
-----------
We use a simple triangular curve: level L requires a total of
``L * (L + 1) * XP_LEVEL_FACTOR / 2`` XP.  The inverse is the positive
root of the quadratic.  Level 1 starts at 0 XP.

Achievements
------------
Thresholds are checked against aggregated facts (total verified,
streak, boss defeats, etc.).  Each achievement has a unique ``key``
and a human-readable ``label``.

Boss-fights
-----------
An open work item (inbox item / task) is a boss if it contains any
of ``_BOSS_KEYWORDS``.  Bosses appear in the active-quests list with
``is_boss=True`` and separately in ``boss_fights``.

Loot
----
The most recent N *verified* receipts are surfaced as loot drops.
Each receipt earns a loot name derived from its goal.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

#: XP awarded per verified run (floor).
BASE_XP_PER_VERIFIED: int = 50

#: One bonus XP for every this many wall seconds spent (capped at MAX_WALL_SECONDS).
SECONDS_PER_BONUS_XP: int = 30

#: Maximum wall seconds counted toward bonus XP per run.
MAX_WALL_SECONDS: float = 1800.0

#: Level-curve factor; total XP for level L = L*(L+1)*FACTOR//2.
XP_LEVEL_FACTOR: int = 100

#: Maximum loot items surfaced in the quest log.
MAX_LOOT: int = 10

#: Maximum days between verified runs for streak to continue.
STREAK_GAP_DAYS: int = 1

#: Keywords that flag an open task as a "boss fight".
_BOSS_KEYWORDS: frozenset[str] = frozenset(
    {
        "refactor",
        "migrate",
        "overhaul",
        "rewrite",
        "security",
        "critical",
        "breaking",
        "performance",
        "architecture",
        "redesign",
        "complex",
        "hard",
        "difficult",
        "urgent",
        "risk",
        "risky",
        "dangerous",
    }
)

# ---------------------------------------------------------------------------
# Achievement catalogue
# ---------------------------------------------------------------------------

_ACHIEVEMENT_CATALOGUE: list[dict[str, Any]] = [
    {
        "key": "first_blood",
        "label": "First Blood",
        "description": "Completed your first verified run.",
        "check": lambda facts: facts["verified_total"] >= 1,
    },
    {
        "key": "ten_runs",
        "label": "Seasoned Adventurer",
        "description": "Completed 10 verified runs.",
        "check": lambda facts: facts["verified_total"] >= 10,
    },
    {
        "key": "fifty_runs",
        "label": "Veteran",
        "description": "Completed 50 verified runs.",
        "check": lambda facts: facts["verified_total"] >= 50,
    },
    {
        "key": "hundred_runs",
        "label": "Legend",
        "description": "Completed 100 verified runs.",
        "check": lambda facts: facts["verified_total"] >= 100,
    },
    {
        "key": "streak_3",
        "label": "On a Roll",
        "description": "Maintained a 3-day active streak.",
        "check": lambda facts: facts["streak_days"] >= 3,
    },
    {
        "key": "streak_5",
        "label": "Unstoppable",
        "description": "Maintained a 5-day active streak.",
        "check": lambda facts: facts["streak_days"] >= 5,
    },
    {
        "key": "streak_10",
        "label": "Monk Mode",
        "description": "Maintained a 10-day active streak.",
        "check": lambda facts: facts["streak_days"] >= 10,
    },
    {
        "key": "boss_slayer",
        "label": "Boss Slayer",
        "description": "Slayed a boss (completed a gnarly high-risk task).",
        "check": lambda facts: facts["boss_defeats"] >= 1,
    },
    {
        "key": "boss_hunter",
        "label": "Boss Hunter",
        "description": "Slayed 5 bosses.",
        "check": lambda facts: facts["boss_defeats"] >= 5,
    },
    {
        "key": "level_5",
        "label": "Rising Hero",
        "description": "Reached level 5.",
        "check": lambda facts: facts["level"] >= 5,
    },
    {
        "key": "level_10",
        "label": "Champion",
        "description": "Reached level 10.",
        "check": lambda facts: facts["level"] >= 10,
    },
    {
        "key": "level_20",
        "label": "Grand Master",
        "description": "Reached level 20.",
        "check": lambda facts: facts["level"] >= 20,
    },
    {
        "key": "rich_loot",
        "label": "Treasure Hunter",
        "description": "Accumulated 10 loot drops.",
        "check": lambda facts: facts["loot_total"] >= 10,
    },
    {
        "key": "cost_saver",
        "label": "Cost Optimizer",
        "description": "Completed a verified run at zero reported cost.",
        "check": lambda facts: facts["has_free_run"],
    },
]

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Achievement:
    """A single unlocked achievement.

    Fields
    ------
    key:
        Stable machine-readable identifier.
    label:
        Short human-readable name shown in the UI.
    description:
        One-sentence flavour text.
    """

    key: str
    label: str
    description: str


@dataclass(frozen=True)
class Loot:
    """A completed verified run rendered as an RPG loot drop.

    Fields
    ------
    receipt_goal:
        Original goal string from the receipt.
    name:
        Derived loot item name (capitalised slug of the goal).
    xp_earned:
        XP this run contributed.
    verified:
        Always ``True`` for loot (unverified runs are excluded).
    ended_at:
        ISO-8601 UTC timestamp of completion, or empty string if absent.
    """

    receipt_goal: str
    name: str
    xp_earned: int
    verified: bool
    ended_at: str


@dataclass(frozen=True)
class ActiveQuest:
    """An open work item surfaced as a quest.

    Fields
    ------
    text:
        Task description.
    source:
        Origin of the task (e.g. ``"manual"``, ``"todo"``, ``"coverage"``).
    score:
        Numeric priority score from the inbox ranker (higher = more urgent).
    is_boss:
        ``True`` when the task contains boss-fight keywords.
    """

    text: str
    source: str
    score: float
    is_boss: bool


@dataclass(frozen=True)
class BossFight:
    """A high-priority or high-risk open task elevated to boss status.

    This is a filtered view of :class:`ActiveQuest` (``is_boss=True``)
    presented separately for emphasis.

    Fields
    ------
    text:
        Task description.
    source:
        Origin of the task.
    score:
        Numeric priority score.
    """

    text: str
    source: str
    score: float


@dataclass
class QuestLog:
    """The complete gamified state of the onmc session.

    Fields
    ------
    level:
        Current level (1 = novice, no upper bound).
    total_xp:
        All XP earned so far.
    xp_to_next:
        XP needed to reach the next level (0 at max-level edge cases).
    streak_days:
        Consecutive calendar days with at least one verified run.
    active_quests:
        Open work items as quests (ranked by score, bosses first).
    boss_fights:
        Subset of active_quests that are boss-fight level.
    recent_loot:
        Most recent verified completions as loot (newest first).
    achievements:
        Unlocked achievements.
    total_runs:
        Total receipts loaded (verified + unverified).
    verified_total:
        Verified runs out of total.
    """

    level: int
    total_xp: int
    xp_to_next: int
    streak_days: int
    active_quests: list[ActiveQuest] = field(default_factory=list)
    boss_fights: list[BossFight] = field(default_factory=list)
    recent_loot: list[Loot] = field(default_factory=list)
    achievements: list[Achievement] = field(default_factory=list)
    total_runs: int = 0
    verified_total: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view."""
        return {
            "level": self.level,
            "total_xp": self.total_xp,
            "xp_to_next": self.xp_to_next,
            "streak_days": self.streak_days,
            "total_runs": self.total_runs,
            "verified_total": self.verified_total,
            "active_quests": [
                {
                    "text": q.text,
                    "source": q.source,
                    "score": q.score,
                    "is_boss": q.is_boss,
                }
                for q in self.active_quests
            ],
            "boss_fights": [
                {"text": b.text, "source": b.source, "score": b.score}
                for b in self.boss_fights
            ],
            "recent_loot": [
                {
                    "name": lo.name,
                    "receipt_goal": lo.receipt_goal,
                    "xp_earned": lo.xp_earned,
                    "ended_at": lo.ended_at,
                }
                for lo in self.recent_loot
            ],
            "achievements": [
                {
                    "key": a.key,
                    "label": a.label,
                    "description": a.description,
                }
                for a in self.achievements
            ],
        }


# ---------------------------------------------------------------------------
# Helper: XP / level math
# ---------------------------------------------------------------------------


def _xp_for_receipt(receipt: dict[str, Any]) -> int:
    """XP earned from a single verified receipt.

    Unverified receipts return 0 — XP is only for real completions.
    """
    if not bool(receipt.get("verified", False)):
        return 0
    wall = min(float(receipt.get("wall_seconds") or 0.0), MAX_WALL_SECONDS)
    bonus = int(wall / SECONDS_PER_BONUS_XP)
    return BASE_XP_PER_VERIFIED + bonus


def _total_xp_for_level(level: int) -> int:
    """Cumulative XP required to *reach* ``level`` from level 1.

    Level 1 requires 0 XP.  Each level requires more than the last,
    using a triangular ramp: XP(L) = L*(L-1)*FACTOR/2.
    """
    if level <= 1:
        return 0
    return (level - 1) * level * XP_LEVEL_FACTOR // 2


def _level_from_xp(total_xp: int) -> int:
    """Level corresponding to *total_xp* (always >= 1).

    Inverts the triangular curve: L = floor((1 + sqrt(1 + 8*xp/FACTOR)) / 2).
    """
    if total_xp <= 0:
        return 1
    discriminant = 1.0 + 8.0 * total_xp / XP_LEVEL_FACTOR
    level = int((1.0 + math.sqrt(discriminant)) / 2.0)
    return max(1, level)


def _xp_to_next_level(current_level: int, total_xp: int) -> int:
    """XP remaining until the next level."""
    xp_for_next = _total_xp_for_level(current_level + 1)
    return max(0, xp_for_next - total_xp)


# ---------------------------------------------------------------------------
# Helper: streak calculation
# ---------------------------------------------------------------------------


def _streak_days(receipts: list[dict[str, Any]], now: datetime) -> int:
    """Count consecutive calendar days (ending today) with a verified run.

    A "day" is a UTC calendar day.  The streak is the longest suffix of
    consecutive days (up to and including today) that each have at least one
    verified receipt.  If today has no verified run, the streak is 0.
    """
    verified_dates: set[Any] = set()
    for r in receipts:
        if not bool(r.get("verified", False)):
            continue
        ts_raw = r.get("ended_at") or r.get("started_at")
        if not ts_raw:
            continue
        try:
            dt = _parse_iso(str(ts_raw))
        except ValueError:
            continue
        verified_dates.add(dt.date())

    today = now.astimezone(UTC).date()
    if today not in verified_dates:
        return 0

    streak = 0
    current = today
    while current in verified_dates:
        streak += 1
        from datetime import timedelta

        current = current - timedelta(days=1)
    return streak


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp; raises ValueError on failure."""
    # Accept trailing Z as UTC.
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


# ---------------------------------------------------------------------------
# Helper: loot naming
# ---------------------------------------------------------------------------


def _loot_name(goal: str) -> str:
    """Derive a short loot-item name from a goal string.

    Takes up to the first 5 significant words, title-cased.
    """
    words = re.findall(r"[A-Za-z0-9]+", goal)
    significant = [w for w in words if len(w) >= 2][:5]
    if not significant:
        return "Mysterious Artefact"
    return " ".join(w.capitalize() for w in significant)


# ---------------------------------------------------------------------------
# Helper: boss detection
# ---------------------------------------------------------------------------


def _is_boss(text: str) -> bool:
    """True when the task text contains any boss-fight keyword."""
    lower = text.lower()
    return any(kw in lower for kw in _BOSS_KEYWORDS)


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


def compute_quests(
    receipts: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    *,
    now: datetime,
) -> QuestLog:
    """Compute the complete quest log from receipts and open tasks.

    Parameters
    ----------
    receipts:
        Receipt dicts (schema_version "2" shape from
        :func:`oh_no_my_claudecode.ledger.accounting.load_receipts`).
        Corrupt / partial entries are skipped defensively.
    tasks:
        Open work-item dicts with at minimum ``"text"`` (str), ``"source"``
        (str), and ``"score"`` (float) keys — the same shape produced by
        :func:`oh_no_my_claudecode.inbox.queue.gather_candidates`.
        Missing keys are handled with sensible defaults.
    now:
        Current UTC time (injected for determinism; never read from wall clock
        inside this function).

    Returns
    -------
    QuestLog
        Fully populated quest log.  Safe to call with empty inputs — returns
        a level-1, 0-XP log with no quests, loot, or achievements.
    """
    # --- XP + level ---
    total_xp = 0
    verified_total = 0
    total_runs = 0
    has_free_run = False
    valid_receipts: list[dict[str, Any]] = []

    for r in receipts:
        if not isinstance(r, dict):
            continue
        total_runs += 1
        xp = _xp_for_receipt(r)
        total_xp += xp
        if bool(r.get("verified", False)):
            verified_total += 1
            if r.get("cost_usd") == 0 or r.get("cost_usd") == 0.0:
                has_free_run = True
        valid_receipts.append(r)

    level = _level_from_xp(total_xp)
    xp_to_next = _xp_to_next_level(level, total_xp)

    # --- streak ---
    streak = _streak_days(valid_receipts, now)

    # --- loot: most recent verified receipts ---
    verified_receipts = [r for r in valid_receipts if bool(r.get("verified", False))]
    # Sort newest-first using ended_at / started_at; undated go last.
    def _sort_key(r: dict[str, Any]) -> str:
        ts = r.get("ended_at") or r.get("started_at") or ""
        return str(ts)

    verified_receipts.sort(key=_sort_key, reverse=True)
    recent_loot: list[Loot] = []
    for r in verified_receipts[:MAX_LOOT]:
        goal = str(r.get("goal") or "")
        xp = _xp_for_receipt(r)
        recent_loot.append(
            Loot(
                receipt_goal=goal,
                name=_loot_name(goal),
                xp_earned=xp,
                verified=True,
                ended_at=str(r.get("ended_at") or r.get("started_at") or ""),
            )
        )

    # --- active quests + boss fights ---
    active_quests: list[ActiveQuest] = []
    boss_fights: list[BossFight] = []

    for t in tasks:
        if not isinstance(t, dict):
            continue
        text = str(t.get("text") or "")
        source = str(t.get("source") or "unknown")
        score = float(t.get("score") or 0.0)
        boss = _is_boss(text)
        active_quests.append(
            ActiveQuest(text=text, source=source, score=score, is_boss=boss)
        )
        if boss:
            boss_fights.append(BossFight(text=text, source=source, score=score))

    # Sort active quests: bosses first, then by score descending.
    active_quests.sort(key=lambda q: (not q.is_boss, -q.score))
    boss_fights.sort(key=lambda b: -b.score)

    # --- boss defeats: verified receipts whose goal contains a boss keyword ---
    boss_defeats = sum(
        1
        for r in valid_receipts
        if bool(r.get("verified", False)) and _is_boss(str(r.get("goal") or ""))
    )

    # --- achievements ---
    facts: dict[str, Any] = {
        "verified_total": verified_total,
        "streak_days": streak,
        "boss_defeats": boss_defeats,
        "level": level,
        "loot_total": len(verified_receipts),
        "has_free_run": has_free_run,
    }
    achievements: list[Achievement] = []
    for entry in _ACHIEVEMENT_CATALOGUE:
        try:
            if entry["check"](facts):
                achievements.append(
                    Achievement(
                        key=entry["key"],
                        label=entry["label"],
                        description=entry["description"],
                    )
                )
        except Exception:  # noqa: BLE001, S110
            pass  # skip broken achievement check; never crash the quest log

    return QuestLog(
        level=level,
        total_xp=total_xp,
        xp_to_next=xp_to_next,
        streak_days=streak,
        active_quests=active_quests,
        boss_fights=boss_fights,
        recent_loot=recent_loot,
        achievements=achievements,
        total_runs=total_runs,
        verified_total=verified_total,
    )
