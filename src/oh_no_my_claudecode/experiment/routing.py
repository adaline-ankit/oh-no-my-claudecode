"""Shadow evaluation scaffolding for trajectory-aware routing."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class RoutingArm(StrEnum):
    """Predeclared routing baselines and the candidate policy."""

    STATIC_PROMPT = "static-prompt"
    ALWAYS_CHEAP = "always-cheap"
    ALWAYS_STRONG = "always-strong"
    TRAJECTORY = "trajectory"


@dataclass(frozen=True, slots=True)
class RoutingTrial:
    """One verified task outcome for one routing arm."""

    task_id: str
    arm: RoutingArm
    verified: bool
    cost_usd: float | None
    cost_is_reliable: bool = True

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id must be non-empty")
        if not isinstance(self.arm, RoutingArm):
            raise ValueError("arm must be a RoutingArm")
        if not isinstance(self.verified, bool):
            raise ValueError("verified must be a bool")
        if not isinstance(self.cost_is_reliable, bool):
            raise ValueError("cost_is_reliable must be a bool")
        if self.cost_usd is not None and (
            isinstance(self.cost_usd, bool)
            or not isinstance(self.cost_usd, (int, float))
            or not math.isfinite(self.cost_usd)
            or self.cost_usd < 0
        ):
            raise ValueError("cost_usd must be a finite non-negative number or None")

    @property
    def cost_learning_eligible(self) -> bool:
        return self.cost_usd is not None and self.cost_is_reliable


@dataclass(frozen=True, slots=True)
class RoutingEvaluation:
    """Point-estimate report for a matched shadow-routing experiment.

    ``observed_gate_met`` is descriptive scaffolding, not a promotion claim.
    Enforcement and claim readiness remain false until a later publication-
    grade evaluation adds adequate sample size, uncertainty, and approval.
    """

    task_count: int
    cost_pair_count: int
    cost_coverage: float
    trajectory_quality: float
    always_strong_quality: float
    oracle_quality: float
    quality_delta: float
    non_inferiority_margin: float
    quality_non_inferior: bool
    cost_reduction_vs_always_strong: float | None
    minimum_cost_reduction: float
    cost_gate_met: bool
    router_quality_regret: float
    router_cost_regret_usd: float | None
    oracle_cost_coverage: float
    observed_gate_met: bool
    gate_reasons: tuple[str, ...]
    enforcement_enabled: bool = False
    claim_ready: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "task_count": self.task_count,
            "cost_pair_count": self.cost_pair_count,
            "cost_coverage": self.cost_coverage,
            "trajectory_quality": self.trajectory_quality,
            "always_strong_quality": self.always_strong_quality,
            "oracle_quality": self.oracle_quality,
            "quality_delta": self.quality_delta,
            "non_inferiority_margin": self.non_inferiority_margin,
            "quality_non_inferior": self.quality_non_inferior,
            "cost_reduction_vs_always_strong": self.cost_reduction_vs_always_strong,
            "minimum_cost_reduction": self.minimum_cost_reduction,
            "cost_gate_met": self.cost_gate_met,
            "router_quality_regret": self.router_quality_regret,
            "router_cost_regret_usd": self.router_cost_regret_usd,
            "oracle_cost_coverage": self.oracle_cost_coverage,
            "observed_gate_met": self.observed_gate_met,
            "gate_reasons": list(self.gate_reasons),
            "enforcement_enabled": self.enforcement_enabled,
            "claim_ready": self.claim_ready,
        }


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("cannot compute mean of empty values")
    return sum(values) / len(values)


def _reliable_cost(trial: RoutingTrial) -> float:
    if not trial.cost_learning_eligible or trial.cost_usd is None:
        raise ValueError("trial does not have reliable cost telemetry")
    return trial.cost_usd


def evaluate_routing(
    trials: Sequence[RoutingTrial],
    *,
    non_inferiority_margin: float = 0.02,
    minimum_cost_reduction: float = 0.20,
) -> RoutingEvaluation:
    """Compare trajectory routing with always-strong and hindsight oracle arms.

    Costs participate only when explicitly present and reliable. The cost gate
    requires complete paired coverage, so missing telemetry cannot look like a
    saving. The hindsight oracle is the cheapest verified arm per task among
    all observed arms.
    """
    if not 0.0 <= non_inferiority_margin <= 1.0:
        raise ValueError("non_inferiority_margin must be in [0, 1]")
    if not 0.0 <= minimum_cost_reduction <= 1.0:
        raise ValueError("minimum_cost_reduction must be in [0, 1]")

    indexed: dict[tuple[str, RoutingArm], RoutingTrial] = {}
    by_task: dict[str, list[RoutingTrial]] = {}
    for trial in trials:
        key = (trial.task_id, trial.arm)
        if key in indexed:
            raise ValueError(f"duplicate routing trial for {trial.task_id}/{trial.arm.value}")
        indexed[key] = trial
        by_task.setdefault(trial.task_id, []).append(trial)

    task_ids = sorted(
        task_id
        for task_id in by_task
        if (task_id, RoutingArm.TRAJECTORY) in indexed
        and (task_id, RoutingArm.ALWAYS_STRONG) in indexed
    )
    if not task_ids:
        raise ValueError("at least one matched trajectory/always-strong task is required")

    trajectory = [indexed[(task_id, RoutingArm.TRAJECTORY)] for task_id in task_ids]
    always_strong = [indexed[(task_id, RoutingArm.ALWAYS_STRONG)] for task_id in task_ids]
    trajectory_quality = _mean([float(trial.verified) for trial in trajectory])
    always_strong_quality = _mean([float(trial.verified) for trial in always_strong])
    quality_delta = trajectory_quality - always_strong_quality
    quality_non_inferior = quality_delta >= -non_inferiority_margin

    cost_pairs = [
        (router, strong)
        for router, strong in zip(trajectory, always_strong, strict=True)
        if router.cost_learning_eligible and strong.cost_learning_eligible
    ]
    cost_coverage = len(cost_pairs) / len(task_ids)
    cost_reduction: float | None = None
    if cost_coverage == 1.0:
        router_cost = _mean([_reliable_cost(router) for router, _ in cost_pairs])
        strong_cost = _mean([_reliable_cost(strong) for _, strong in cost_pairs])
        if strong_cost > 0:
            cost_reduction = (strong_cost - router_cost) / strong_cost
    cost_gate_met = (
        cost_coverage == 1.0
        and cost_reduction is not None
        and cost_reduction >= minimum_cost_reduction
    )

    oracle_quality_values: list[float] = []
    quality_regrets: list[float] = []
    cost_regrets: list[float] = []
    for task_id, router in zip(task_ids, trajectory, strict=True):
        task_trials = by_task[task_id]
        oracle_verified = any(trial.verified for trial in task_trials)
        oracle_quality_values.append(float(oracle_verified))
        quality_regrets.append(float(oracle_verified) - float(router.verified))

        verified_trials = [trial for trial in task_trials if trial.verified]
        if (
            router.verified
            and router.cost_learning_eligible
            and verified_trials
            and all(trial.cost_learning_eligible for trial in verified_trials)
        ):
            oracle_cost = min(_reliable_cost(trial) for trial in verified_trials)
            cost_regrets.append(max(0.0, _reliable_cost(router) - oracle_cost))

    oracle_quality = _mean(oracle_quality_values)
    quality_regret = _mean(quality_regrets)
    oracle_cost_coverage = len(cost_regrets) / len(task_ids)
    router_cost_regret = (
        _mean(cost_regrets) if oracle_cost_coverage == 1.0 else None
    )

    reasons: list[str] = []
    if not quality_non_inferior:
        reasons.append("quality non-inferiority margin not met")
    if cost_coverage < 1.0:
        reasons.append("complete reliable paired cost coverage required")
    elif cost_reduction is None:
        reasons.append("always-strong baseline cost must be positive")
    elif cost_reduction < minimum_cost_reduction:
        reasons.append("minimum cost reduction not met")
    if not reasons:
        reasons.append("point gate observed; shadow-only evidence is not claim-ready")

    return RoutingEvaluation(
        task_count=len(task_ids),
        cost_pair_count=len(cost_pairs),
        cost_coverage=cost_coverage,
        trajectory_quality=trajectory_quality,
        always_strong_quality=always_strong_quality,
        oracle_quality=oracle_quality,
        quality_delta=quality_delta,
        non_inferiority_margin=non_inferiority_margin,
        quality_non_inferior=quality_non_inferior,
        cost_reduction_vs_always_strong=cost_reduction,
        minimum_cost_reduction=minimum_cost_reduction,
        cost_gate_met=cost_gate_met,
        router_quality_regret=quality_regret,
        router_cost_regret_usd=router_cost_regret,
        oracle_cost_coverage=oracle_cost_coverage,
        observed_gate_met=quality_non_inferior and cost_gate_met,
        gate_reasons=tuple(reasons),
    )


__all__ = [
    "RoutingArm",
    "RoutingEvaluation",
    "RoutingTrial",
    "evaluate_routing",
]
