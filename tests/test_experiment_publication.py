from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.experiment.publication import (
    build_publication_bundle,
    build_publication_work_plan,
    index_raw_artifacts,
    render_publication_markdown,
    validate_benchmark_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
V4_MANIFEST = REPO_ROOT / "datasets" / "experiment" / "portfolio_external_v4.json"
SATURATED_REPORT = REPO_ROOT / "datasets" / "experiment" / "reports" / (
    "external_v3_stage1_2026-07-25.json"
)


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _ready_product_surface() -> dict[str, object]:
    return {
        "ready": True,
        "canonical_entrypoint": "run",
        "primary_limit": 14,
        "visible_primary": ["commands", "missioncontrol", "run", "setup"],
        "hidden_advanced_count": 12,
        "missing_primary": [],
        "hidden_primary": [],
        "unexpected_visible": [],
    }


def test_current_manifest_is_valid_but_not_publication_ready() -> None:
    validation = validate_benchmark_manifest(_load(V4_MANIFEST))

    assert validation.structurally_valid is True
    assert validation.publication_ready is False
    assert validation.task_count == 28
    assert validation.trials_per_cell == 3
    assert validation.condition_count == 2
    assert any("50" in reason for reason in validation.blockers)
    assert any("five benchmark arms" in reason for reason in validation.blockers)
    assert any("three agent/model configurations" in reason for reason in validation.blockers)
    assert any("three seeds" in reason for reason in validation.blockers)


def test_manifest_validator_rejects_invalid_core_contract() -> None:
    validation = validate_benchmark_manifest(
        {
            "schema_version": "1",
            "experiment": {},
            "tasks": [],
            "audit_status": "valid",
            "leakage_notes": "audited",
        }
    )

    assert validation.structurally_valid is False
    assert validation.publication_ready is False
    assert validation.errors


def test_publication_report_exposes_paired_ci_cost_and_leakage_gaps() -> None:
    report = _load(SATURATED_REPORT)
    manifest = _load(V4_MANIFEST)

    bundle = build_publication_bundle(
        report,
        manifest,
        proposed_claim="ONMC is SOTA, better, and cheaper than plain coding agents.",
        product_surface=_ready_product_surface(),
    )
    markdown = render_publication_markdown(bundle)

    assert bundle["publication_ready"] is False
    assert bundle["claim_language_gate"]["decision"] == "refuse"
    assert bundle["paired"]["mean_delta"] == 0.0
    assert bundle["paired"]["delta_ci95"] == [0.0, 0.0]
    assert bundle["cost_coverage"]["complete"] is False
    assert bundle["leakage_audit"]["complete"] is False
    assert bundle["product_surface"]["ready"] is True
    assert "NOT PUBLICATION-READY" in markdown
    assert "Paired Delta" in markdown
    assert "95% CI" in markdown
    assert "Cost Coverage" in markdown
    assert "INCOMPLETE" in markdown
    assert "Leakage Audit" in markdown
    assert "Product Surface" in markdown
    assert "SOTA" not in bundle["claim_language_gate"]["suggested_safe_claim"]


def test_publication_report_fails_closed_without_product_surface_audit() -> None:
    report = _load(SATURATED_REPORT)
    manifest = _load(V4_MANIFEST)

    bundle = build_publication_bundle(report, manifest)

    assert bundle["publication_ready"] is False
    assert bundle["product_surface"]["ready"] is False
    assert bundle["product_surface"]["evaluated"] is False
    assert bundle["product_surface"]["blockers"] == [
        "live product surface audit was not provided"
    ]


def test_publication_work_plan_turns_blockers_into_next_matrix() -> None:
    report = _load(SATURATED_REPORT)
    manifest = _load(V4_MANIFEST)
    bundle = build_publication_bundle(
        report,
        manifest,
        product_surface=_ready_product_surface(),
    )

    plan = build_publication_work_plan(bundle)

    assert plan["schema_version"] == "onmc-publication-work-plan/v1"
    assert plan["publication_ready"] is False
    assert plan["target_matrix"]["required_arms"] == [
        "bare-agent",
        "context-only",
        "onmc-single-agent",
        "selective-swarm",
        "trajectory-routed",
    ]
    assert plan["deficits"]["tasks_to_add"] == 22
    assert plan["deficits"]["discriminative_tasks_to_find"] == 10
    assert plan["deficits"]["missing_benchmark_arms"] == [
        "context-only",
        "onmc-single-agent",
        "selective-swarm",
        "trajectory-routed",
    ]
    assert plan["deficits"]["missing_cost_cells"] == 11
    assert plan["deficits"]["product_surface_ready"] is True
    assert plan["spend_gate"]["paid_full_matrix_allowed"] is False


def test_raw_artifact_index_verifies_declared_files(tmp_path: Path) -> None:
    trajectory = tmp_path / "trajectory.json"
    verifier = tmp_path / "verifier.json"
    trajectory.write_text('{"events":[]}\n', encoding="utf-8")
    verifier.write_text('{"passed":true}\n', encoding="utf-8")
    report = {
        "records": [
            {
                "task_id": "task-a",
                "condition": "bare-agent",
                "trial": 0,
                "infra_error": None,
                "trajectory_path": "trajectory.json",
                "verifier_path": "verifier.json",
            }
        ]
    }

    index = index_raw_artifacts(report, artifact_root=tmp_path)

    assert index["complete"] is True
    assert index["usable_cells"] == 1
    assert index["indexed_cells"] == 1
    assert index["missing"] == []
    assert {item["kind"] for item in index["artifacts"]} == {"trajectory", "verifier"}
    assert all(len(str(item["sha256"])) == 64 for item in index["artifacts"])


def test_raw_artifact_index_reports_missing_cell_artifacts(tmp_path: Path) -> None:
    report = {
        "records": [
            {
                "task_id": "task-a",
                "condition": "bare-agent",
                "trial": 0,
                "infra_error": None,
            }
        ]
    }

    index = index_raw_artifacts(report, artifact_root=tmp_path)

    assert index["complete"] is False
    assert index["indexed_cells"] == 0
    assert index["missing"] == [
        "task-a/bare-agent/trial-0: trajectory_path",
        "task-a/bare-agent/trial-0: verifier_path",
    ]
