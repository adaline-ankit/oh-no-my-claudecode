from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType

import pytest

from oh_no_my_claudecode.experiment.calibration import (
    CalibrationDecision,
    calibrate_external_report,
    calibrate_portfolio_report,
    calibrate_records,
)
from oh_no_my_claudecode.experiment.contracts import Condition

REPO_ROOT = Path(__file__).resolve().parents[1]
SATURATED_REPORT = REPO_ROOT / "datasets" / "experiment" / "reports" / (
    "external_v3_stage1_2026-07-25.json"
)
V4_MANIFEST = REPO_ROOT / "datasets" / "experiment" / "portfolio_external_v4.json"
SCRIPT_PATH = REPO_ROOT / "scripts" / "calibrate_external_report.py"


def _record(
    task_id: str,
    condition: str,
    passed: bool,
    *,
    cost_usd: float | None = 0.1,
    infra_error: str | None = None,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "condition": condition,
        "passed": passed,
        "cost_usd": cost_usd,
        "infra_error": infra_error,
    }


def _failure_taxonomy() -> dict[str, object]:
    return {
        "overall": {"wrong_change": 20},
        "by_condition": {
            Condition.BARE_AGENT.value: {"wrong_change": 20},
            Condition.ONMC_CURRENT.value: {},
        },
    }


def _token_telemetry() -> dict[str, object]:
    return {
        "overall": {
            "cells": 40,
            "reported_cells": 20,
            "input_tokens": 1000,
            "output_tokens": 500,
            "context_tokens": 250,
        },
        "by_condition": {
            Condition.BARE_AGENT.value: {
                "cells": 20,
                "reported_cells": 10,
                "input_tokens": 600,
                "output_tokens": 300,
                "context_tokens": 0,
            },
            Condition.ONMC_CURRENT.value: {
                "cells": 20,
                "reported_cells": 10,
                "input_tokens": 400,
                "output_tokens": 200,
                "context_tokens": 250,
            },
        },
    }


def _verifier_artifacts() -> dict[str, object]:
    return {
        "overall": {
            "cells": 40,
            "usable_cells": 40,
            "artifact_cells": 40,
            "missing_artifacts": 0,
            "unique_output_hashes": 2,
            "output_hashes": ["hash-a", "hash-b"],
        },
        "by_condition": {
            Condition.BARE_AGENT.value: {
                "cells": 20,
                "usable_cells": 20,
                "artifact_cells": 20,
                "missing_artifacts": 0,
                "unique_output_hashes": 1,
                "output_hashes": ["hash-a"],
            },
            Condition.ONMC_CURRENT.value: {
                "cells": 20,
                "usable_cells": 20,
                "artifact_cells": 20,
                "missing_artifacts": 0,
                "unique_output_hashes": 1,
                "output_hashes": ["hash-b"],
            },
        },
    }


def _trajectory_artifacts() -> dict[str, object]:
    return {
        "overall": {
            "cells": 40,
            "usable_cells": 40,
            "artifact_cells": 40,
            "missing_artifacts": 0,
            "unique_trajectory_hashes": 2,
            "trajectory_hashes": ["traj-a", "traj-b"],
        },
        "by_condition": {
            Condition.BARE_AGENT.value: {
                "cells": 20,
                "usable_cells": 20,
                "artifact_cells": 20,
                "missing_artifacts": 0,
                "unique_trajectory_hashes": 1,
                "trajectory_hashes": ["traj-a"],
            },
            Condition.ONMC_CURRENT.value: {
                "cells": 20,
                "usable_cells": 20,
                "artifact_cells": 20,
                "missing_artifacts": 0,
                "unique_trajectory_hashes": 1,
                "trajectory_hashes": ["traj-b"],
            },
        },
    }


def test_saturated_report_is_not_claim_ready() -> None:
    raw = json.loads(SATURATED_REPORT.read_text(encoding="utf-8"))

    report = calibrate_external_report(raw)

    assert report.decision is CalibrationDecision.NEEDS_DISCRIMINATION
    assert report.quality_claim_ready is False
    assert report.cost_claim_ready is False
    assert report.discriminative_tasks == 0
    assert report.saturated_tasks == 24
    assert any("discriminative" in reason for reason in report.reasons)


