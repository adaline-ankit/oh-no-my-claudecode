"""Active evaluation — spend the benchmark budget where it decides the question.

The project's real constraint: a paid external run costs ~$40 and you can only
run so many tasks. Running them at random wastes budget on tasks where the two
variants already agree. To decide "does variant B beat champion A?", the
informative tasks are the ones where A and B are most likely to *disagree* —
those carry the signal; agreements carry none.

Given a prior pass-probability per task for each variant (from cheap pilots or
historical rates), expected disagreement on a task is

    P(A passes, B fails) + P(A fails, B passes)
      = p_A(1 - p_B) + p_B(1 - p_A)

which is maximized when the variants' outcomes are most anti-correlated. We
rank tasks by that and select the top-`budget`, so every dollar buys
discrimination. This is active learning applied to eval economics — the same
uncertainty-sampling idea, scoped to a paired A/B decision.

Deterministic, offline, no model calls: it decides *what to run*, not *how*.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


def expected_disagreement(p_a: float, p_b: float) -> float:
    """Probability the two variants disagree on a Bernoulli task outcome."""
    if not (0.0 <= p_a <= 1.0 and 0.0 <= p_b <= 1.0):
        raise ValueError("pass probabilities must be in [0, 1]")
    return p_a * (1.0 - p_b) + p_b * (1.0 - p_a)


@dataclass(frozen=True, slots=True)
class TaskInformativeness:
    task_id: str
    disagreement: float

    def to_dict(self) -> dict[str, object]:
        return {"task_id": self.task_id, "disagreement": round(self.disagreement, 4)}


def rank_tasks(
    prior_a: Mapping[str, float],
    prior_b: Mapping[str, float],
) -> list[TaskInformativeness]:
    """Rank the common tasks by expected A/B disagreement, descending.

    Only tasks with a prior for BOTH variants are rankable. Ties break by
    task_id so the ordering is deterministic.
    """
    common = sorted(set(prior_a) & set(prior_b))
    ranked = [
        TaskInformativeness(task_id, expected_disagreement(prior_a[task_id], prior_b[task_id]))
        for task_id in common
    ]
    ranked.sort(key=lambda t: (-t.disagreement, t.task_id))
    return ranked


def select_under_budget(
    prior_a: Mapping[str, float],
    prior_b: Mapping[str, float],
    *,
    budget: int,
) -> list[str]:
    """The task_ids to actually run: the top `budget` most-informative ones."""
    if budget < 0:
        raise ValueError("budget must be non-negative")
    return [t.task_id for t in rank_tasks(prior_a, prior_b)[:budget]]


def expected_information(
    prior_a: Mapping[str, float],
    prior_b: Mapping[str, float],
    selected: Sequence[str],
) -> float:
    """Total expected disagreement captured by a selection — the 'signal bought'.

    Comparing this for the active selection vs a same-size random/first-N
    selection is the payoff proof: same cost, more discrimination.
    """
    return sum(expected_disagreement(prior_a[t], prior_b[t]) for t in selected)


__all__ = [
    "TaskInformativeness",
    "expected_disagreement",
    "expected_information",
    "rank_tasks",
    "select_under_budget",
]
