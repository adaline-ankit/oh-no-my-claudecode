"""Calibration gates for ONMC external benchmark evidence.

This module answers a narrow question before any product claim is made:

Can this report actually discriminate between conditions, and is cost telemetry
complete enough to cite?

It is deliberately offline and pure. It reads already-collected trial records
from ``scripts/run_external_eval.py`` or an equivalent report and returns a
typed gate result. No agent, subprocess, network, or provider call is involved.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from oh_no_my_claudecode.experiment.contracts import Condition
from oh_no_my_claudecode.experiment.stats import mean

__all__ = [
    "CalibrationDecision",
    "CalibrationReport",
    "ManifestCalibrationReport",
    "ReportMetadataAudit",
    "TaskCalibration",
    "calibrate_external_report",
    "calibrate_portfolio_report",
    "calibrate_records",
]


class CalibrationDecision(StrEnum):
    """Final gate status for a benchmark report."""

    READY = "ready"
    NEEDS_DISCRIMINATION = "needs-discrimination"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class TaskCalibration:
    """Per-task discriminativeness summary."""

    task_id: str
    pass_rates: tuple[tuple[str, float], ...]
    usable_cells: int
    saturated: bool
    discriminative: bool
    max_delta: float

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "pass_rates": dict(self.pass_rates),
            "usable_cells": self.usable_cells,
            "saturated": self.saturated,
            "discriminative": self.discriminative,
            "max_delta": self.max_delta,
        }


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """Claim-readiness report derived from measured trial records."""

    decision: CalibrationDecision
    total_tasks: int
    discriminative_tasks: int
    saturated_tasks: int
    incomplete_cost_conditions: tuple[str, ...]
    incomplete_cell_count: int
    min_discriminative_tasks: int
    min_pass_delta: float
    quality_claim_ready: bool
    cost_claim_ready: bool
    reasons: tuple[str, ...]
    tasks: tuple[TaskCalibration, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.value,
            "total_tasks": self.total_tasks,
            "discriminative_tasks": self.discriminative_tasks,
            "saturated_tasks": self.saturated_tasks,
            "incomplete_cost_conditions": list(self.incomplete_cost_conditions),
            "incomplete_cell_count": self.incomplete_cell_count,
            "min_discriminative_tasks": self.min_discriminative_tasks,
            "min_pass_delta": self.min_pass_delta,
            "quality_claim_ready": self.quality_claim_ready,
            "cost_claim_ready": self.cost_claim_ready,
            "reasons": list(self.reasons),
            "tasks": [task.to_dict() for task in self.tasks],
        }


@dataclass(frozen=True, slots=True)
class ManifestCalibrationReport:
    """Calibration plus manifest/report coverage gates."""

    calibration: CalibrationReport
    metadata_audit: ReportMetadataAudit
    manifest_task_set_revision: str
    report_task_set_revision: str | None
    audit_status: str
    manifest_tasks: int
    reported_tasks: int
    missing_tasks: tuple[str, ...]
    unexpected_tasks: tuple[str, ...]
    expected_conditions: tuple[str, ...]
    reported_conditions: tuple[str, ...]
    expected_trials: int
    reported_trials: int | None
    quality_claim_ready: bool
    cost_claim_ready: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "calibration": self.calibration.to_dict(),
            "metadata_audit": self.metadata_audit.to_dict(),
            "manifest_task_set_revision": self.manifest_task_set_revision,
            "report_task_set_revision": self.report_task_set_revision,
            "audit_status": self.audit_status,
            "manifest_tasks": self.manifest_tasks,
            "reported_tasks": self.reported_tasks,
            "missing_tasks": list(self.missing_tasks),
            "unexpected_tasks": list(self.unexpected_tasks),
            "expected_conditions": list(self.expected_conditions),
            "reported_conditions": list(self.reported_conditions),
            "expected_trials": self.expected_trials,
            "reported_trials": self.reported_trials,
            "quality_claim_ready": self.quality_claim_ready,
            "cost_claim_ready": self.cost_claim_ready,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class ReportMetadataAudit:
    """Reproducibility and leakage metadata gate for saved benchmark reports."""

    ready: bool
    manifest_audit_status: str
    report_audit_status: str | None
    expected_code_sha: str | None
    report_code_sha: str | None
    code_sha_under_test: str | None
    environment_manifest_present: bool
    environment_manifest_matches: bool
    failure_taxonomy_present: bool
    failure_taxonomy_complete: bool
    token_telemetry_present: bool
    token_telemetry_complete: bool
    trajectory_artifacts_present: bool
    trajectory_artifacts_complete: bool
    verifier_artifacts_present: bool
    verifier_artifacts_complete: bool
    leakage_notes_present: bool
    report_leakage_notes_present: bool
    missing_fields: tuple[str, ...]
    mismatched_fields: tuple[str, ...]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "manifest_audit_status": self.manifest_audit_status,
            "report_audit_status": self.report_audit_status,
            "expected_code_sha": self.expected_code_sha,
            "report_code_sha": self.report_code_sha,
            "code_sha_under_test": self.code_sha_under_test,
            "environment_manifest_present": self.environment_manifest_present,
            "environment_manifest_matches": self.environment_manifest_matches,
            "failure_taxonomy_present": self.failure_taxonomy_present,
            "failure_taxonomy_complete": self.failure_taxonomy_complete,
            "token_telemetry_present": self.token_telemetry_present,
            "token_telemetry_complete": self.token_telemetry_complete,
            "trajectory_artifacts_present": self.trajectory_artifacts_present,
            "trajectory_artifacts_complete": self.trajectory_artifacts_complete,
            "verifier_artifacts_present": self.verifier_artifacts_present,
            "verifier_artifacts_complete": self.verifier_artifacts_complete,
            "leakage_notes_present": self.leakage_notes_present,
            "report_leakage_notes_present": self.report_leakage_notes_present,
            "missing_fields": list(self.missing_fields),
            "mismatched_fields": list(self.mismatched_fields),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class _Record:
    task_id: str
    condition: str
    passed: bool
    infra_error: str | None
    cost_usd: float | None


def calibrate_external_report(
    report: Mapping[str, object],
    *,
    min_discriminative_tasks: int = 10,
    min_pass_delta: float = 0.05,
) -> CalibrationReport:
    """Calibrate a JSON-like report emitted by ``run_external_eval.py``."""
    raw_records = report.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("report.records must be a list")
    raw_conditions = report.get("conditions")
    if not isinstance(raw_conditions, list):
        raise ValueError("report.conditions must be a list")
    conditions = tuple(_condition_value(item) for item in raw_conditions)
    return calibrate_records(
        raw_records,
        conditions=conditions,
        min_discriminative_tasks=min_discriminative_tasks,
        min_pass_delta=min_pass_delta,
    )


def calibrate_portfolio_report(
    manifest: Mapping[str, object],
    report: Mapping[str, object],
    *,
    min_discriminative_tasks: int = 10,
    min_pass_delta: float = 0.05,
) -> ManifestCalibrationReport:
    """Calibrate a report against the frozen portfolio it is supposed to cover."""
    experiment = _mapping(manifest.get("experiment"), "manifest.experiment")
    raw_tasks = manifest.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ValueError("manifest.tasks must be a list")
    expected_tasks = tuple(sorted(_task_id(item) for item in raw_tasks))
    reported_tasks = tuple(sorted(_reported_task_ids(report)))
    missing = tuple(task for task in expected_tasks if task not in reported_tasks)
    unexpected = tuple(task for task in reported_tasks if task not in expected_tasks)
    raw_expected_conditions = _list(
        experiment.get("conditions"),
        "manifest.conditions",
    )
    expected_conditions = tuple(
        _condition_value(item) for item in raw_expected_conditions
    )
    reported_conditions = tuple(
        _condition_value(item) for item in _list(report.get("conditions"), "report.conditions")
    )
    expected_revision = _string(
        experiment.get("task_set_revision"),
        "manifest.experiment.task_set_revision",
    )
    report_revision = _optional_string(report.get("task_set_revision"), "report.task_set_revision")
    expected_trials = _integer(experiment.get("trials"), "manifest.experiment.trials")
    reported_trials = _optional_integer(report.get("trials_per_cell"), "report.trials_per_cell")
    audit_status = _string(manifest.get("audit_status"), "manifest.audit_status")
    metadata_audit = _audit_report_metadata(manifest, report)
    calibration = calibrate_external_report(
        report,
        min_discriminative_tasks=min_discriminative_tasks,
        min_pass_delta=min_pass_delta,
    )
    reasons = list(calibration.reasons)
    if expected_revision != report_revision:
        reasons.append(
            f"task_set_revision mismatch: manifest={expected_revision}, report={report_revision}"
        )
    if expected_conditions != reported_conditions:
        reasons.append(
            "condition mismatch: "
            f"manifest={list(expected_conditions)}, report={list(reported_conditions)}"
        )
    if reported_trials != expected_trials:
        reasons.append(
            f"trial count mismatch: manifest={expected_trials}, report={reported_trials}"
        )
    if audit_status != "valid":
        reasons.append(f"manifest audit_status is {audit_status}, not valid")
    if not metadata_audit.ready:
        reasons.extend(metadata_audit.reasons)
    if expected_trials < 2:
        reasons.append("manifest trials must be at least 2 for claim uncertainty")
    if missing:
        reasons.append(f"{len(missing)} manifest task(s) missing from report")
    if unexpected:
        reasons.append(f"{len(unexpected)} reported task(s) are absent from manifest")
    structural_ready = (
        expected_revision == report_revision
        and expected_conditions == reported_conditions
        and reported_trials == expected_trials
        and audit_status == "valid"
        and metadata_audit.ready
        and expected_trials >= 2
        and not missing
        and not unexpected
    )
    quality_ready = structural_ready and calibration.quality_claim_ready
    return ManifestCalibrationReport(
        calibration=calibration,
        metadata_audit=metadata_audit,
        manifest_task_set_revision=expected_revision,
        report_task_set_revision=report_revision,
        audit_status=audit_status,
        manifest_tasks=len(expected_tasks),
        reported_tasks=len(reported_tasks),
        missing_tasks=missing,
        unexpected_tasks=unexpected,
        expected_conditions=expected_conditions,
        reported_conditions=reported_conditions,
        expected_trials=expected_trials,
        reported_trials=reported_trials,
        quality_claim_ready=quality_ready,
        cost_claim_ready=quality_ready and calibration.cost_claim_ready,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _audit_report_metadata(
    manifest: Mapping[str, object],
    report: Mapping[str, object],
) -> ReportMetadataAudit:
    experiment = _mapping(manifest.get("experiment"), "manifest.experiment")
    environment = _mapping(experiment.get("environment"), "manifest.experiment.environment")
    manifest_audit_status = _string(manifest.get("audit_status"), "manifest.audit_status")
    expected_code_sha = _string(
        environment.get("code_sha"),
        "manifest.experiment.environment.code_sha",
    )
    report_audit_status = _optional_string(report.get("audit_status"), "report.audit_status")
    report_code_sha = _optional_string(report.get("code_sha"), "report.code_sha")
    code_sha_under_test = _optional_string(
        report.get("code_sha_under_test"),
        "report.code_sha_under_test",
    )
    leakage_notes = _optional_string(manifest.get("leakage_notes"), "manifest.leakage_notes")
    report_leakage_notes = _optional_string(report.get("leakage_notes"), "report.leakage_notes")
    report_environment = report.get("environment")
    expected_conditions = tuple(
        _condition_value(item)
        for item in _list(experiment.get("conditions"), "manifest.experiment.conditions")
    )
    failure_taxonomy_present, failure_taxonomy_complete = _audit_failure_taxonomy(
        report,
        expected_conditions,
    )
    token_telemetry_present, token_telemetry_complete = _audit_token_telemetry(
        report,
        expected_conditions,
    )
    trajectory_artifacts_present, trajectory_artifacts_complete = _audit_trajectory_artifacts(
        report,
        expected_conditions,
    )
    verifier_artifacts_present, verifier_artifacts_complete = _audit_verifier_artifacts(
        report,
        expected_conditions,
    )

    missing: list[str] = []
    mismatched: list[str] = []
    reasons: list[str] = []
    if report_audit_status is None:
        missing.append("report.audit_status")
    elif report_audit_status != manifest_audit_status:
        mismatched.append("report.audit_status")
    if report_code_sha is None:
        missing.append("report.code_sha")
    elif report_code_sha != expected_code_sha:
        mismatched.append("report.code_sha")
    if code_sha_under_test is None or code_sha_under_test == "unknown":
        missing.append("report.code_sha_under_test")
    if leakage_notes is None:
        missing.append("manifest.leakage_notes")
    if report_leakage_notes is None:
        missing.append("report.leakage_notes")
    elif leakage_notes is not None and report_leakage_notes != leakage_notes:
        mismatched.append("report.leakage_notes")
    environment_manifest_present = isinstance(report_environment, Mapping)
    environment_manifest_matches = False
    if not environment_manifest_present:
        missing.append("report.environment")
    else:
        expected_environment = _environment_dict(environment)
        actual_environment = _environment_dict(_mapping(report_environment, "report.environment"))
        environment_manifest_matches = actual_environment == expected_environment
        if not environment_manifest_matches:
            mismatched.append("report.environment")
    if not failure_taxonomy_present:
        missing.append("report.failure_taxonomy")
    elif not failure_taxonomy_complete:
        mismatched.append("report.failure_taxonomy")
    if not token_telemetry_present:
        missing.append("report.token_telemetry")
    elif not token_telemetry_complete:
        mismatched.append("report.token_telemetry")
    if not trajectory_artifacts_present:
        missing.append("report.trajectory_artifacts")
    elif not trajectory_artifacts_complete:
        mismatched.append("report.trajectory_artifacts")
    if not verifier_artifacts_present:
        missing.append("report.verifier_artifacts")
    elif not verifier_artifacts_complete:
        mismatched.append("report.verifier_artifacts")

    if missing:
        reasons.append("report missing leakage/reproducibility fields: " + ", ".join(missing))
    if mismatched:
        reasons.append("report metadata mismatch: " + ", ".join(mismatched))
    return ReportMetadataAudit(
        ready=not missing and not mismatched,
        manifest_audit_status=manifest_audit_status,
        report_audit_status=report_audit_status,
        expected_code_sha=expected_code_sha,
        report_code_sha=report_code_sha,
        code_sha_under_test=code_sha_under_test,
        environment_manifest_present=environment_manifest_present,
        environment_manifest_matches=environment_manifest_matches,
        failure_taxonomy_present=failure_taxonomy_present,
        failure_taxonomy_complete=failure_taxonomy_complete,
        token_telemetry_present=token_telemetry_present,
        token_telemetry_complete=token_telemetry_complete,
        trajectory_artifacts_present=trajectory_artifacts_present,
        trajectory_artifacts_complete=trajectory_artifacts_complete,
        verifier_artifacts_present=verifier_artifacts_present,
        verifier_artifacts_complete=verifier_artifacts_complete,
        leakage_notes_present=leakage_notes is not None,
        report_leakage_notes_present=report_leakage_notes is not None,
        missing_fields=tuple(missing),
        mismatched_fields=tuple(mismatched),
        reasons=tuple(reasons),
    )


def _environment_dict(value: Mapping[str, object]) -> dict[str, str]:
    required = ("code_sha", "config_hash", "model", "provider", "image")
    return {key: _string(value.get(key), f"environment.{key}") for key in required}


def _audit_failure_taxonomy(
    report: Mapping[str, object],
    expected_conditions: Sequence[str],
) -> tuple[bool, bool]:
    raw = report.get("failure_taxonomy")
    if not isinstance(raw, Mapping):
        return False, False
    by_condition = raw.get("by_condition")
    overall = raw.get("overall")
    if not isinstance(by_condition, Mapping) or not isinstance(overall, Mapping):
        return True, False
    if not _taxonomy_counts(overall):
        return True, False
    for condition in expected_conditions:
        item = by_condition.get(condition)
        if not isinstance(item, Mapping) or not _taxonomy_counts(item):
            return True, False
    return True, True


def _audit_token_telemetry(
    report: Mapping[str, object],
    expected_conditions: Sequence[str],
) -> tuple[bool, bool]:
    raw = report.get("token_telemetry")
    if not isinstance(raw, Mapping):
        return False, False
    by_condition = raw.get("by_condition")
    overall = raw.get("overall")
    if not isinstance(by_condition, Mapping) or not isinstance(overall, Mapping):
        return True, False
    if not _token_counts(overall):
        return True, False
    for condition in expected_conditions:
        item = by_condition.get(condition)
        if not isinstance(item, Mapping) or not _token_counts(item):
            return True, False
    return True, True


def _audit_verifier_artifacts(
    report: Mapping[str, object],
    expected_conditions: Sequence[str],
) -> tuple[bool, bool]:
    raw = report.get("verifier_artifacts")
    if not isinstance(raw, Mapping):
        return False, False
    by_condition = raw.get("by_condition")
    overall = raw.get("overall")
    if not isinstance(by_condition, Mapping) or not isinstance(overall, Mapping):
        return True, False
    if not _verifier_artifact_counts(overall):
        return True, False
    for condition in expected_conditions:
        item = by_condition.get(condition)
        if not isinstance(item, Mapping) or not _verifier_artifact_counts(item):
            return True, False
    return True, True


def _audit_trajectory_artifacts(
    report: Mapping[str, object],
    expected_conditions: Sequence[str],
) -> tuple[bool, bool]:
    raw = report.get("trajectory_artifacts")
    if not isinstance(raw, Mapping):
        return False, False
    by_condition = raw.get("by_condition")
    overall = raw.get("overall")
    if not isinstance(by_condition, Mapping) or not isinstance(overall, Mapping):
        return True, False
    if not _trajectory_artifact_counts(overall):
        return True, False
    for condition in expected_conditions:
        item = by_condition.get(condition)
        if not isinstance(item, Mapping) or not _trajectory_artifact_counts(item):
            return True, False
    return True, True


def _trajectory_artifact_counts(value: Mapping[object, object]) -> bool:
    required = (
        "cells",
        "usable_cells",
        "artifact_cells",
        "missing_artifacts",
        "unique_trajectory_hashes",
    )
    if not all(_non_negative_int(value.get(key)) for key in required):
        return False
    usable_cells = value["usable_cells"]
    artifact_cells = value["artifact_cells"]
    missing_artifacts = value["missing_artifacts"]
    if not (
        isinstance(usable_cells, int)
        and isinstance(artifact_cells, int)
        and isinstance(missing_artifacts, int)
    ):
        return False
    if artifact_cells > usable_cells:
        return False
    if missing_artifacts != usable_cells - artifact_cells:
        return False
    if missing_artifacts != 0:
        return False
    hashes = value.get("trajectory_hashes", [])
    if not isinstance(hashes, list):
        return False
    return all(isinstance(item, str) and item for item in hashes)


def _verifier_artifact_counts(value: Mapping[object, object]) -> bool:
    required = (
        "cells",
        "usable_cells",
        "artifact_cells",
        "missing_artifacts",
        "unique_output_hashes",
    )
    if not all(_non_negative_int(value.get(key)) for key in required):
        return False
    usable_cells = value["usable_cells"]
    artifact_cells = value["artifact_cells"]
    missing_artifacts = value["missing_artifacts"]
    if not (
        isinstance(usable_cells, int)
        and isinstance(artifact_cells, int)
        and isinstance(missing_artifacts, int)
    ):
        return False
    if artifact_cells > usable_cells:
        return False
    if missing_artifacts != usable_cells - artifact_cells:
        return False
    if missing_artifacts != 0:
        return False
    hashes = value.get("output_hashes", [])
    if not isinstance(hashes, list):
        return False
    return all(isinstance(item, str) and item for item in hashes)


def _token_counts(value: Mapping[object, object]) -> bool:
    required = ("cells", "reported_cells", "input_tokens", "output_tokens", "context_tokens")
    return all(_non_negative_int(value.get(key)) for key in required)


def _taxonomy_counts(value: Mapping[object, object]) -> bool:
    return all(isinstance(key, str) and _non_negative_int(count) for key, count in value.items())


def _non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def calibrate_records(
    records: Sequence[Mapping[str, object]],
    *,
    conditions: Sequence[str | Condition],
    min_discriminative_tasks: int = 10,
    min_pass_delta: float = 0.05,
) -> CalibrationReport:
    """Return claim gates for raw trial records.

    A task is discriminative only when at least two conditions have usable cells
    and the max pass-rate spread is at least ``min_pass_delta``. Tasks that every
    condition solves or every condition fails are saturated and cannot support an
    improvement claim.
    """
    if min_discriminative_tasks < 1:
        raise ValueError("min_discriminative_tasks must be positive")
    if min_pass_delta < 0:
        raise ValueError("min_pass_delta must be non-negative")
    condition_values = tuple(_condition_value(item) for item in conditions)
    if len(condition_values) < 2 or len(set(condition_values)) != len(condition_values):
        raise ValueError("at least two distinct conditions are required")

    rows = [_normalize_record(record) for record in records]
    tasks = tuple(
        _calibrate_task(task_id, rows, condition_values, min_pass_delta)
        for task_id in sorted({row.task_id for row in rows})
    )
    discriminative_tasks = sum(1 for task in tasks if task.discriminative)
    saturated_tasks = sum(1 for task in tasks if task.saturated)
    incomplete_cost_conditions = _incomplete_cost_conditions(rows, condition_values)
    incomplete_cell_count = sum(1 for row in rows if row.infra_error is not None)
    quality_ready = discriminative_tasks >= min_discriminative_tasks and incomplete_cell_count == 0
    cost_ready = quality_ready and not incomplete_cost_conditions
    reasons: list[str] = []
    if discriminative_tasks < min_discriminative_tasks:
        reasons.append(
            f"only {discriminative_tasks} discriminative task(s); "
            f"requires {min_discriminative_tasks}"
        )
    if saturated_tasks:
        reasons.append(f"{saturated_tasks} task(s) saturated across conditions")
    if incomplete_cell_count:
        reasons.append(
            f"{incomplete_cell_count} cell(s) were incomplete or infrastructure failures"
        )
    if incomplete_cost_conditions:
        reasons.append(
            "cost telemetry incomplete for: " + ", ".join(incomplete_cost_conditions)
        )
    decision = (
        CalibrationDecision.READY
        if quality_ready
        else CalibrationDecision.INCOMPLETE
        if incomplete_cell_count
        else CalibrationDecision.NEEDS_DISCRIMINATION
    )
    return CalibrationReport(
        decision=decision,
        total_tasks=len(tasks),
        discriminative_tasks=discriminative_tasks,
        saturated_tasks=saturated_tasks,
        incomplete_cost_conditions=incomplete_cost_conditions,
        incomplete_cell_count=incomplete_cell_count,
        min_discriminative_tasks=min_discriminative_tasks,
        min_pass_delta=min_pass_delta,
        quality_claim_ready=quality_ready,
        cost_claim_ready=cost_ready,
        reasons=tuple(reasons),
        tasks=tasks,
    )


def _condition_value(value: str | Condition | object) -> str:
    if isinstance(value, Condition):
        return value.value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("conditions must be non-empty strings")
    return value


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


def _optional_string(value: object, path: str) -> str | None:
    if value is None:
        return None
    return _string(value, path)


def _integer(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{path} must be an integer")
    return value


def _optional_integer(value: object, path: str) -> int | None:
    if value is None:
        return None
    return _integer(value, path)


def _task_id(value: object) -> str:
    task = _mapping(value, "manifest.tasks[]")
    return _string(task.get("task_id"), "manifest.tasks[].task_id")


def _reported_task_ids(report: Mapping[str, object]) -> set[str]:
    raw_records = report.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("report.records must be a list")
    task_ids: set[str] = set()
    for item in raw_records:
        record = _mapping(item, "report.records[]")
        task_ids.add(_string(record.get("task_id"), "report.records[].task_id"))
    return task_ids


def _normalize_record(record: Mapping[str, object]) -> _Record:
    task_id = record.get("task_id")
    condition = record.get("condition")
    passed = record.get("passed")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("record.task_id must be a non-empty string")
    if not isinstance(condition, str) or not condition.strip():
        raise ValueError("record.condition must be a non-empty string")
    if not isinstance(passed, bool):
        raise ValueError("record.passed must be a bool")
    infra_error = record.get("infra_error")
    if infra_error is not None and not isinstance(infra_error, str):
        raise ValueError("record.infra_error must be null or a string")
    cost_usd = record.get("cost_usd")
    if cost_usd is not None and (
        isinstance(cost_usd, bool) or not isinstance(cost_usd, (int, float)) or cost_usd < 0
    ):
        raise ValueError("record.cost_usd must be null or a non-negative number")
    return _Record(
        task_id=task_id,
        condition=condition,
        passed=passed,
        infra_error=infra_error,
        cost_usd=None if cost_usd is None else float(cost_usd),
    )


def _calibrate_task(
    task_id: str,
    rows: Sequence[_Record],
    conditions: Sequence[str],
    min_pass_delta: float,
) -> TaskCalibration:
    pass_rates: list[tuple[str, float]] = []
    usable_cells = 0
    for condition in conditions:
        usable = [
            row
            for row in rows
            if row.task_id == task_id
            and row.condition == condition
            and row.infra_error is None
        ]
        usable_cells += len(usable)
        if usable:
            pass_rates.append(
                (
                    condition,
                    mean([1.0 if row.passed else 0.0 for row in usable]),
                )
            )
    rates = [rate for _condition, rate in pass_rates]
    max_delta = max(rates) - min(rates) if len(rates) >= 2 else 0.0
    saturated = bool(rates) and all(rate == rates[0] for rate in rates)
    discriminative = len(rates) >= 2 and max_delta >= min_pass_delta
    return TaskCalibration(
        task_id=task_id,
        pass_rates=tuple(pass_rates),
        usable_cells=usable_cells,
        saturated=saturated,
        discriminative=discriminative,
        max_delta=max_delta,
    )


def _incomplete_cost_conditions(
    rows: Iterable[_Record],
    conditions: Sequence[str],
) -> tuple[str, ...]:
    incomplete: list[str] = []
    for condition in conditions:
        usable = [
            row
            for row in rows
            if row.condition == condition and row.infra_error is None
        ]
        if usable and any(row.cost_usd is None for row in usable):
            incomplete.append(condition)
    return tuple(incomplete)