def test_discriminative_tasks_pass_quality_and_cost_gate() -> None:
    records: list[dict[str, object]] = []
    for index in range(10):
        task_id = f"task-{index}"
        records.append(_record(task_id, Condition.BARE_AGENT.value, False))
        records.append(_record(task_id, Condition.ONMC_CURRENT.value, True))

    report = calibrate_records(
        records,
        conditions=(Condition.BARE_AGENT, Condition.ONMC_CURRENT),
    )

    assert report.decision is CalibrationDecision.READY
    assert report.quality_claim_ready is True
    assert report.cost_claim_ready is True
    assert report.discriminative_tasks == 10
    assert report.saturated_tasks == 0
    assert report.reasons == ()


def test_incomplete_cost_blocks_cost_claim_but_not_quality_claim() -> None:
    records: list[dict[str, object]] = []
    for index in range(10):
        task_id = f"task-{index}"
        records.append(_record(task_id, Condition.BARE_AGENT.value, False, cost_usd=None))
        records.append(_record(task_id, Condition.ONMC_CURRENT.value, True))

    report = calibrate_records(
        records,
        conditions=(Condition.BARE_AGENT, Condition.ONMC_CURRENT),
    )

    assert report.decision is CalibrationDecision.READY
    assert report.quality_claim_ready is True
    assert report.cost_claim_ready is False
    assert report.incomplete_cost_conditions == (Condition.BARE_AGENT.value,)
    assert any("cost telemetry incomplete" in reason for reason in report.reasons)


def test_infra_failures_make_report_incomplete() -> None:
    records = [
        _record("task-a", Condition.BARE_AGENT.value, False, infra_error="clone failed"),
        _record("task-a", Condition.ONMC_CURRENT.value, True),
    ]

    report = calibrate_records(
        records,
        conditions=(Condition.BARE_AGENT, Condition.ONMC_CURRENT),
        min_discriminative_tasks=1,
    )

    assert report.decision is CalibrationDecision.INCOMPLETE
    assert report.quality_claim_ready is False
    assert report.incomplete_cell_count == 1
    assert any("incomplete" in reason for reason in report.reasons)


def test_invalid_records_are_rejected() -> None:
    with pytest.raises(ValueError, match="record.passed"):
        calibrate_records(
            [
                {
                    "task_id": "task-a",
                    "condition": Condition.BARE_AGENT.value,
                    "passed": "yes",
                }
            ],
            conditions=(Condition.BARE_AGENT, Condition.ONMC_CURRENT),
        )

    with pytest.raises(ValueError, match="two distinct"):
        calibrate_records(
            [_record("task-a", Condition.BARE_AGENT.value, True)],
            conditions=(Condition.BARE_AGENT,),
        )


def test_manifest_gate_rejects_stale_report_for_current_v4_manifest() -> None:
    manifest = json.loads(V4_MANIFEST.read_text(encoding="utf-8"))
    report = json.loads(SATURATED_REPORT.read_text(encoding="utf-8"))

    gated = calibrate_portfolio_report(manifest, report)

    assert gated.quality_claim_ready is False
    assert gated.cost_claim_ready is False
    assert gated.manifest_tasks == 28
    assert gated.reported_tasks == 24
    assert len(gated.missing_tasks) == 4
    assert gated.manifest_task_set_revision == "external-v4-2026-07-25"
    assert gated.report_task_set_revision == "external-v3-2026-07-25"
    assert any("task_set_revision mismatch" in reason for reason in gated.reasons)
    assert any("missing from report" in reason for reason in gated.reasons)


