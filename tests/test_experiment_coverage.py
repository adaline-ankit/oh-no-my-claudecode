from __future__ import annotations

import json
from pathlib import Path

import pytest

from oh_no_my_claudecode.experiment.coverage import (
    gate_portfolio_coverage,
    plan_portfolio_expansion,
)
from oh_no_my_claudecode.experiment.power import plan_portfolio_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
V4_MANIFEST = REPO_ROOT / "datasets" / "experiment" / "portfolio_external_v4.json"


def _task(index: int, *, kind: str, repo: str) -> dict[str, object]:
    return {
        "task_id": f"{kind}-{repo}-{index}",
        "repo": {
            "name": repo,
            "url": f"https://github.com/example/{repo}.git",
            "pinned_sha": "abcdef0",
        },
        "prompt": "Fix the task.",
        "verifier_argv": ["python", "-m", "pytest"],
        "task_kind": kind,
        "expected_outcome": "Verifier passes.",
    }


def test_v4_manifest_fails_portfolio_coverage_gate() -> None:
    manifest = json.loads(V4_MANIFEST.read_text(encoding="utf-8"))

    gate = gate_portfolio_coverage(manifest)

    assert gate.task_count == 28
    assert gate.repo_count == 6
    assert gate.task_kind_count == 4
    assert gate.repo_coverage_ready is True
    assert gate.metadata_ready is True
    assert gate.task_kind_coverage_ready is False
    assert gate.balance_ready is False
    assert gate.claim_ready is False
    assert dict(gate.task_kind_counts)["refactor"] == 1
    assert dict(gate.task_kind_counts)["long-running"] == 1
    assert any("refactor" in reason for reason in gate.reasons)
    assert any("long-running" in reason for reason in gate.reasons)
    assert any("feature" in reason and "maximum" in reason for reason in gate.reasons)


def test_v4_manifest_expansion_plan_names_exact_gaps() -> None:
    manifest = json.loads(V4_MANIFEST.read_text(encoding="utf-8"))
    benchmark_plan = plan_portfolio_manifest(
        manifest,
        per_cell_cost_usd=0.75,
        budget_ceiling_usd=300.0,
    )
    coverage_gate = gate_portfolio_coverage(manifest)

    plan = plan_portfolio_expansion(
        benchmark_plan=benchmark_plan.to_dict(),
        coverage_gate=coverage_gate.to_dict(),
    )

    assert plan.current_tasks == 28
    assert plan.target_tasks == 50
    assert plan.minimum_total_additions == 22
    assert dict(plan.kind_deficits) == {"long-running": 2, "refactor": 2}
    assert dict(plan.suggested_minimum_additions_by_kind) == {
        "long-running": 2,
        "refactor": 2,
    }
    assert plan.unallocated_non_dominant_additions == 18
    assert plan.dominant_kind == "feature"
    assert plan.dominance_only_additions_required == 4
    assert plan.max_additional_dominant_kind_at_target == 11
    assert plan.repo_deficit == 0


def test_balanced_manifest_passes_portfolio_coverage_gate() -> None:
    tasks: list[dict[str, object]] = []
    repos = ["repo-a", "repo-b", "repo-c", "repo-d", "repo-e"]
    for kind in ("bugfix", "feature", "refactor", "long-running"):
        for index in range(5):
            tasks.append(_task(index, kind=kind, repo=repos[(index + len(tasks)) % len(repos)]))
    manifest = {"tasks": tasks}

    gate = gate_portfolio_coverage(manifest)

    assert gate.task_count == 20
    assert gate.repo_count == 5
    assert gate.task_kind_count == 4
    assert gate.task_kind_coverage_ready is True
    assert gate.repo_coverage_ready is True
    assert gate.balance_ready is True
    assert gate.metadata_ready is True
    assert gate.claim_ready is True
    assert gate.reasons == ()

    benchmark_plan = {
        "min_tasks_required": 20,
    }
    plan = plan_portfolio_expansion(
        benchmark_plan=benchmark_plan,
        coverage_gate=gate.to_dict(),
    )
    assert plan.minimum_total_additions == 0
    assert plan.ready_if_applied is True


def test_missing_task_metadata_blocks_coverage_gate() -> None:
    manifest = {
        "tasks": [
            {
                **_task(1, kind="bugfix", repo="repo-a"),
                "expected_outcome": "",
                "verifier_argv": [],
            }
        ]
    }

    gate = gate_portfolio_coverage(
        manifest,
        required_kind_minimums={"bugfix": 1},
        min_repos=1,
        min_task_kinds=1,
        max_kind_fraction=1,
    )

    assert gate.metadata_ready is False
    assert any("expected_outcome" in reason for reason in gate.reasons)
    assert any("verifier_argv" in reason for reason in gate.reasons)


def test_invalid_coverage_thresholds_are_rejected() -> None:
    manifest = {"tasks": [_task(1, kind="bugfix", repo="repo-a")]}

    with pytest.raises(ValueError, match="min_repos"):
        gate_portfolio_coverage(manifest, min_repos=0)

    with pytest.raises(ValueError, match="max_kind_fraction"):
        gate_portfolio_coverage(manifest, max_kind_fraction=0)
