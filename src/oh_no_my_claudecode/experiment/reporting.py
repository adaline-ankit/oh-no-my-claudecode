"""Coverage manifest for external benchmark report evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_SCHEMA_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ExternalReportCoverageField:
    """Coverage verdict for one external benchmark report requirement."""

    name: str
    covered: bool
    source: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "covered": self.covered,
            "source": self.source,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ExternalReportCoverageManifest:
    """Machine-readable R13 coverage for one saved external report."""

    fields: tuple[ExternalReportCoverageField, ...]
    schema_version: str = _SCHEMA_VERSION

    @property
    def covered_count(self) -> int:
        return sum(1 for field in self.fields if field.covered)

    @property
    def missing_count(self) -> int:
        return len(self.fields) - self.covered_count

    @property
    def claim_ready(self) -> bool:
        """True only when every report field needed for external claims is covered."""
        return self.missing_count == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "covered_count": self.covered_count,
            "missing_count": self.missing_count,
            "claim_ready": self.claim_ready,
            "fields": [field.to_dict() for field in self.fields],
        }


def external_report_coverage_manifest(
    report: Mapping[str, object],
) -> ExternalReportCoverageManifest:
    """Build an honest R13 coverage manifest for one saved external report."""

    has_records = _has_records(report)
    has_summary_pass = _summary_has(report, "pass_at_1")
    has_summary_pass_ci = _summary_has(report, "pass_at_1_ci95")
    has_summary_latency = _summary_has(report, "mean_latency_ms")
    has_record_latency = has_records and _records_have(report, "latency_ms")
    has_record_cost = has_records and _records_have(report, "cost_usd")
    has_cost = has_record_cost and all(
        _is_number(record.get("cost_usd"))
        for record in _record_mappings(report)
        if record.get("infra_error") is None
    )
    has_paired = _paired_complete(report)
    has_trajectory = _artifact_complete(report, "trajectory_artifacts", "trajectory_hashes")
    has_verifier = _artifact_complete(report, "verifier_artifacts", "output_hashes")
    has_tokens = _token_telemetry_complete(report)
    has_failure_taxonomy = _failure_taxonomy_complete(report)
    has_leakage = _is_non_empty_string(report.get("leakage_notes"))
    has_environment = isinstance(report.get("environment"), Mapping)

    fields = (
        ExternalReportCoverageField(
            "raw_trajectories",
            has_trajectory,
            "report.trajectory_artifacts",
            "raw trajectory artifacts are present for every usable cell"
            if has_trajectory
            else "raw trajectory artifacts are missing or incomplete",
        ),
        ExternalReportCoverageField(
            "verifier_artifacts",
            has_verifier,
            "report.verifier_artifacts",
            "verifier output artifacts are present for every usable cell"
            if has_verifier
            else "verifier output artifacts are missing or incomplete",
        ),
        ExternalReportCoverageField(
            "pass_rate",
            has_summary_pass,
            "report.summary.*.pass_at_1",
            "condition pass rates are present"
            if has_summary_pass
            else "condition pass rates are missing",
        ),
        ExternalReportCoverageField(
            "pass_at_k",
            has_summary_pass,
            "report.summary.*.pass_at_1",
            "pass@1 is present as the report's pass@k statistic"
            if has_summary_pass
            else "pass@k/pass@1 is missing",
        ),
        ExternalReportCoverageField(
            "paired_deltas",
            has_paired,
            "report.paired",
            "paired deltas and confidence interval are present"
            if has_paired
            else "paired deltas or confidence interval are missing",
        ),
        ExternalReportCoverageField(
            "uncertainty",
            has_summary_pass_ci and has_paired,
            "report.summary.*.pass_at_1_ci95 + report.paired.delta_ci95",
            "condition and paired confidence intervals are present"
            if has_summary_pass_ci and has_paired
            else "condition or paired confidence intervals are missing",
        ),
        ExternalReportCoverageField(
            "latency",
            has_summary_latency and has_record_latency,
            "report.records[].latency_ms + report.summary.*.mean_latency_ms",
            "per-cell and aggregate latency are present"
            if has_summary_latency and has_record_latency
            else "per-cell or aggregate latency is missing",
        ),
        ExternalReportCoverageField(
            "token_use",
            has_tokens,
            "report.token_telemetry",
            "token telemetry is present and complete"
            if has_tokens
            else "token telemetry is missing or incomplete",
        ),
        ExternalReportCoverageField(
            "cost_coverage",
            has_cost,
            "report.records[].cost_usd",
            "all usable cells have measured cost"
            if has_cost
            else "one or more usable cells lack measured cost",
        ),
        ExternalReportCoverageField(
            "failure_taxonomy",
            has_failure_taxonomy,
            "report.failure_taxonomy",
            "failure taxonomy is present and complete"
            if has_failure_taxonomy
            else "failure taxonomy is missing or incomplete",
        ),
        ExternalReportCoverageField(
            "leakage_audit",
            has_leakage,
            "report.leakage_notes",
            "leakage notes are present"
            if has_leakage
            else "leakage notes are missing",
        ),
        ExternalReportCoverageField(
            "environment_manifest",
            has_environment,
            "report.environment",
            "environment manifest is present"
            if has_environment
            else "environment manifest is missing",
        ),
    )
    return ExternalReportCoverageManifest(fields=fields)


def _has_records(report: Mapping[str, object]) -> bool:
    records = report.get("records")
    return isinstance(records, list) and bool(records) and all(
        isinstance(record, Mapping) for record in records
    )


def _record_mappings(report: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    records = report.get("records")
    if not isinstance(records, list):
        return ()
    return tuple(record for record in records if isinstance(record, Mapping))


def _records_have(report: Mapping[str, object], key: str) -> bool:
    records = _record_mappings(report)
    return bool(records) and all(key in record for record in records)


def _summary_has(report: Mapping[str, object], key: str) -> bool:
    summary = report.get("summary")
    if not isinstance(summary, Mapping) or not summary:
        return False
    return all(isinstance(item, Mapping) and key in item for item in summary.values())


def _paired_complete(report: Mapping[str, object]) -> bool:
    paired = report.get("paired")
    if not isinstance(paired, Mapping):
        return False
    return (
        _positive_int(paired.get("paired_tasks"))
        and _is_number(paired.get("mean_delta"))
        and _ci(paired.get("delta_ci95"))
        and isinstance(paired.get("per_task_delta"), Mapping)
    )


def _artifact_complete(report: Mapping[str, object], key: str, hash_key: str) -> bool:
    raw = report.get(key)
    if not isinstance(raw, Mapping):
        return False
    overall = raw.get("overall")
    by_condition = raw.get("by_condition")
    if not isinstance(overall, Mapping) or not isinstance(by_condition, Mapping):
        return False
    return _artifact_counts_complete(overall, hash_key) and all(
        isinstance(item, Mapping) and _artifact_counts_complete(item, hash_key)
        for item in by_condition.values()
    )


def _artifact_counts_complete(value: Mapping[object, object], hash_key: str) -> bool:
    usable = value.get("usable_cells")
    artifact = value.get("artifact_cells")
    missing = value.get("missing_artifacts")
    hashes = value.get(hash_key)
    return (
        _non_negative_int(usable)
        and _non_negative_int(artifact)
        and _non_negative_int(missing)
        and isinstance(usable, int)
        and isinstance(artifact, int)
        and isinstance(missing, int)
        and artifact <= usable
        and missing == usable - artifact
        and missing == 0
        and isinstance(hashes, list)
        and all(isinstance(item, str) and item for item in hashes)
    )


def _token_telemetry_complete(report: Mapping[str, object]) -> bool:
    raw = report.get("token_telemetry")
    if not isinstance(raw, Mapping):
        return False
    overall = raw.get("overall")
    by_condition = raw.get("by_condition")
    if not isinstance(overall, Mapping) or not isinstance(by_condition, Mapping):
        return False
    return _token_counts_complete(overall) and all(
        isinstance(item, Mapping) and _token_counts_complete(item)
        for item in by_condition.values()
    )


def _token_counts_complete(value: Mapping[object, object]) -> bool:
    required = ("cells", "reported_cells", "input_tokens", "output_tokens", "context_tokens")
    return all(_non_negative_int(value.get(key)) for key in required)


def _failure_taxonomy_complete(report: Mapping[str, object]) -> bool:
    raw = report.get("failure_taxonomy")
    if not isinstance(raw, Mapping):
        return False
    overall = raw.get("overall")
    by_condition = raw.get("by_condition")
    if not isinstance(overall, Mapping) or not isinstance(by_condition, Mapping):
        return False
    return _taxonomy_counts(overall) and all(
        isinstance(item, Mapping) and _taxonomy_counts(item)
        for item in by_condition.values()
    )


def _taxonomy_counts(value: Mapping[object, object]) -> bool:
    return all(isinstance(key, str) and _non_negative_int(count) for key, count in value.items())


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _ci(value: object) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(_is_number(item) for item in value)


__all__ = [
    "ExternalReportCoverageField",
    "ExternalReportCoverageManifest",
    "external_report_coverage_manifest",
]
