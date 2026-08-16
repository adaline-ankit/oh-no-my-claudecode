"""E4 — compaction-policy scoring: rank policies by benchmark lift per token freed.

The correctness half of R1 lives in
:mod:`oh_no_my_claudecode.context_engine.compaction_gate` — it judges one
compaction. This module is the measurement half: given several candidate
compaction *policies*, it answers "which one buys the most benchmark lift per
kilotoken freed, and how sure are we?"

Fail-closed by construction: a policy whose compaction loses any declared
constraint on any context is marked rejected and never scored on tasks — a
summary that erases an invariant is worthless no matter how many tokens it
frees. Surviving policies are compared *paired* against the implicit
"full-context" identity baseline, with a seeded bootstrap CI on the delta.
Deterministic, offline, no LLM.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from oh_no_my_claudecode.context_engine.compaction_gate import Constraint, check_compaction
from oh_no_my_claudecode.experiment.stats import bootstrap_ci, derive_seed, mean, paired_deltas

__all__ = ["FULL_CONTEXT_POLICY", "CompactionPolicy", "PolicyScore", "score_policies"]

FULL_CONTEXT_POLICY = "full-context"


def _identity(text: str) -> str:
    return text


@dataclass(frozen=True, slots=True)
class CompactionPolicy:
    """A named compactor: ``compact(full_context) -> compacted view``."""

    name: str
    compact: Callable[[str], str]


@dataclass(frozen=True, slots=True)
class PolicyScore:
    """One policy's scorecard. Rejected policies carry zeros for task metrics."""

    name: str
    rejected: bool
    violations: int
    pass_rate: float
    delta_vs_full: float
    delta_ci95: tuple[float, float]
    mean_tokens_freed: float
    lift_per_kilotoken: float

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "rejected": self.rejected,
            "violations": self.violations,
            "pass_rate": self.pass_rate,
            "delta_vs_full": self.delta_vs_full,
            "delta_ci95": list(self.delta_ci95),
            "mean_tokens_freed": self.mean_tokens_freed,
            "lift_per_kilotoken": self.lift_per_kilotoken,
        }


def score_policies(
    policies: Sequence[CompactionPolicy],
    contexts: Sequence[str],
    constraints: Sequence[Constraint],
    task_runner: Callable[[str, str], bool],
    task_ids: Sequence[str],
    *,
    seed: int = 0,
) -> list[PolicyScore]:
    """Score and rank compaction policies against the full-context baseline.

    The identity baseline (``"full-context"``) is always scored implicitly; a
    caller-supplied policy with that name is ignored in its favor. Any policy
    that loses a constraint on any context is rejected (fail-closed) with its
    violation count recorded and ``task_runner`` never invoked for it.
    Ordering is deterministic: safe policies by ``lift_per_kilotoken``
    descending (name as tiebreak), rejected policies last.
    """
    if not contexts:
        raise ValueError("score_policies requires at least one context")
    if not task_ids:
        raise ValueError("score_policies requires at least one task id")

    baseline = CompactionPolicy(FULL_CONTEXT_POLICY, _identity)
    candidates = [baseline, *(p for p in policies if p.name != FULL_CONTEXT_POLICY)]
    baseline_results = {tid: float(task_runner(FULL_CONTEXT_POLICY, tid)) for tid in task_ids}

    scores: list[PolicyScore] = []
    for policy in candidates:
        violations = 0
        freed: list[float] = []
        for context in contexts:
            verdict = check_compaction(context, policy.compact(context), constraints)
            violations += len(verdict.lost)
            freed.append(float(verdict.tokens_freed))
        mean_freed = mean(freed)

        if violations:
            scores.append(
                PolicyScore(
                    name=policy.name,
                    rejected=True,
                    violations=violations,
                    pass_rate=0.0,
                    delta_vs_full=0.0,
                    delta_ci95=(0.0, 0.0),
                    mean_tokens_freed=mean_freed,
                    lift_per_kilotoken=0.0,
                )
            )
            continue

        results = (
            baseline_results
            if policy.name == FULL_CONTEXT_POLICY
            else {tid: float(task_runner(policy.name, tid)) for tid in task_ids}
        )
        deltas = list(paired_deltas(baseline_results, results).values())
        delta = mean(deltas)
        lift = delta / (mean_freed / 1000.0) if mean_freed > 0 else 0.0
        scores.append(
            PolicyScore(
                name=policy.name,
                rejected=False,
                violations=0,
                pass_rate=mean(list(results.values())),
                delta_vs_full=delta,
                delta_ci95=bootstrap_ci(deltas, seed=derive_seed(seed, policy.name)),
                mean_tokens_freed=mean_freed,
                lift_per_kilotoken=lift,
            )
        )

    scores.sort(key=lambda s: (s.rejected, -s.lift_per_kilotoken, s.name))
    return scores
