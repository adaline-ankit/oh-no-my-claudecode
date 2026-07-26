from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
V4_MANIFEST = REPO_ROOT / "datasets" / "experiment" / "portfolio_external_v4.json"
SATURATED_REPORT = REPO_ROOT / "datasets" / "experiment" / "reports" / (
    "external_v3_stage1_2026-07-25.json"
)


def _load_script(name: str) -> ModuleType:
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_product_smoke(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "ready": True,
                "canonical_entrypoint": "run",
                "mode": "in-process-typer-cli",
                "package_version": "0.111.0",
                "init_verified": True,
                "commands_surface_ready": True,
                "plan_only_verified": True,
                "run_status": "planned",
                "run_stop_reason": "plan-only",
                "model_calls": 0,
                "network_used": False,
                "agent_execution_attempted": False,
                "receipt_written": False,
                "blockers": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_runtime_delegation(path: Path) -> None:
    view = {
        "ready": True,
        "delegates_to": "audit",
        "runtime_contract_present": True,
        "runtime_contract_digest": "abc123",
        "digest_validated": True,
        "run_id": "run-audit",
        "node_count": 1,
        "node_kinds": ["agent-task"],
        "side_effect_nodes_complete": True,
        "blockers": [],
    }
    path.write_text(
        json.dumps(
            {
                "ready": True,
                "canonical_contract": "RunSpec",
                "model_calls": 0,
                "network_used": False,
                "agent_execution_attempted": False,
                "views": {
                    "mission": dict(view),
                    "swarm": dict(view, node_kinds=["swarm-unit", "swarm-fan-in"]),
                    "wrap": dict(view),
                },
                "blockers": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_manifest_validator_cli_can_fail_on_publication_gate(tmp_path: Path) -> None:
    module = _load_script("validate_benchmark_manifest")
    output = tmp_path / "validation.json"

    exit_code = module.main(
        [str(V4_MANIFEST), "--out", str(output), "--require-publication-ready"]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert payload["structurally_valid"] is True
    assert payload["publication_ready"] is False


def test_report_generator_writes_deterministic_publication_artifacts(tmp_path: Path) -> None:
    module = _load_script("generate_benchmark_report")
    json_output = tmp_path / "report.json"
    markdown_output = tmp_path / "report.md"
    artifact_output = tmp_path / "raw-artifacts.json"
    work_plan_output = tmp_path / "work-plan.json"
    product_smoke = tmp_path / "product-smoke.json"
    runtime_delegation = tmp_path / "runtime-delegation.json"
    _write_product_smoke(product_smoke)
    _write_runtime_delegation(runtime_delegation)

    exit_code = module.main(
        [
            str(SATURATED_REPORT),
            "--manifest",
            str(V4_MANIFEST),
            "--product-smoke",
            str(product_smoke),
            "--runtime-delegation",
            str(runtime_delegation),
            "--json-out",
            str(json_output),
            "--markdown-out",
            str(markdown_output),
            "--artifact-index-out",
            str(artifact_output),
            "--work-plan-out",
            str(work_plan_output),
        ]
    )

    payload = json.loads(json_output.read_text(encoding="utf-8"))
    artifact_index = json.loads(artifact_output.read_text(encoding="utf-8"))
    work_plan = json.loads(work_plan_output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["publication_ready"] is False
    assert payload["claim_language_gate"]["decision"] == "refuse"
    assert payload["product_surface"]["ready"] is True
    assert payload["product_surface"]["canonical_entrypoint"] == "run"
    assert payload["product_surface"]["unexpected_visible"] == []
    assert payload["product_smoke"]["ready"] is True
    assert payload["product_smoke"]["run_status"] == "planned"
    assert payload["runtime_delegation"]["ready"] is True
    assert payload["runtime_delegation"]["canonical_contract"] == "RunSpec"
    assert artifact_index["complete"] is False
    assert work_plan["publication_ready"] is False
    assert work_plan["deficits"]["product_surface_ready"] is True
    assert work_plan["deficits"]["product_smoke_ready"] is True
    assert work_plan["deficits"]["runtime_delegation_ready"] is True
    assert work_plan["deficits"]["tasks_to_add"] == 22
    assert work_plan["spend_gate"]["paid_full_matrix_allowed"] is False
    assert "NOT PUBLICATION-READY" in markdown_output.read_text(encoding="utf-8")
    assert "Product Surface" in markdown_output.read_text(encoding="utf-8")
    assert "Product Smoke" in markdown_output.read_text(encoding="utf-8")
    assert "Runtime Delegation" in markdown_output.read_text(encoding="utf-8")


def test_external_claim_gate_cli_refuses_strong_claim(tmp_path: Path) -> None:
    generator = _load_script("generate_benchmark_report")
    gate = _load_script("gate_external_claim")
    bundle_path = tmp_path / "report.json"

    generator.main(
        [
            str(SATURATED_REPORT),
            "--manifest",
            str(V4_MANIFEST),
            "--json-out",
            str(bundle_path),
        ]
    )
    exit_code = gate.main(
        [
            str(bundle_path),
            "--claim",
            "ONMC is state-of-the-art, better, and cheaper.",
        ]
    )

    assert exit_code == 2