def test_manifest_gate_accepts_complete_discriminative_report() -> None:
    task_ids = [f"task-{index}" for index in range(10)]
    manifest = {
        "audit_status": "valid",
        "leakage_notes": "frozen public repo tasks audited for leakage",
        "experiment": {
            "task_set_revision": "rev-good",
            "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
            "trials": 2,
            "environment": {
                "code_sha": "abc123",
                "config_hash": "cfg1",
                "model": "claude-test",
                "provider": "anthropic",
                "image": "local",
            },
        },
        "tasks": [{"task_id": task_id} for task_id in task_ids],
    }
    records: list[dict[str, object]] = []
    for task_id in task_ids:
        for trial in range(2):
            records.append(
                {
                    **_record(task_id, Condition.BARE_AGENT.value, False),
                    "trial": trial + 1,
                }
            )
            records.append(
                {
                    **_record(task_id, Condition.ONMC_CURRENT.value, True),
                    "trial": trial + 1,
                }
            )
    report = {
        "task_set_revision": "rev-good",
        "audit_status": "valid",
        "leakage_notes": "frozen public repo tasks audited for leakage",
        "environment": {
            "code_sha": "abc123",
            "config_hash": "cfg1",
            "model": "claude-test",
            "provider": "anthropic",
            "image": "local",
        },
        "failure_taxonomy": _failure_taxonomy(),
        "token_telemetry": _token_telemetry(),
        "trajectory_artifacts": _trajectory_artifacts(),
        "verifier_artifacts": _verifier_artifacts(),
        "code_sha": "abc123",
        "code_sha_under_test": "def456",
        "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
        "trials_per_cell": 2,
        "records": records,
    }

    gated = calibrate_portfolio_report(manifest, report)

    assert gated.quality_claim_ready is True
    assert gated.cost_claim_ready is True
    assert gated.metadata_audit.ready is True
    assert gated.metadata_audit.environment_manifest_present is True
    assert gated.metadata_audit.environment_manifest_matches is True
    assert gated.metadata_audit.failure_taxonomy_present is True
    assert gated.metadata_audit.failure_taxonomy_complete is True
    assert gated.metadata_audit.token_telemetry_present is True
    assert gated.metadata_audit.token_telemetry_complete is True
    assert gated.metadata_audit.trajectory_artifacts_present is True
    assert gated.metadata_audit.trajectory_artifacts_complete is True
    assert gated.metadata_audit.verifier_artifacts_present is True
    assert gated.metadata_audit.verifier_artifacts_complete is True
    assert gated.missing_tasks == ()
    assert gated.unexpected_tasks == ()
    assert gated.reasons == ()


def test_manifest_gate_blocks_missing_report_metadata() -> None:
    task_ids = [f"task-{index}" for index in range(10)]
    manifest = {
        "audit_status": "valid",
        "leakage_notes": "audited public repo tasks",
        "experiment": {
            "task_set_revision": "rev-good",
            "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
            "trials": 2,
            "environment": {
                "code_sha": "abc123",
                "config_hash": "cfg1",
                "model": "claude-test",
                "provider": "anthropic",
                "image": "local",
            },
        },
        "tasks": [{"task_id": task_id} for task_id in task_ids],
    }
    records: list[dict[str, object]] = []
    for task_id in task_ids:
        for trial in range(2):
            records.append(
                {
                    **_record(task_id, Condition.BARE_AGENT.value, False),
                    "trial": trial + 1,
                }
            )
            records.append(
                {
                    **_record(task_id, Condition.ONMC_CURRENT.value, True),
                    "trial": trial + 1,
                }
            )
    report = {
        "task_set_revision": "rev-good",
        "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
        "trials_per_cell": 2,
        "records": records,
    }

    gated = calibrate_portfolio_report(manifest, report)

    assert gated.calibration.quality_claim_ready is True
    assert gated.metadata_audit.ready is False
    assert gated.quality_claim_ready is False
    assert gated.cost_claim_ready is False
    assert gated.metadata_audit.missing_fields == (
        "report.audit_status",
        "report.code_sha",
        "report.code_sha_under_test",
        "report.leakage_notes",
        "report.environment",
        "report.failure_taxonomy",
        "report.token_telemetry",
        "report.trajectory_artifacts",
        "report.verifier_artifacts",
    )
    assert any("leakage/reproducibility" in reason for reason in gated.reasons)


