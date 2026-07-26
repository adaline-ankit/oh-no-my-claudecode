from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.experiment.coverage import gate_portfolio_coverage
from oh_no_my_claudecode.experiment.expansion import build_portfolio_expansion_draft
from oh_no_my_claudecode.experiment.power import plan_portfolio_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
V4_MANIFEST = REPO_ROOT / "datasets" / "experiment" / "portfolio_external_v4.json"


def test_v4_expansion_draft_creates_exact_planned_slots() -> None:
    manifest = json.loads(V4_MANIFEST.read_text(encoding="utf-8"))
    benchmark_plan = plan_portfolio_manifest(
        manifest,
        per_cell_cost_usd=0.75,
        budget_ceiling_usd=300.0,
    ).to_dict()
    coverage_gate = gate_portfolio_coverage(manifest).to_dict()

    draft = build_portfolio_expansion_draft(
        manifest=manifest,
        benchmark_plan=benchmark_plan,
        coverage_gate=coverage_gate,
    )

    assert draft.base_task_count == 28
    assert draft.target_task_count == 50
    assert draft.slot_count == 22
    assert dict(draft.slots_by_kind) == {
        "bugfix": 4,
        "long-running": 9,
        "refactor": 9,
    }
    assert "feature" not in dict(draft.slots_by_kind)
    required_slots = [slot for slot in draft.slots if slot.required_by == "kind-minimum"]
    assert len(required_slots) == 4
    assert {slot.task_kind for slot in required_slots} == {"long-running", "refactor"}
    assert all(slot.slot_id.startswith("planned-v5-") for slot in draft.slots)
    assert any("not benchmark tasks" in note for note in draft.notes)


def test_expansion_draft_is_empty_for_already_sized_manifest() -> None:
    manifest = {
        "tasks": [
            {
                "task_id": f"task-{index}",
                "repo": {
                    "name": f"repo-{index % 5}",
                    "url": "https://github.com/example/repo.git",
                    "pinned_sha": "abcdef0",
                },
                "prompt": "Fix.",
                "verifier_argv": ["python", "-m", "pytest"],
                "task_kind": ("bugfix", "feature", "refactor", "long-running")[index % 4],
                "expected_outcome": "Verifier passes.",
            }
            for index in range(20)
        ]
    }
    coverage_gate = gate_portfolio_coverage(manifest).to_dict()
    benchmark_plan = {"min_tasks_required": 20}

    draft = build_portfolio_expansion_draft(
        manifest=manifest,
        benchmark_plan=benchmark_plan,
        coverage_gate=coverage_gate,
    )

    assert draft.slot_count == 0
    assert draft.slots == ()
