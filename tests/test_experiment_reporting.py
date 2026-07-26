from __future__ import annotations

from oh_no_my_claudecode.experiment.reporting import external_report_coverage_manifest


def test_external_report_coverage_accepts_complete_r13_report() -> None:
    report = {
        "records": [
            {
                "condition": "bare-agent",
                "task_id": "t1",
                "passed": False,
                "cost_usd": 0.1,
                "latency_ms": 10.0,
            },
            {
                "condition": "onmc-current",
                "task_id": "t1",
                "passed": True,
                "cost_usd": 0.2,
                "latency_ms": 12.0,
            },
        ],
        "summary": {
            "bare-agent": {
                "pass_at_1": 0.0,
                "pass_at_1_ci95": [0.0, 0.0],
                "mean_latency_ms": 10.0,
            },
            "onmc-current": {
                "pass_at_1": 1.0,
                "pass_at_1_ci95": [1.0, 1.0],
                "mean_latency_ms": 12.0,
            },
        },
        "paired": {
            "paired_tasks": 1,
            "mean_delta": 1.0,
            "delta_ci95": [1.0, 1.0],
            "per_task_delta": {"t1": 1.0},
        },
        "trajectory_artifacts": {
            "overall": {
                "usable_cells": 2,
                "artifact_cells": 2,
                "missing_artifacts": 0,
                "trajectory_hashes": ["a", "b"],
            },
            "by_condition": {
                "bare-agent": {
                    "usable_cells": 1,
                    "artifact_cells": 1,
                    "missing_artifacts": 0,
                    "trajectory_hashes": ["a"],
                },
                "onmc-current": {
                    "usable_cells": 1,
                    "artifact_cells": 1,
                    "missing_artifacts": 0,
                    "trajectory_hashes": ["b"],
                },
            },
        },
        "verifier_artifacts": {
            "overall": {
                "usable_cells": 2,
                "artifact_cells": 2,
                "missing_artifacts": 0,
                "output_hashes": ["a", "b"],
            },
            "by_condition": {
                "bare-agent": {
                    "usable_cells": 1,
                    "artifact_cells": 1,
                    "missing_artifacts": 0,
                    "output_hashes": ["a"],
                },
                "onmc-current": {
                    "usable_cells": 1,
                    "artifact_cells": 1,
                    "missing_artifacts": 0,
                    "output_hashes": ["b"],
                },
            },
        },
        "token_telemetry": {
            "overall": {
                "cells": 2,
                "reported_cells": 2,
                "input_tokens": 20,
                "output_tokens": 10,
                "context_tokens": 5,
            },
            "by_condition": {
                "bare-agent": {
                    "cells": 1,
                    "reported_cells": 1,
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "context_tokens": 0,
                },
                "onmc-current": {
                    "cells": 1,
                    "reported_cells": 1,
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "context_tokens": 5,
                },
            },
        },
        "failure_taxonomy": {
            "overall": {"wrong_change": 1},
            "by_condition": {
                "bare-agent": {"wrong_change": 1},
                "onmc-current": {},
            },
        },
        "leakage_notes": "audited",
        "environment": {"code_sha": "a", "config_hash": "b", "model": "c"},
    }

    coverage = external_report_coverage_manifest(report)

    assert coverage.claim_ready is True
    assert coverage.missing_count == 0
    assert {field.name for field in coverage.fields if field.covered} == {
        "raw_trajectories",
        "verifier_artifacts",
        "pass_rate",
        "pass_at_k",
        "paired_deltas",
        "uncertainty",
        "latency",
        "token_use",
        "cost_coverage",
        "failure_taxonomy",
        "leakage_audit",
        "environment_manifest",
    }