def test_manifest_gate_blocks_environment_manifest_mismatch() -> None:
    task_ids = [f"task-{index}" for index in range(10)]
    manifest = {
        "audit_status": "valid",
        "leakage_notes": "audited public repo tasks",
        "experiment": {
            "task_set_revision": "rev-good",
            "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
            "trials": 2,
            "environment": {
                "code_sha": "abc123",
                "config_hash": "cfg1",
                "model": "claude-test",
                "provider": "anthropic",
                "image": "local",
            },
        },
        "tasks": [{"task_id": task_id} for task_id in task_ids],
    }
    records: list[dict[str, object]] = []
    for task_id in task_ids:
        for trial in range(2):
            records.append(
                {
                    **_record(task_id, Condition.BARE_AGENT.value, False),
                    "trial": trial + 1,
                }
            )
            records.append(
                {
                    **_record(task_id, Condition.ONMC_CURRENT.value, True),
                    "trial": trial + 1,
                }
            )
    report = {
        "task_set_revision": "rev-good",
        "audit_status": "valid",
        "leakage_notes": "audited public repo tasks",
        "environment": {
            "code_sha": "abc123",
            "config_hash": "different-cfg",
            "model": "claude-test",
            "provider": "anthropic",
            "image": "local",
        },
        "failure_taxonomy": _failure_taxonomy(),
        "token_telemetry": _token_telemetry(),
        "trajectory_artifacts": _trajectory_artifacts(),
        "verifier_artifacts": _verifier_artifacts(),
        "code_sha": "abc123",
        "code_sha_under_test": "def456",
        "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
        "trials_per_cell": 2,
        "records": records,
    }

    gated = calibrate_portfolio_report(manifest, report)

    assert gated.calibration.quality_claim_ready is True
    assert gated.metadata_audit.ready is False
    assert gated.metadata_audit.environment_manifest_present is True
    assert gated.metadata_audit.environment_manifest_matches is False
    assert gated.metadata_audit.mismatched_fields == ("report.environment",)
    assert gated.quality_claim_ready is False


def test_manifest_gate_blocks_incomplete_failure_taxonomy() -> None:
    task_ids = [f"task-{index}" for index in range(10)]
    manifest = {
        "audit_status": "valid",
        "leakage_notes": "audited public repo tasks",
        "experiment": {
            "task_set_revision": "rev-good",
            "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
            "trials": 2,
            "environment": {
                "code_sha": "abc123",
                "config_hash": "cfg1",
                "model": "claude-test",
                "provider": "anthropic",
                "image": "local",
            },
        },
        "tasks": [{"task_id": task_id} for task_id in task_ids],
    }
    records: list[dict[str, object]] = []
    for task_id in task_ids:
        for trial in range(2):
            records.append(
                {
                    **_record(task_id, Condition.BARE_AGENT.value, False),
                    "trial": trial + 1,
                }
            )
            records.append(
                {
                    **_record(task_id, Condition.ONMC_CURRENT.value, True),
                    "trial": trial + 1,
                }
            )
    report = {
        "task_set_revision": "rev-good",
        "audit_status": "valid",
        "leakage_notes": "audited public repo tasks",
        "environment": {
            "code_sha": "abc123",
            "config_hash": "cfg1",
            "model": "claude-test",
            "provider": "anthropic",
            "image": "local",
        },
        "failure_taxonomy": {
            "overall": {"wrong_change": 20},
            "by_condition": {
                Condition.BARE_AGENT.value: {"wrong_change": 20},
            },
        },
        "token_telemetry": _token_telemetry(),
        "trajectory_artifacts": _trajectory_artifacts(),
        "verifier_artifacts": _verifier_artifacts(),
        "code_sha": "abc123",
        "code_sha_under_test": "def456",
        "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
        "trials_per_cell": 2,
        "records": records,
    }

    gated = calibrate_portfolio_report(manifest, report)

    assert gated.calibration.quality_claim_ready is True
    assert gated.metadata_audit.failure_taxonomy_present is True
    assert gated.metadata_audit.failure_taxonomy_complete is False
    assert gated.metadata_audit.mismatched_fields == ("report.failure_taxonomy",)
    assert gated.quality_claim_ready is False


