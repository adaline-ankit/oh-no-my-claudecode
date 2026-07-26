"""Unified external-claim readiness for ONMC benchmark evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "ClaimReadinessDecision",
    "ClaimReadinessReport",
    "build_claim_readiness",
]


class ClaimReadinessDecision(StrEnum):
    """Top-level benchmark claim verdict."""

    READY = "ready"
    NOT_READY = "not-ready"


@dataclass(frozen=True, slots=True)
class ClaimReadinessReport:
    """Single verdict over power, coverage, calibration, and cost gates."""

    decision: ClaimReadinessDecision
    quality_claim_ready: bool
    cost_claim_ready: bool
    benchmark_plan_ready: bool
    portfolio_coverage_ready: bool
    calibration_ready: bool
    cost_calibration_ready: bool
    blocked_gates: tuple[str, ...]
    reasons: tuple[str, ...]
    next_actions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.value,
            "quality_claim_ready": self.quality_claim_ready,
            "cost_claim_ready": self.cost_claim_ready,
            "benchmark_plan_ready": self.benchmark_plan_ready,
            "portfolio_coverage_ready": self.portfolio_coverage_ready,
            "calibration_ready": self.calibration_ready,
            "cost_calibration_ready": self.cost_calibration_ready,
            "blocked_gates": list(self.blocked_gates),
            "reasons": list(self.reasons),
            "next_actions": list(self.next_actions),
        }


def build_claim_readiness(
    *,
    benchmark_plan: Mapping[str, object],
    calibration_gate: Mapping[str, object],
    coverage_gate: Mapping[str, object] | None = None,
) -> ClaimReadinessReport:
    """Combine separate benchmark gates into one externally-citable verdict."""
    benchmark_ready = _bool(benchmark_plan.get("claim_ready"), "benchmark_plan.claim_ready")
    coverage_ready = (
        False
        if coverage_gate is None
        else _bool(coverage_gate.get("claim_ready"), "coverage_gate.claim_ready")
    )
    calibration_ready = _bool(
        calibration_gate.get("quality_claim_ready"),
        "calibration_gate.quality_claim_ready",
    )
    cost_ready = _bool(
        calibration_gate.get("cost_claim_ready"),
        "calibration_gate.cost_claim_ready",
    )
    quality_claim_ready = benchmark_ready and coverage_ready and calibration_ready
    cost_claim_ready = quality_claim_ready and cost_ready

    blocked: list[str] = []
    reasons: list[str] = []
    next_actions: list[str] = []

    if not benchmark_ready:
        blocked.append("benchmark_plan")
        _extend_reasons(reasons, benchmark_plan.get("reasons"))
        _append_benchmark_next_action(next_actions, benchmark_plan)
    if coverage_gate is None:
        blocked.append("portfolio_coverage")
        reasons.append("manifest missing; portfolio coverage cannot be checked")
        next_actions.append("Provide a frozen portfolio manifest for external-claim gating.")
    elif not coverage_ready:
        blocked.append("portfolio_coverage")
        _extend_reasons(reasons, coverage_gate.get("reasons"))
        next_actions.append(
            "Rebalance the portfolio so required task kinds, repo spread, metadata, "
            "and dominance thresholds pass."
        )
    if not calibration_ready:
        blocked.append("calibration")
        _extend_reasons(reasons, calibration_gate.get("reasons"))
        next_actions.append(
            "Run a fresh, complete, discriminative benchmark report against the current manifest."
        )
    if calibration_ready and not cost_ready:
        blocked.append("cost_calibration")
        _extend_reasons(reasons, calibration_gate.get("reasons"))
        next_actions.append("Capture complete per-cell cost telemetry for every condition.")

    decision = (
        ClaimReadinessDecision.READY
        if quality_claim_ready and cost_claim_ready
        else ClaimReadinessDecision.NOT_READY
    )
    return ClaimReadinessReport(
        decision=decision,
        quality_claim_ready=quality_claim_ready,
        cost_claim_ready=cost_claim_ready,
        benchmark_plan_ready=benchmark_ready,
        portfolio_coverage_ready=coverage_ready,
        calibration_ready=calibration_ready,
        cost_calibration_ready=cost_ready,
        blocked_gates=tuple(dict.fromkeys(blocked)),
        reasons=tuple(dict.fromkeys(reasons)),
        next_actions=tuple(dict.fromkeys(next_actions)),
    )


def _append_benchmark_next_action(
    next_actions: list[str],
    benchmark_plan: Mapping[str, object],
) -> None:
    task_count = _optional_int(benchmark_plan.get("task_count"))
    min_required = _optional_int(benchmark_plan.get("min_tasks_required"))
    if task_count is not None and min_required is not None and task_count < min_required:
        next_actions.append(
            f"Add at least {min_required - task_count} benchmark task(s) to reach "
            f"the {min_required}-task planning target."
        )
    if benchmark_plan.get("budget_ready") is False:
        next_actions.append(
            "Set an explicit per-cell cost estimate and budget ceiling that covers "
            "the claim-sized benchmark run."
        )


def _extend_reasons(dest: list[str], value: object) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        if isinstance(item, str) and item.strip():
            dest.append(item)


def _bool(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{path} must be a bool")
    return value


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
