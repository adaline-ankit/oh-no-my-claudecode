"""R4 — self-evolving harness, with proof instead of faith.

"Self-improving" is the field's hottest claim and its least verified: harness
changes ship on vibes, trained pruning is opaque, and nobody can show that
yesterday's "improvement" wasn't noise. This module makes harness evolution a
measured tournament:

    champion config  vs  challenger configs
    → paired runs on the repo's own benchmark (injected runner; kernel stats)
    → promote a challenger ONLY when the paired-delta CI excludes zero
    → every promotion is a sealed, attestable evolution record

The unit of evolution is a :class:`HarnessVariant` — any harness configuration
(compaction policy × memory set × retrieval interface weights × model choice).
The gate is the same statistical bar every other claim in this project meets;
losing or noisy challengers are recorded, not erased.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from oh_no_my_claudecode.experiment.stats import bootstrap_ci, mean, paired_deltas

#: Runner contract: does the harness under *variant_id* pass *task_id*?
VariantRunner = Callable[[str, str], bool]


@dataclass(frozen=True, slots=True)
class HarnessVariant:
    """One harness configuration in the tournament."""

    variant_id: str
    config: tuple[tuple[str, str], ...]  # sorted key/value pairs; hashable, canonical

    @classmethod
    def from_config(cls, variant_id: str, config: Mapping[str, str]) -> HarnessVariant:
        return cls(variant_id, tuple(sorted(config.items())))

    def to_dict(self) -> dict[str, object]:
        return {"variant_id": self.variant_id, "config": dict(self.config)}


@dataclass(frozen=True, slots=True)
class EvolutionResult:
    """One evolution step's verdict — promoted only on CI-backed lift."""

    champion_id: str
    winner_id: str
    promoted: bool
    pass_rates: tuple[tuple[str, float], ...]
    delta_mean: float
    delta_ci95: tuple[float, float]
    n_tasks: int
    record_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "champion_id": self.champion_id,
            "winner_id": self.winner_id,
            "promoted": self.promoted,
            "pass_rates": dict(self.pass_rates),
            "delta_mean": round(self.delta_mean, 4),
            "delta_ci95": [round(self.delta_ci95[0], 4), round(self.delta_ci95[1], 4)],
            "n_tasks": self.n_tasks,
            "record_hash": self.record_hash,
        }


def evolve_step(
    champion: HarnessVariant,
    challengers: Sequence[HarnessVariant],
    task_ids: Sequence[str],
    run: VariantRunner,
    *,
    seed: int = 0,
) -> EvolutionResult:
    """Run one champion-vs-challengers tournament on the benchmark.

    Paired per task; the best challenger by mean paired delta is promoted only
    when its bootstrap CI excludes zero. Otherwise the champion stands — a
    harness change that cannot prove itself does not ship. Deterministic given
    a deterministic runner. Cost = (1 + len(challengers)) × len(task_ids) runs;
    budgeting belongs to the caller.
    """
    if not task_ids:
        raise ValueError("evolution needs at least one benchmark task")
    scores: dict[str, dict[str, float]] = {}
    for variant in (champion, *challengers):
        scores[variant.variant_id] = {
            task: 1.0 if run(variant.variant_id, task) else 0.0 for task in task_ids
        }

    champion_scores = scores[champion.variant_id]
    best_id, best_deltas = champion.variant_id, [0.0]
    for challenger in challengers:
        deltas = list(paired_deltas(champion_scores, scores[challenger.variant_id]).values())
        if mean(deltas) > mean(best_deltas):
            best_id, best_deltas = challenger.variant_id, deltas

    low, high = (
        bootstrap_ci(best_deltas, seed=seed) if best_id != champion.variant_id else (0.0, 0.0)
    )
    promoted = best_id != champion.variant_id and low > 0.0

    payload = {
        "champion": champion.to_dict(),
        "winner": best_id,
        "promoted": promoted,
        "scores": dict(sorted(scores.items())),
        "delta_ci95": [low, high],
        "seed": seed,
    }
    record_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    return EvolutionResult(
        champion_id=champion.variant_id,
        winner_id=best_id if promoted else champion.variant_id,
        promoted=promoted,
        pass_rates=tuple(sorted((vid, mean(list(s.values()))) for vid, s in scores.items())),
        delta_mean=mean(best_deltas),
        delta_ci95=(low, high),
        n_tasks=len(task_ids),
        record_hash=record_hash,
    )


__all__ = ["EvolutionResult", "HarnessVariant", "VariantRunner", "evolve_step"]