def test_manifest_gate_blocks_incomplete_token_telemetry() -> None:
    task_ids = [f"task-{index}" for index in range(10)]
    manifest = {
        "audit_status": "valid",
        "leakage_notes": "audited public repo tasks",
        "experiment": {
            "task_set_revision": "rev-good",
            "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
            "trials": 2,
            "environment": {
                "code_sha": "abc123",
                "config_hash": "cfg1",
                "model": "claude-test",
                "provider": "anthropic",
                "image": "local",
            },
        },
        "tasks": [{"task_id": task_id} for task_id in task_ids],
    }
    records: list[dict[str, object]] = []
    for task_id in task_ids:
        for trial in range(2):
            records.append(
                {
                    **_record(task_id, Condition.BARE_AGENT.value, False),
                    "trial": trial + 1,
                }
            )
            records.append(
                {
                    **_record(task_id, Condition.ONMC_CURRENT.value, True),
                    "trial": trial + 1,
                }
            )
    report = {
        "task_set_revision": "rev-good",
        "audit_status": "valid",
        "leakage_notes": "audited public repo tasks",
        "environment": {
            "code_sha": "abc123",
            "config_hash": "cfg1",
            "model": "claude-test",
            "provider": "anthropic",
            "image": "local",
        },
        "failure_taxonomy": _failure_taxonomy(),
        "token_telemetry": {
            "overall": {
                "cells": 40,
                "reported_cells": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "context_tokens": 0,
            },
            "by_condition": {
                Condition.BARE_AGENT.value: {
                    "cells": 20,
                    "reported_cells": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "context_tokens": 0,
                },
            },
        },
        "trajectory_artifacts": _trajectory_artifacts(),
        "verifier_artifacts": _verifier_artifacts(),
        "code_sha": "abc123",
        "code_sha_under_test": "def456",
        "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
        "trials_per_cell": 2,
        "records": records,
    }

    gated = calibrate_portfolio_report(manifest, report)

    assert gated.calibration.quality_claim_ready is True
    assert gated.metadata_audit.token_telemetry_present is True
    assert gated.metadata_audit.token_telemetry_complete is False
    assert gated.metadata_audit.mismatched_fields == ("report.token_telemetry",)
    assert gated.quality_claim_ready is False


def test_manifest_gate_blocks_incomplete_trajectory_artifacts() -> None:
    task_ids = [f"task-{index}" for index in range(10)]
    manifest = {
        "audit_status": "valid",
        "leakage_notes": "audited public repo tasks",
        "experiment": {
            "task_set_revision": "rev-good",
            "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
            "trials": 2,
            "environment": {
                "code_sha": "abc123",
                "config_hash": "cfg1",
                "model": "claude-test",
                "provider": "anthropic",
                "image": "local",
            },
        },
        "tasks": [{"task_id": task_id} for task_id in task_ids],
    }
    records: list[dict[str, object]] = []
    for task_id in task_ids:
        for trial in range(2):
            records.append(
                {
                    **_record(task_id, Condition.BARE_AGENT.value, False),
                    "trial": trial + 1,
                }
            )
            records.append(
                {
                    **_record(task_id, Condition.ONMC_CURRENT.value, True),
                    "trial": trial + 1,
                }
            )
    incomplete_artifacts = _trajectory_artifacts()
    by_condition = incomplete_artifacts["by_condition"]
    assert isinstance(by_condition, dict)
    by_condition[Condition.ONMC_CURRENT.value] = {
        "cells": 20,
        "usable_cells": 20,
        "artifact_cells": 19,
        "missing_artifacts": 1,
        "unique_trajectory_hashes": 1,
        "trajectory_hashes": ["traj-b"],
    }
    report = {
        "task_set_revision": "rev-good",
        "audit_status": "valid",
        "leakage_notes": "audited public repo tasks",
        "environment": {
            "code_sha": "abc123",
            "config_hash": "cfg1",
            "model": "claude-test",
            "provider": "anthropic",
            "image": "local",
        },
        "failure_taxonomy": _failure_taxonomy(),
        "token_telemetry": _token_telemetry(),
        "trajectory_artifacts": incomplete_artifacts,
        "verifier_artifacts": _verifier_artifacts(),
        "code_sha": "abc123",
        "code_sha_under_test": "def456",
        "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
        "trials_per_cell": 2,
        "records": records,
    }

    gated = calibrate_portfolio_report(manifest, report)

    assert gated.calibration.quality_claim_ready is True
    assert gated.metadata_audit.trajectory_artifacts_present is True
    assert gated.metadata_audit.trajectory_artifacts_complete is False
    assert gated.metadata_audit.mismatched_fields == ("report.trajectory_artifacts",)
    assert gated.quality_claim_ready is False


