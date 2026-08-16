"""Verified Cascade — speculative decoding's shape, lifted to task scale.

Speculative decoding wins because a cheap generator proposes and an exact
verifier accepts or rejects, so exactness is never traded for speed. This
module applies that shape to whole tasks: the cheap agent attempts first, the
*gate* (executed verification — never a judge) accepts or escalates to the
expensive agent. Routing decisions ride the only acceptance signal that can't
be gamed.

Honesty rules built in:
- an attempt counts only if it VERIFIED (gate-passed); "looks done" escalates;
- the comparison versus direct (expensive-only) is paired on the same tasks;
- savings can be negative and are reported that way — a cheap model that never
  passes makes the cascade strictly worse, and the number says so.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from oh_no_my_claudecode.experiment.stats import mean

#: Verified attempt: does this tier's agent pass the gate on this task?
TierRunner = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class CascadeOutcome:
    """One task's path through the cascade."""

    task_id: str
    resolved_by: str  # "cheap" | "expensive" | "unresolved"
    verified: bool
    cost: float


@dataclass(frozen=True, slots=True)
class CascadeReport:
    """Paired cascade-vs-direct economics, gate-verified on both arms."""

    outcomes: tuple[CascadeOutcome, ...]
    cascade_pass_rate: float
    direct_pass_rate: float
    escalation_rate: float
    spend_cascade: float
    spend_direct: float

    @property
    def savings_pct(self) -> float:
        if self.spend_direct <= 0:
            return 0.0
        return (self.spend_direct - self.spend_cascade) / self.spend_direct * 100.0

    def to_dict(self) -> dict[str, object]:
        return {
            "cascade_pass_rate": round(self.cascade_pass_rate, 4),
            "direct_pass_rate": round(self.direct_pass_rate, 4),
            "escalation_rate": round(self.escalation_rate, 4),
            "spend_cascade": round(self.spend_cascade, 4),
            "spend_direct": round(self.spend_direct, 4),
            "savings_pct": round(self.savings_pct, 2),
            "outcomes": [
                {"task": o.task_id, "resolved_by": o.resolved_by, "verified": o.verified}
                for o in self.outcomes
            ],
        }


def run_cascade(
    task_ids: Sequence[str],
    cheap: TierRunner,
    expensive: TierRunner,
    *,
    cheap_cost: float,
    expensive_cost: float,
) -> CascadeReport:
    """Cheap tier first; escalate on gate-fail; pair against direct-expensive.

    ``cheap``/``expensive`` return the task's *verified* outcome (gate-passed),
    so a cheap tier that produces plausible-but-wrong patches escalates instead
    of polluting the pass rate. The direct arm reuses the expensive tier's
    outcome per task, keeping the comparison paired. Deterministic given
    deterministic runners; costs are injected, measured upstream.
    """
    if not task_ids:
        raise ValueError("cascade needs at least one task")
    if cheap_cost < 0 or expensive_cost < 0:
        raise ValueError("costs must be non-negative")

    outcomes: list[CascadeOutcome] = []
    direct_passes: list[float] = []
    spend_cascade = 0.0
    escalations = 0
    for task_id in task_ids:
        expensive_verified = expensive(task_id)  # one paid reference run per task
        direct_passes.append(1.0 if expensive_verified else 0.0)
        if cheap(task_id):
            outcomes.append(CascadeOutcome(task_id, "cheap", True, cheap_cost))
            spend_cascade += cheap_cost
            continue
        escalations += 1
        cost = cheap_cost + expensive_cost
        spend_cascade += cost
        if expensive_verified:
            outcomes.append(CascadeOutcome(task_id, "expensive", True, cost))
        else:
            outcomes.append(CascadeOutcome(task_id, "unresolved", False, cost))

    return CascadeReport(
        outcomes=tuple(outcomes),
        cascade_pass_rate=mean([1.0 if o.verified else 0.0 for o in outcomes]),
        direct_pass_rate=mean(direct_passes),
        escalation_rate=escalations / len(task_ids),
        spend_cascade=spend_cascade,
        spend_direct=expensive_cost * len(task_ids),
    )


__all__ = ["CascadeOutcome", "CascadeReport", "TierRunner", "run_cascade"]
