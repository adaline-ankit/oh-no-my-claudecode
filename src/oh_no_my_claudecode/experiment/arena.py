"""Agent Arena — a Bradley-Terry ladder for YOUR repo, not someone else's.

LMSYS Arena's crack: when absolute scores lie, paired battles + a
Bradley-Terry model still produce rigorous rankings. Our substrate already
generates the battles — every paired run on repo-bench (A/B harness, R4
tournaments, cascade arms) is a per-task win/loss between two variants.
This module turns those into a private leaderboard: which agent config
actually wins on this codebase, with the win probabilities the ratings imply.

Fitting uses the classic MM (Zermelo) iteration with 0.5 pseudo-battle
smoothing so undefeated or winless entrants get finite, honest ratings.
Deterministic, offline, stdlib only.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

#: battles[(a, b)] = number of times a beat b (order matters; ties → 0.5 each).
Battles = Mapping[tuple[str, str], float]

_ITERATIONS = 200
_SMOOTHING = 0.5  # pseudo-wins each way per pair; keeps ratings finite


def battles_from_scores(scores: Mapping[str, Mapping[str, float]]) -> dict[tuple[str, str], float]:
    """Derive pairwise battles from per-task scores (1.0 pass / 0.0 fail).

    For every variant pair and every shared task: the higher score wins;
    equal scores are a tie, credited half to each side. This is how existing
    paired-run data (R4 tournaments, A/B arms) enters the arena.
    """
    battles: dict[tuple[str, str], float] = {}
    names = sorted(scores)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            shared = set(scores[a]) & set(scores[b])
            for task in shared:
                if scores[a][task] > scores[b][task]:
                    battles[a, b] = battles.get((a, b), 0.0) + 1.0
                elif scores[b][task] > scores[a][task]:
                    battles[b, a] = battles.get((b, a), 0.0) + 1.0
                else:
                    battles[a, b] = battles.get((a, b), 0.0) + 0.5
                    battles[b, a] = battles.get((b, a), 0.0) + 0.5
    return battles


@dataclass(frozen=True, slots=True)
class ArenaRating:
    """One variant's place on the ladder."""

    variant_id: str
    elo: float
    strength: float  # raw Bradley-Terry strength (relative)
    battles: float

    def to_dict(self) -> dict[str, object]:
        return {
            "variant_id": self.variant_id,
            "elo": round(self.elo, 1),
            "strength": round(self.strength, 6),
            "battles": self.battles,
        }


def fit_ladder(battles: Battles) -> list[ArenaRating]:
    """Fit Bradley-Terry strengths; return the ladder best-first.

    Elo scale: 1000 + 400·log10(strength / geometric-mean-strength), so the
    ladder centers at 1000 and a +400 gap means ~10:1 implied win odds —
    the familiar reading, derived from paired evidence.
    """
    names = sorted({n for pair in battles for n in pair})
    if len(names) < 2:
        raise ValueError("an arena needs at least two variants")

    smoothed: dict[tuple[str, str], float] = {}
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            smoothed[a, b] = battles.get((a, b), 0.0) + _SMOOTHING
            smoothed[b, a] = battles.get((b, a), 0.0) + _SMOOTHING

    strength = dict.fromkeys(names, 1.0)
    for _ in range(_ITERATIONS):
        updated: dict[str, float] = {}
        for a in names:
            wins = sum(smoothed[a, b] for b in names if b != a)
            denominator = sum(
                (smoothed[a, b] + smoothed[b, a]) / (strength[a] + strength[b])
                for b in names
                if b != a
            )
            updated[a] = wins / denominator
        total = sum(updated.values())
        strength = {n: s * len(names) / total for n, s in updated.items()}

    log_geomean = sum(math.log10(s) for s in strength.values()) / len(names)
    fought = {n: sum(v for pair, v in battles.items() if n in pair) for n in names}
    ladder = [
        ArenaRating(
            variant_id=name,
            elo=1000.0 + 400.0 * (math.log10(strength[name]) - log_geomean),
            strength=strength[name],
            battles=fought[name],
        )
        for name in names
    ]
    ladder.sort(key=lambda r: (-r.elo, r.variant_id))
    return ladder


__all__ = ["ArenaRating", "Battles", "battles_from_scores", "fit_ladder"]
