"""Pure, deterministic HUD engine for ``onmc vibe``.

Aggregates coach streak, whip reward tally, and quest level/XP into a
single "mood" reading — a glanceable ambient status for the agent.

Design
------
- **Deterministic**: mood is computed from inputs only — no wallclock, no
  random, no I/O.  The same inputs always produce the same :class:`Mood`.
- **Pure**: zero side-effects.  All I/O lives in ``commands.py``.
- **Graceful degradation**: any source (coach / whip / quest) may be absent.
  The mood falls back to whatever components are available, or ``MEH`` when
  nothing is known.

Mood thresholds
---------------
The mood ladder (highest first):

=============  =========================================================
``ON_FIRE``    streak >= 5 AND praises/(praises+corrections) >= 0.6
``CRUISING``   streak >= 2 OR praises/(praises+corrections) >= 0.5 OR level >= 5
``MEH``        (default — neither good nor bad signals)
``STRUGGLING`` corrections > praises OR (streak == 0 AND total_rewards > 0)
=============  =========================================================

The computed ``score`` is a float in [0.0, 1.0] driving the mood label.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Mood enum
# ---------------------------------------------------------------------------


class Mood(StrEnum):
    """Agent mood levels, from lowest to highest energy."""

    STRUGGLING = "struggling"
    MEH = "meh"
    CRUISING = "cruising"
    ON_FIRE = "on_fire"

    @property
    def emoji(self) -> str:
        """Return the mood emoji."""
        return {
            Mood.ON_FIRE: "\U0001f525",       # 🔥
            Mood.CRUISING: "\U0001f60e",       # 😎
            Mood.MEH: "\U0001f610",            # 😐
            Mood.STRUGGLING: "\U0001f975",     # 🥵
        }[self]

    @property
    def caption(self) -> str:
        """Return a one-line vibe caption."""
        return {
            Mood.ON_FIRE: "On a tear — streak is hot and praises are stacking up.",
            Mood.CRUISING: "Steady flow — things are moving in the right direction.",
            Mood.MEH: "Neutral zone — some data, no strong signal either way.",
            Mood.STRUGGLING: "Friction detected — corrections outpacing praises.",
        }[self]


# ---------------------------------------------------------------------------
# Inputs dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VibeState:
    """Aggregated inputs for mood computation.

    All fields are optional; absent sources degrade gracefully.

    Attributes
    ----------
    streak:
        Current coach streak (consecutive green events).  ``None`` = coach data absent.
    praises:
        Total ``treat`` (praise) signals from whip.  ``None`` = whip data absent.
    corrections:
        Total ``crack`` (correction) signals from whip.  ``None`` = whip data absent.
    level:
        Quest level.  ``None`` = quest data absent.
    total_xp:
        Quest total XP.  ``None`` = quest data absent.
    xp_to_next:
        Quest XP to next level.  ``None`` = quest data absent.
    streak_days:
        Quest streak in days from verified runs.  ``None`` = quest data absent.
    """

    streak: int | None = None
    praises: int | None = None
    corrections: int | None = None
    level: int | None = None
    total_xp: int | None = None
    xp_to_next: int | None = None
    streak_days: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "streak": self.streak,
            "praises": self.praises,
            "corrections": self.corrections,
            "level": self.level,
            "total_xp": self.total_xp,
            "xp_to_next": self.xp_to_next,
            "streak_days": self.streak_days,
        }


# ---------------------------------------------------------------------------
# Core mood computation
# ---------------------------------------------------------------------------


def compute_mood(
    *,
    streak: int | None,
    praises: int | None,
    corrections: int | None,
    level: int | None,
) -> tuple[Mood, float]:
    """Compute the agent mood and a numeric score in [0.0, 1.0].

    Parameters
    ----------
    streak:
        Current coach streak (consecutive green events).  ``None`` = absent.
    praises:
        Total whip treat signals.  ``None`` = absent.
    corrections:
        Total whip crack signals.  ``None`` = absent.
    level:
        Quest level.  ``None`` = absent.

    Returns
    -------
    tuple[Mood, float]
        ``(mood, score)`` where score is a normalised [0, 1] confidence.

    Notes
    -----
    Thresholds are fixed (no wallclock, no random) so the same inputs always
    produce the same result.
    """
    # Compute praise_ratio when both signals are present.
    praise_ratio: float | None = None
    total_rewards = 0
    if praises is not None and corrections is not None:
        total_rewards = praises + corrections
        if total_rewards > 0:
            praise_ratio = praises / total_rewards

    # --- ON_FIRE: hot streak + positive praise ratio ---
    streak_ok = streak is not None and streak >= 5
    praise_ok = praise_ratio is not None and praise_ratio >= 0.6
    if streak_ok and (praise_ok or praises is None):
        score = min(1.0, 0.7 + (streak or 0) * 0.02)
        return Mood.ON_FIRE, round(score, 3)

    # --- STRUGGLING: corrections outpace praises, or streak reset with feedback ---
    if praises is not None and corrections is not None and corrections > praises:
        score = max(0.0, 0.3 - corrections * 0.02)
        return Mood.STRUGGLING, round(score, 3)
    if (
        streak is not None
        and streak == 0
        and total_rewards > 0
        and corrections is not None
        and corrections > 0
    ):
        return Mood.STRUGGLING, 0.25

    # --- CRUISING: moderate streak, decent ratio, or meaningful quest level ---
    if streak is not None and streak >= 2:
        score = min(0.69, 0.5 + streak * 0.03)
        return Mood.CRUISING, round(score, 3)
    if praise_ratio is not None and praise_ratio >= 0.5 and total_rewards >= 2:
        return Mood.CRUISING, round(0.55 + praise_ratio * 0.1, 3)
    if level is not None and level >= 5:
        return Mood.CRUISING, round(min(0.69, 0.5 + level * 0.01), 3)

    # --- MEH: default / not enough signal ---
    return Mood.MEH, 0.5


# ---------------------------------------------------------------------------
# HUD renderer
# ---------------------------------------------------------------------------


def render(state: VibeState) -> str:
    """Render the ambient HUD as a multi-line string.

    Parameters
    ----------
    state:
        Aggregated :class:`VibeState` — absent fields render as ``n/a``.

    Returns
    -------
    str
        A short, human-readable HUD block.
    """
    mood, score = compute_mood(
        streak=state.streak,
        praises=state.praises,
        corrections=state.corrections,
        level=state.level,
    )

    def _fmt(value: int | None, unit: str = "") -> str:
        if value is None:
            return "n/a"
        return f"{value}{unit}"

    lines = [
        f"  {mood.emoji}  {mood.name.replace('_', ' ').title()}  (score {score:.2f})",
        f"  {mood.caption}",
        "",
        f"  coach streak   : {_fmt(state.streak)}",
        f"  whip praises   : {_fmt(state.praises)}  corrections: {_fmt(state.corrections)}",
        f"  quest level    : {_fmt(state.level)}  XP: {_fmt(state.total_xp)}  "
        f"to next: {_fmt(state.xp_to_next)}",
        f"  quest streak   : {_fmt(state.streak_days, 'd')}",
    ]
    return "\n".join(lines)


def render_json(state: VibeState) -> dict[str, Any]:
    """Return a JSON-serialisable envelope of the full vibe state.

    Parameters
    ----------
    state:
        Aggregated :class:`VibeState`.

    Returns
    -------
    dict[str, Any]
        Envelope with ``kind``, ``mood``, ``score``, ``caption``, and the
        component inputs.
    """
    mood, score = compute_mood(
        streak=state.streak,
        praises=state.praises,
        corrections=state.corrections,
        level=state.level,
    )
    return {
        "kind": "vibe",
        "mood": mood.value,
        "emoji": mood.emoji,
        "score": score,
        "caption": mood.caption,
        "components": state.to_dict(),
    }
