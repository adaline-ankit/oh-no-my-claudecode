from __future__ import annotations

import json
from pathlib import Path

import pytest

from oh_no_my_claudecode.experiment.contracts import Condition
from oh_no_my_claudecode.experiment.power import (
    plan_external_report,
    plan_portfolio_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SATURATED_REPORT = REPO_ROOT / "datasets" / "experiment" / "reports" / (
    "external_v3_stage1_2026-07-25.json"
)
V4_MANIFEST = REPO_ROOT / "datasets" / "experiment" / "portfolio_external_v4.json"


def test_v4_manifest_is_underpowered_for_claim_sized_eval() -> None:
    manifest = json.loads(V4_MANIFEST.read_text(encoding="utf-8"))

    plan = plan_portfolio_manifest(
        manifest,
        per_cell_cost_usd=0.75,
        budget_ceiling_usd=300.0,
    )

    assert plan.task_count == 28
    assert plan.condition_count == 2
    assert plan.trials_per_cell == 3
    assert plan.total_cells == 168
    assert plan.min_tasks_required == 50
    assert plan.min_total_cells_required == 300
    assert plan.estimated_cost_usd == 126.0
    assert plan.sample_size_ready is False
    assert plan.budget_ready is True
    assert plan.claim_ready is False
    assert any("only 28 task(s)" in reason for reason in plan.reasons)


def test_budget_gate_blocks_run_that_exceeds_ceiling() -> None:
    manifest = json.loads(V4_MANIFEST.read_text(encoding="utf-8"))

    plan = plan_portfolio_manifest(
        manifest,
        per_cell_cost_usd=0.75,
        budget_ceiling_usd=100.0,
    )

    assert plan.estimated_cost_usd == 126.0
    assert plan.budget_ready is False
    assert any("exceeds budget ceiling" in reason for reason in plan.reasons)


def test_claim_sized_manifest_passes_power_and_budget_plan() -> None:
    manifest = {
        "experiment": {
            "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
            "trials": 3,
        },
        "tasks": [{"task_id": f"task-{index}"} for index in range(50)],
    }

    plan = plan_portfolio_manifest(
        manifest,
        per_cell_cost_usd=0.5,
        budget_ceiling_usd=150.0,
    )

    assert plan.task_count == 50
    assert plan.total_cells == 300
    assert plan.estimated_cost_usd == 150.0
    assert plan.sample_size_ready is True
    assert plan.budget_ready is True
    assert plan.claim_ready is True
    assert plan.reasons == ()


def test_report_plan_derives_measured_cell_cost_and_budget() -> None:
    report = json.loads(SATURATED_REPORT.read_text(encoding="utf-8"))

    plan = plan_external_report(report)

    assert plan.task_count == 24
    assert plan.condition_count == 2
    assert plan.trials_per_cell == 1
    assert plan.total_cells == 48
    assert plan.per_cell_cost_usd is not None
    assert plan.budget_ceiling_usd == 35.0
    assert plan.sample_size_ready is False
    assert plan.claim_ready is False


def test_invalid_power_inputs_are_rejected() -> None:
    manifest = {
        "experiment": {
            "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
            "trials": 1,
        },
        "tasks": [{"task_id": "task-a"}],
    }

    with pytest.raises(ValueError, match="min_effect"):
        plan_portfolio_manifest(manifest, min_effect=0)

    with pytest.raises(ValueError, match="non-negative"):
        plan_portfolio_manifest(manifest, per_cell_cost_usd=-1)