def test_manifest_gate_blocks_incomplete_verifier_artifacts() -> None:
    task_ids = [f"task-{index}" for index in range(10)]
    manifest = {
        "audit_status": "valid",
        "leakage_notes": "audited public repo tasks",
        "experiment": {
            "task_set_revision": "rev-good",
            "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
            "trials": 2,
            "environment": {
                "code_sha": "abc123",
                "config_hash": "cfg1",
                "model": "claude-test",
                "provider": "anthropic",
                "image": "local",
            },
        },
        "tasks": [{"task_id": task_id} for task_id in task_ids],
    }
    records: list[dict[str, object]] = []
    for task_id in task_ids:
        for trial in range(2):
            records.append(
                {
                    **_record(task_id, Condition.BARE_AGENT.value, False),
                    "trial": trial + 1,
                }
            )
            records.append(
                {
                    **_record(task_id, Condition.ONMC_CURRENT.value, True),
                    "trial": trial + 1,
                }
            )
    incomplete_artifacts = _verifier_artifacts()
    by_condition = incomplete_artifacts["by_condition"]
    assert isinstance(by_condition, dict)
    by_condition[Condition.ONMC_CURRENT.value] = {
        "cells": 20,
        "usable_cells": 20,
        "artifact_cells": 19,
        "missing_artifacts": 1,
        "unique_output_hashes": 1,
        "output_hashes": ["hash-b"],
    }
    report = {
        "task_set_revision": "rev-good",
        "audit_status": "valid",
        "leakage_notes": "audited public repo tasks",
        "environment": {
            "code_sha": "abc123",
            "config_hash": "cfg1",
            "model": "claude-test",
            "provider": "anthropic",
            "image": "local",
        },
        "failure_taxonomy": _failure_taxonomy(),
        "token_telemetry": _token_telemetry(),
        "trajectory_artifacts": _trajectory_artifacts(),
        "verifier_artifacts": incomplete_artifacts,
        "code_sha": "abc123",
        "code_sha_under_test": "def456",
        "conditions": [Condition.BARE_AGENT.value, Condition.ONMC_CURRENT.value],
        "trials_per_cell": 2,
        "records": records,
    }

    gated = calibrate_portfolio_report(manifest, report)

    assert gated.calibration.quality_claim_ready is True
    assert gated.metadata_audit.verifier_artifacts_present is True
    assert gated.metadata_audit.verifier_artifacts_complete is False
    assert gated.metadata_audit.mismatched_fields == ("report.verifier_artifacts",)
    assert gated.quality_claim_ready is False


def _load_script() -> ModuleType:
    module_name = "_calibrate_external_report_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_calibration_script_writes_json_and_markdown(tmp_path: Path) -> None:
    script = _load_script()
    out = tmp_path / "calibration.json"

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = script.main([str(SATURATED_REPORT), "--out", str(out)])

    assert exit_code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["benchmark_plan"]["task_count"] == 24
    assert payload["benchmark_plan"]["sample_size_ready"] is False
    assert payload["claim_readiness"]["decision"] == "not-ready"
    assert payload["claim_readiness"]["blocked_gates"] == [
        "benchmark_plan",
        "portfolio_coverage",
        "calibration",
        "report_coverage",
        "verifier_calibration",
    ]
    assert payload["claim_readiness"]["report_coverage_ready"] is False
    assert payload["claim_readiness"]["verifier_calibration_ready"] is False
    assert payload["calibration"]["decision"] == "needs-discrimination"
    assert payload["calibration"]["saturated_tasks"] == 24
    assert payload["report_coverage"]["claim_ready"] is False
    assert payload["verifier_calibration"]["claim_ready"] is False
    assert payload["verifier_calibration"]["caught_false_green"] == 13
    assert payload["verifier_calibration"]["false_positive_legitimate"] == 1
    assert any(
        item["name"] == "raw_trajectories" and item["covered"] is False
        for item in payload["report_coverage"]["fields"]
    )
    assert any(
        item["name"] == "paired_deltas" and item["covered"] is True
        for item in payload["report_coverage"]["fields"]
    )
    assert payload["claim_language_gate"]["decision"] == "refuse"
    assert payload["claim_language_gate"]["detected_claims"] == ["quality", "cost"]
    assert any(
        "quality improvement claim" in reason
        for reason in payload["claim_language_gate"]["reasons"]
    )
    assert any(
        "receipt/report coverage is incomplete" in reason
        for reason in payload["claim_language_gate"]["reasons"]
    )
    assert "external improvement claims are blocked" in payload["claim_language_gate"][
        "suggested_safe_claim"
    ]
    printed = json.loads(stdout.getvalue())
    assert printed == payload

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = script.main([str(SATURATED_REPORT), "--markdown"])

    assert exit_code == 0
    markdown = stdout.getvalue()
    assert "decision: `needs-discrimination`" in markdown
    assert "saturated_tasks: `24`" in markdown
    assert "claim_ready: `false`" in markdown
    assert "external_claim_decision: `not-ready`" in markdown
    assert "claim_language_decision: `refuse`" in markdown
    assert "report_coverage_claim_ready: `false`" in markdown
    assert "verifier_calibration_claim_ready: `false`" in markdown
    assert "## Report Coverage" in markdown
    assert "## Verifier Calibration" in markdown
    assert "raw_trajectories: missing" in markdown
    assert "## Claim Language Gate" in markdown
    assert "suggested_safe_claim: ONMC records harness evidence" in markdown


