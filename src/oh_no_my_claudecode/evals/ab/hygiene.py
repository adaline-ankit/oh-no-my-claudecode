"""E5 — corpus hygiene: a benchmark that can't discriminate isn't a benchmark.

Two failure modes rot a task corpus silently:

- **saturated** — every arm passes every trial: the task measures nothing and
  inflates pass rates (we've watched a 24/24-both-arms suite claim signal).
- **dead** — every arm fails every trial: broken environment, impossible task,
  or a rotted gate; it deflates rates and wastes spend.

Both look like data until you split them out. This analyzer runs over trial
history (any iterable of ABTaskComparison, across repeats) and flags each task,
so a suite can drop or refresh the deadweight before the next paid run —
SWE-bench-Verified's lesson (task validity rots) applied continuously.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from oh_no_my_claudecode.evals.ab.models import ABTaskComparison


@dataclass(frozen=True, slots=True)
class TaskHealth:
    """One task's discrimination record across all observed trials."""

    task_id: str
    trials: int
    alone_passes: int
    onmc_passes: int

    @property
    def saturated(self) -> bool:
        return (
            self.trials > 0 and self.alone_passes == self.trials and self.onmc_passes == self.trials
        )

    @property
    def dead(self) -> bool:
        return self.trials > 0 and self.alone_passes == 0 and self.onmc_passes == 0

    @property
    def discriminating(self) -> bool:
        return self.trials > 0 and not self.saturated and not self.dead

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "trials": self.trials,
            "alone_passes": self.alone_passes,
            "onmc_passes": self.onmc_passes,
            "verdict": "saturated" if self.saturated else "dead" if self.dead else "discriminating",
        }


@dataclass(frozen=True, slots=True)
class CorpusHealth:
    """The suite-level verdict; drives drop/refresh decisions."""

    tasks: tuple[TaskHealth, ...]

    @property
    def saturated_ids(self) -> tuple[str, ...]:
        return tuple(t.task_id for t in self.tasks if t.saturated)

    @property
    def dead_ids(self) -> tuple[str, ...]:
        return tuple(t.task_id for t in self.tasks if t.dead)

    @property
    def discriminating_ratio(self) -> float:
        return sum(t.discriminating for t in self.tasks) / len(self.tasks) if self.tasks else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "saturated": list(self.saturated_ids),
            "dead": list(self.dead_ids),
            "discriminating_ratio": round(self.discriminating_ratio, 3),
        }


def audit_corpus(history: Iterable[ABTaskComparison]) -> CorpusHealth:
    """Flag saturated/dead tasks across all trials in *history*.

    Single-trial corpora are audited too (one all-pass trial already flags
    saturation risk) — more trials only sharpen the verdict. Deterministic:
    tasks ordered by id.
    """
    trials: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for comparison in history:
        trials[comparison.task.id].append((comparison.alone.passed, comparison.onmc.passed))
    tasks = tuple(
        TaskHealth(
            task_id=task_id,
            trials=len(outcomes),
            alone_passes=sum(alone for alone, _ in outcomes),
            onmc_passes=sum(onmc for _, onmc in outcomes),
        )
        for task_id, outcomes in sorted(trials.items())
    )
    return CorpusHealth(tasks)


__all__ = ["CorpusHealth", "TaskHealth", "audit_corpus"]
