"""Per-memory measured lift — the P&L that makes memory *earned*.

Every memory framework stores claims; none can say whether a given memory
helps, does nothing, or poisons. This module answers that with measurement:
replay a task set (e.g. the repo-bench private benchmark) with the full memory
set versus leave-one-out sets, and score each memory by its paired marginal
lift, with a bootstrap CI from the experiment kernel.

Verdicts drive the lifecycle: ``EARNING`` memories stay promoted, ``HARMFUL``
ones are retired by evidence (the memory-poisoning literature reports a 100%
relapse rate for conversational correction — measurement doesn't relapse),
and ``UNPROVEN`` ones face expiry like any unfunded claim.

Pure over an injected runner: no I/O, no LLM calls here — callers plug in the
fixture adapter (free) or a live suite runner (paid, budgeted elsewhere).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from oh_no_my_claudecode.experiment.stats import bootstrap_ci, mean

#: Runner contract: does *task_id* pass when the agent has *memory_ids* available?
TaskRunner = Callable[[str, frozenset[str]], bool]


class LiftVerdict(StrEnum):
    """What the measurement says about one memory."""

    EARNING = "earning"  # CI above zero: keeps its promotion
    HARMFUL = "harmful"  # CI below zero: retire — this is measured poison
    UNPROVEN = "unproven"  # CI straddles zero: faces expiry like any unfunded claim


@dataclass(frozen=True, slots=True)
class MemoryLift:
    """The measured P&L entry for one memory."""

    memory_id: str
    mean_lift: float
    ci95: tuple[float, float]
    n_tasks: int
    verdict: LiftVerdict

    def to_dict(self) -> dict[str, object]:
        return {
            "memory_id": self.memory_id,
            "mean_lift": round(self.mean_lift, 4),
            "ci95": [round(self.ci95[0], 4), round(self.ci95[1], 4)],
            "n_tasks": self.n_tasks,
            "verdict": self.verdict.value,
        }


def _verdict(low: float, high: float) -> LiftVerdict:
    if low > 0.0:
        return LiftVerdict.EARNING
    if high < 0.0:
        return LiftVerdict.HARMFUL
    return LiftVerdict.UNPROVEN


def attribute_memories(
    memory_ids: Sequence[str],
    task_ids: Sequence[str],
    run_task: TaskRunner,
    *,
    seed: int = 0,
) -> list[MemoryLift]:
    """Leave-one-out attribution: lift(m) = pass(all) − pass(all − m), per task.

    Deterministic given a deterministic runner. Cost is
    ``(len(memory_ids) + 1) × len(task_ids)`` runner calls — callers with paid
    runners batch or subsample; that budgeting lives with the caller, never here.
    """
    if not memory_ids or not task_ids:
        return []
    full = frozenset(memory_ids)
    baseline = {task: 1.0 if run_task(task, full) else 0.0 for task in task_ids}

    ledger: list[MemoryLift] = []
    for memory in memory_ids:
        without = full - {memory}
        deltas = [baseline[task] - (1.0 if run_task(task, without) else 0.0) for task in task_ids]
        low, high = bootstrap_ci(deltas, seed=seed)
        ledger.append(
            MemoryLift(
                memory_id=memory,
                mean_lift=mean(deltas),
                ci95=(low, high),
                n_tasks=len(task_ids),
                verdict=_verdict(low, high),
            )
        )
    ledger.sort(key=lambda entry: entry.mean_lift, reverse=True)
    return ledger


def retirement_candidates(ledger: Sequence[MemoryLift]) -> tuple[str, ...]:
    """Memories the evidence says to retire now (measured poison)."""
    return tuple(entry.memory_id for entry in ledger if entry.verdict is LiftVerdict.HARMFUL)


__all__ = [
    "LiftVerdict",
    "MemoryLift",
    "TaskRunner",
    "attribute_memories",
    "retirement_candidates",
]