def test_calibration_script_manifest_gate(tmp_path: Path) -> None:
    script = _load_script()
    out = tmp_path / "manifest-gate.json"
    stdout = io.StringIO()

    with redirect_stdout(stdout):
        exit_code = script.main(
            [
                str(SATURATED_REPORT),
                "--manifest",
                str(V4_MANIFEST),
                "--out",
                str(out),
            ]
        )

    assert exit_code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["benchmark_plan"]["task_count"] == 28
    assert payload["benchmark_plan"]["total_cells"] == 168
    assert payload["coverage_gate"]["repo_count"] == 6
    assert payload["coverage_gate"]["claim_ready"] is False
    assert payload["coverage_gate"]["task_kind_counts"]["feature"] == 19
    assert payload["portfolio_gap_plan"]["minimum_total_additions"] == 22
    assert payload["portfolio_gap_plan"]["suggested_minimum_additions_by_kind"] == {
        "long-running": 2,
        "refactor": 2,
    }
    assert payload["portfolio_gap_plan"]["unallocated_non_dominant_additions"] == 18
    assert payload["portfolio_expansion_draft"]["slot_count"] == 22
    assert payload["portfolio_expansion_draft"]["slots_by_kind"] == {
        "bugfix": 4,
        "long-running": 9,
        "refactor": 9,
    }
    assert payload["claim_readiness"]["decision"] == "not-ready"
    assert payload["report_coverage"]["claim_ready"] is False
    assert payload["claim_language_gate"]["decision"] == "refuse"
    assert payload["claim_language_gate"]["detected_claims"] == ["quality", "cost"]
    assert payload["claim_readiness"]["blocked_gates"] == [
        "benchmark_plan",
        "portfolio_coverage",
        "calibration",
        "report_coverage",
        "verifier_calibration",
    ]
    assert payload["claim_readiness"]["report_coverage_ready"] is False
    assert payload["claim_readiness"]["verifier_calibration_ready"] is False
    assert any(
        "Add at least 22 benchmark task" in action
        for action in payload["claim_readiness"]["next_actions"]
    )
    gate = payload["manifest_gate"]
    assert gate["quality_claim_ready"] is False
    assert gate["metadata_audit"]["ready"] is False
    assert gate["metadata_audit"]["report_leakage_notes_present"] is False
    assert gate["metadata_audit"]["environment_manifest_present"] is False
    assert gate["metadata_audit"]["environment_manifest_matches"] is False
    assert gate["metadata_audit"]["failure_taxonomy_present"] is False
    assert gate["metadata_audit"]["failure_taxonomy_complete"] is False
    assert gate["metadata_audit"]["token_telemetry_present"] is False
    assert gate["metadata_audit"]["token_telemetry_complete"] is False
    assert gate["metadata_audit"]["trajectory_artifacts_present"] is False
    assert gate["metadata_audit"]["trajectory_artifacts_complete"] is False
    assert gate["metadata_audit"]["verifier_artifacts_present"] is False
    assert gate["metadata_audit"]["verifier_artifacts_complete"] is False
    assert any(
        item in gate["metadata_audit"]["missing_fields"]
        for item in (
            "report.leakage_notes",
            "report.environment",
            "report.failure_taxonomy",
            "report.token_telemetry",
            "report.trajectory_artifacts",
            "report.verifier_artifacts",
        )
    )
    assert gate["manifest_tasks"] == 28
    assert gate["reported_tasks"] == 24
    assert len(gate["missing_tasks"]) == 4
    assert json.loads(stdout.getvalue()) == payload
