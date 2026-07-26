"""Offline sample-size and spend planning for ONMC benchmark runs.

The calibration gate says whether a completed report can support a claim. This
module answers the earlier question: is a proposed run large enough, and is the
expected spend explicit, before we launch agent cells?

The power estimate is intentionally conservative and dependency-free. It is a
planning heuristic for paired task deltas, not a substitute for the final
bootstrap/confidence analysis over measured results.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import ceil

from oh_no_my_claudecode.experiment.contracts import Condition

__all__ = [
    "BenchmarkPowerPlan",
    "plan_external_report",
    "plan_portfolio_manifest",
]

_Z_ALPHA_TWO_SIDED_95 = 1.96
_Z_POWER_80 = 0.84


@dataclass(frozen=True, slots=True)
class BenchmarkPowerPlan:
    """Pre-run readiness estimate for a benchmark manifest or report."""

    task_count: int
    condition_count: int
    trials_per_cell: int
    total_cells: int
    min_effect: float
    assumed_task_delta_sd: float
    min_tasks_floor: int
    min_tasks_required: int
    min_total_cells_required: int
    per_cell_cost_usd: float | None
    budget_ceiling_usd: float | None
    estimated_cost_usd: float | None
    estimated_required_cost_usd: float | None
    sample_size_ready: bool
    budget_ready: bool
    claim_ready: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "task_count": self.task_count,
            "condition_count": self.condition_count,
            "trials_per_cell": self.trials_per_cell,
            "total_cells": self.total_cells,
            "min_effect": self.min_effect,
            "assumed_task_delta_sd": self.assumed_task_delta_sd,
            "min_tasks_floor": self.min_tasks_floor,
            "min_tasks_required": self.min_tasks_required,
            "min_total_cells_required": self.min_total_cells_required,
            "per_cell_cost_usd": self.per_cell_cost_usd,
            "budget_ceiling_usd": self.budget_ceiling_usd,
            "estimated_cost_usd": self.estimated_cost_usd,
            "estimated_required_cost_usd": self.estimated_required_cost_usd,
            "sample_size_ready": self.sample_size_ready,
            "budget_ready": self.budget_ready,
            "claim_ready": self.claim_ready,
            "reasons": list(self.reasons),
        }


def plan_portfolio_manifest(
    manifest: Mapping[str, object],
    *,
    per_cell_cost_usd: float | None = None,
    budget_ceiling_usd: float | None = None,
    min_effect: float = 0.15,
    assumed_task_delta_sd: float = 0.35,
    min_tasks_floor: int = 50,
) -> BenchmarkPowerPlan:
    """Return a pre-run plan for a frozen external portfolio manifest."""
    experiment = _mapping(manifest.get("experiment"), "manifest.experiment")
    tasks = _list(manifest.get("tasks"), "manifest.tasks")
    conditions = tuple(
        _condition_value(item)
        for item in _list(experiment.get("conditions"), "manifest.experiment.conditions")
    )
    trials = _positive_int(experiment.get("trials"), "manifest.experiment.trials")
    return _build_plan(
        task_count=len(tasks),
        condition_count=len(conditions),
        trials_per_cell=trials,
        per_cell_cost_usd=per_cell_cost_usd,
        budget_ceiling_usd=budget_ceiling_usd,
        min_effect=min_effect,
        assumed_task_delta_sd=assumed_task_delta_sd,
        min_tasks_floor=min_tasks_floor,
    )


def plan_external_report(
    report: Mapping[str, object],
    *,
    per_cell_cost_usd: float | None = None,
    budget_ceiling_usd: float | None = None,
    min_effect: float = 0.15,
    assumed_task_delta_sd: float = 0.35,
    min_tasks_floor: int = 50,
) -> BenchmarkPowerPlan:
    """Return the planning envelope implied by a completed report."""
    records = _list(report.get("records"), "report.records")
    task_ids = {
        _string(_mapping(item, "report.records[]").get("task_id"), "report.records[].task_id")
        for item in records
    }
    conditions = tuple(
        _condition_value(item) for item in _list(report.get("conditions"), "report.conditions")
    )
    trials = _positive_int(report.get("trials_per_cell"), "report.trials_per_cell")
    if per_cell_cost_usd is None:
        per_cell_cost_usd = _mean_report_cell_cost(records)
    if budget_ceiling_usd is None:
        budget_ceiling_usd = _optional_non_negative_float(
            report.get("budget_ceiling_usd"),
            "report.budget_ceiling_usd",
        )
    return _build_plan(
        task_count=len(task_ids),
        condition_count=len(conditions),
        trials_per_cell=trials,
        per_cell_cost_usd=per_cell_cost_usd,
        budget_ceiling_usd=budget_ceiling_usd,
        min_effect=min_effect,
        assumed_task_delta_sd=assumed_task_delta_sd,
        min_tasks_floor=min_tasks_floor,
    )


def _build_plan(
    *,
    task_count: int,
    condition_count: int,
    trials_per_cell: int,
    per_cell_cost_usd: float | None,
    budget_ceiling_usd: float | None,
    min_effect: float,
    assumed_task_delta_sd: float,
    min_tasks_floor: int,
) -> BenchmarkPowerPlan:
    if task_count < 1:
        raise ValueError("task_count must be positive")
    if condition_count < 2:
        raise ValueError("at least two conditions are required")
    if trials_per_cell < 1:
        raise ValueError("trials_per_cell must be positive")
    if min_effect <= 0:
        raise ValueError("min_effect must be positive")
    if assumed_task_delta_sd <= 0:
        raise ValueError("assumed_task_delta_sd must be positive")
    if min_tasks_floor < 1:
        raise ValueError("min_tasks_floor must be positive")
    per_cell_cost = _validate_optional_cost(per_cell_cost_usd, "per_cell_cost_usd")
    budget_ceiling = _validate_optional_cost(budget_ceiling_usd, "budget_ceiling_usd")

    required_by_effect = ceil(
        ((_Z_ALPHA_TWO_SIDED_95 + _Z_POWER_80) * assumed_task_delta_sd / min_effect) ** 2
    )
    min_tasks_required = max(min_tasks_floor, required_by_effect)
    total_cells = task_count * condition_count * trials_per_cell
    min_total_cells_required = min_tasks_required * condition_count * trials_per_cell
    estimated_cost = (
        round(total_cells * per_cell_cost, 4) if per_cell_cost is not None else None
    )
    estimated_required_cost = (
        round(min_total_cells_required * per_cell_cost, 4)
        if per_cell_cost is not None
        else None
    )

    reasons: list[str] = []
    sample_size_ready = task_count >= min_tasks_required
    if not sample_size_ready:
        reasons.append(
            f"only {task_count} task(s); requires {min_tasks_required} for a "
            f"{min_effect:.3f} paired pass-rate delta planning target"
        )
    if per_cell_cost is None:
        reasons.append("per-cell cost estimate missing; budget risk is unknown")
    if budget_ceiling is None:
        reasons.append("budget ceiling missing; paid run cannot be pre-approved")
    budget_ready = per_cell_cost is not None and budget_ceiling is not None
    if (
        estimated_cost is not None
        and budget_ceiling is not None
        and estimated_cost > budget_ceiling
    ):
        budget_ready = False
        reasons.append(
            f"estimated run cost ${estimated_cost:.2f} exceeds budget ceiling "
            f"${budget_ceiling:.2f}"
        )
    if (
        estimated_required_cost is not None
        and budget_ceiling is not None
        and estimated_required_cost > budget_ceiling
    ):
        budget_ready = False
        reasons.append(
            f"claim-sized run estimate ${estimated_required_cost:.2f} exceeds "
            f"budget ceiling ${budget_ceiling:.2f}"
        )

    return BenchmarkPowerPlan(
        task_count=task_count,
        condition_count=condition_count,
        trials_per_cell=trials_per_cell,
        total_cells=total_cells,
        min_effect=min_effect,
        assumed_task_delta_sd=assumed_task_delta_sd,
        min_tasks_floor=min_tasks_floor,
        min_tasks_required=min_tasks_required,
        min_total_cells_required=min_total_cells_required,
        per_cell_cost_usd=per_cell_cost,
        budget_ceiling_usd=budget_ceiling,
        estimated_cost_usd=estimated_cost,
        estimated_required_cost_usd=estimated_required_cost,
        sample_size_ready=sample_size_ready,
        budget_ready=budget_ready,
        claim_ready=sample_size_ready and budget_ready,
        reasons=tuple(reasons),
    )


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _positive_int(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _condition_value(value: str | Condition | object) -> str:
    if isinstance(value, Condition):
        return value.value
    return _string(value, "condition")


def _validate_optional_cost(value: float | None, path: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or value < 0:
        raise ValueError(f"{path} must be a non-negative number")
    return float(value)


def _optional_non_negative_float(value: object, path: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{path} must be null or a non-negative number")
    return float(value)


def _mean_report_cell_cost(records: Sequence[object]) -> float | None:
    costs: list[float] = []
    for item in records:
        record = _mapping(item, "report.records[]")
        cost = record.get("cost_usd")
        if cost is None:
            continue
        costs.append(_optional_non_negative_float(cost, "report.records[].cost_usd") or 0.0)
    if not costs:
        return None
    return round(sum(costs) / len(costs), 4)
