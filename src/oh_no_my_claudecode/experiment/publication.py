"""Deterministic, fail-closed publication tooling for external benchmark evidence.

This module composes the existing experiment power, coverage, calibration, and
claim gates. It never launches an agent, reads credentials, or contacts a
network service. Generating a report is intentionally separate from earning a
claim: incomplete evidence still produces a useful report whose verdict is
``publication_ready = false``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .calibration import calibrate_portfolio_report
from .claim import build_claim_readiness, gate_claim_language
from .coverage import gate_portfolio_coverage
from .portfolio import PortfolioManifest
from .power import plan_portfolio_manifest
from .reporting import external_report_coverage_manifest
from .verifier_calibration import calibrate_default_verifier

__all__ = [
    "BenchmarkManifestValidation",
    "build_publication_bundle",
    "index_raw_artifacts",
    "render_publication_markdown",
    "validate_benchmark_manifest",
]

_SCHEMA_VERSION = "onmc-publication-report/v1"
_ARTIFACT_INDEX_SCHEMA_VERSION = "onmc-raw-artifact-index/v1"
_REQUIRED_ARMS = frozenset(
    {
        "bare-agent",
        "context-only",
        "onmc-single-agent",
        "trajectory-routed",
        "selective-swarm",
    }
)


@dataclass(frozen=True, slots=True)
class BenchmarkManifestValidation:
    """Structural and publication-specific validation for a portfolio manifest."""

    structurally_valid: bool
    publication_ready: bool
    manifest_sha256: str
    task_count: int
    condition_count: int
    trials_per_cell: int
    repository_count: int
    errors: tuple[str, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "onmc-benchmark-manifest-validation/v1",
            "structurally_valid": self.structurally_valid,
            "publication_ready": self.publication_ready,
            "manifest_sha256": self.manifest_sha256,
            "task_count": self.task_count,
            "condition_count": self.condition_count,
            "trials_per_cell": self.trials_per_cell,
            "repository_count": self.repository_count,
            "errors": list(self.errors),
            "blockers": list(self.blockers),
        }


def validate_benchmark_manifest(
    manifest: Mapping[str, object],
) -> BenchmarkManifestValidation:
    """Validate the shipped portfolio contract plus the stricter U14 release gates."""

    digest = _canonical_digest(manifest)
    errors: list[str] = []
    try:
        PortfolioManifest.from_dict(manifest)
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(str(exc))

    experiment = _optional_mapping(manifest.get("experiment"))
    tasks = _optional_mapping_list(manifest.get("tasks"))
    publication = _optional_mapping(manifest.get("publication"))
    conditions = _string_list(experiment.get("conditions"))
    trials = _int_or_zero(experiment.get("trials"))
    repositories = {
        str(repo.get("name"))
        for task in tasks
        if (repo := _optional_mapping(task.get("repo"))) and _non_empty_string(repo.get("name"))
    }

    blockers: list[str] = []
    if errors:
        blockers.append("core portfolio manifest contract is invalid")
    if manifest.get("audit_status") != "valid" or experiment.get("audit_status") != "valid":
        blockers.append("manifest and experiment audit_status must both be valid")
    if not _non_empty_string(manifest.get("leakage_notes")):
        blockers.append("manifest leakage_notes must describe the corpus audit")
    if len(tasks) < 50:
        blockers.append(f"at least 50 discriminative tasks are required; found {len(tasks)}")
    if trials < 3:
        blockers.append(f"at least three trials per cell are required; found {trials}")

    benchmark_arms = set(_string_list(publication.get("benchmark_arms")))
    if not benchmark_arms:
        benchmark_arms = set(conditions)
    missing_arms = sorted(_REQUIRED_ARMS - benchmark_arms)
    if missing_arms:
        blockers.append(
            "five benchmark arms are required; missing " + ", ".join(missing_arms)
        )

    seeds = publication.get("seeds")
    unique_seeds = {
        seed
        for seed in seeds
        if isinstance(seed, int) and not isinstance(seed, bool)
    } if isinstance(seeds, list) else set()
    if len(unique_seeds) < 3:
        blockers.append("three seeds must be pre-registered in publication.seeds")

    configurations = _optional_mapping_list(
        publication.get("agent_model_configurations")
    )
    valid_configurations = [
        item
        for item in configurations
        if all(_non_empty_string(item.get(key)) for key in ("id", "agent", "model"))
    ]
    if len(valid_configurations) < 3:
        blockers.append(
            "three agent/model configurations must be pre-registered in "
            "publication.agent_model_configurations"
        )

    languages = set(_string_list(publication.get("languages")))
    if len(languages) < 2:
        blockers.append("multiple languages must be declared in publication.languages")
    if len(repositories) < 2:
        blockers.append("multiple pinned repositories are required")

    leakage_audit = _optional_mapping(publication.get("leakage_audit"))
    if not (
        leakage_audit.get("status") == "passed"
        and leakage_audit.get("hidden_material_exposed_to_agent") is False
        and _non_empty_string(leakage_audit.get("method"))
        and _non_empty_string(leakage_audit.get("auditor"))
    ):
        blockers.append(
            "publication.leakage_audit must record a passed independent audit "
            "with hidden material unavailable to the agent"
        )

    return BenchmarkManifestValidation(
        structurally_valid=not errors,
        publication_ready=not errors and not blockers,
        manifest_sha256=digest,
        task_count=len(tasks),
        condition_count=len(conditions),
        trials_per_cell=trials,
        repository_count=len(repositories),
        errors=tuple(errors),
        blockers=tuple(blockers),
    )


def build_publication_bundle(
    report: Mapping[str, object],
    manifest: Mapping[str, object],
    *,
    proposed_claim: str = (
        "ONMC improves coding-agent quality and lowers cost versus plain coding agents."
    ),
    artifact_root: Path | None = None,
) -> dict[str, object]:
    """Build a deterministic report bundle without weakening any evidence gate."""

    validation = validate_benchmark_manifest(manifest)
    cost_coverage = _cost_coverage(report)
    per_cell_cost = (
        _optional_number(cost_coverage["mean_cost_usd"])
        if cost_coverage["complete"] is True
        else None
    )
    budget_ceiling = _optional_number(report.get("budget_ceiling_usd"))
    benchmark_plan = plan_portfolio_manifest(
        manifest,
        per_cell_cost_usd=per_cell_cost,
        budget_ceiling_usd=budget_ceiling,
    )
    portfolio_coverage = gate_portfolio_coverage(manifest)
    calibration = calibrate_portfolio_report(manifest, report)
    report_coverage = external_report_coverage_manifest(report)
    verifier_calibration = calibrate_default_verifier()
    claim_readiness = build_claim_readiness(
        benchmark_plan=benchmark_plan.to_dict(),
        coverage_gate=portfolio_coverage.to_dict(),
        calibration_gate=calibration.to_dict(),
        report_coverage_gate=report_coverage.to_dict(),
        verifier_calibration_gate=verifier_calibration.to_dict(),
    )
    claim_language = gate_claim_language(
        proposed_claim,
        claim_readiness,
        report_coverage=report_coverage.to_dict(),
    )
    leakage_audit = _leakage_audit(manifest, report)
    artifacts = index_raw_artifacts(
        report,
        artifact_root=Path(".") if artifact_root is None else artifact_root,
    )
    publication_ready = (
        validation.publication_ready
        and claim_readiness.quality_claim_ready
        and report_coverage.claim_ready
        and leakage_audit["complete"] is True
        and artifacts["complete"] is True
    )

    return {
        "schema_version": _SCHEMA_VERSION,
        "publication_ready": publication_ready,
        "status": "publication-ready" if publication_ready else "not-publication-ready",
        "experiment_id": report.get("experiment_id"),
        "task_set_revision": report.get("task_set_revision"),
        "manifest_validation": validation.to_dict(),
        "benchmark_plan": benchmark_plan.to_dict(),
        "portfolio_coverage": portfolio_coverage.to_dict(),
        "calibration": calibration.to_dict(),
        "report_coverage": report_coverage.to_dict(),
        "verifier_calibration": verifier_calibration.to_dict(),
        "claim_readiness": claim_readiness.to_dict(),
        "claim_language_gate": claim_language.to_dict(),
        "conditions": _json_value(report.get("conditions", [])),
        "summary": _json_value(report.get("summary", {})),
        "paired": _json_value(report.get("paired", {})),
        "cost_coverage": cost_coverage,
        "leakage_audit": leakage_audit,
        "failure_taxonomy": _json_value(report.get("failure_taxonomy", {})),
        "raw_artifact_index": artifacts,
    }


def index_raw_artifacts(
    report: Mapping[str, object],
    *,
    artifact_root: Path,
) -> dict[str, object]:
    """Index and hash per-cell trajectory/verifier files, failing closed on gaps."""

    root = artifact_root.resolve()
    records = _optional_mapping_list(report.get("records"))
    artifacts: list[dict[str, object]] = []
    missing: list[str] = []
    usable_cells = 0
    indexed_cells = 0

    for record in records:
        if record.get("infra_error") is not None:
            continue
        usable_cells += 1
        cell = _cell_id(record)
        cell_complete = True
        for kind, key in (
            ("trajectory", "trajectory_path"),
            ("verifier", "verifier_path"),
        ):
            value = record.get(key)
            if not _non_empty_string(value):
                missing.append(f"{cell}: {key}")
                cell_complete = False
                continue
            path = (root / str(value)).resolve()
            try:
                path.relative_to(root)
            except ValueError:
                missing.append(f"{cell}: {key} escapes artifact root")
                cell_complete = False
                continue
            if not path.is_file():
                missing.append(f"{cell}: {key} not found")
                cell_complete = False
                continue
            data = path.read_bytes()
            artifacts.append(
                {
                    "cell": cell,
                    "kind": kind,
                    "path": path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                    "media_type": "application/json",
                }
            )
        if cell_complete:
            indexed_cells += 1

    artifacts.sort(key=lambda item: (str(item["cell"]), str(item["kind"])))
    missing.sort()
    return {
        "schema_version": _ARTIFACT_INDEX_SCHEMA_VERSION,
        "complete": usable_cells > 0 and indexed_cells == usable_cells and not missing,
        "artifact_root": artifact_root.as_posix(),
        "usable_cells": usable_cells,
        "indexed_cells": indexed_cells,
        "artifacts": artifacts,
        "missing": missing,
    }


def render_publication_markdown(bundle: Mapping[str, object]) -> str:
    """Render the publication bundle as a compact, deterministic evidence report."""

    ready = bundle.get("publication_ready") is True
    summary = _optional_mapping(bundle.get("summary"))
    paired = _optional_mapping(bundle.get("paired"))
    cost = _optional_mapping(bundle.get("cost_coverage"))
    leakage = _optional_mapping(bundle.get("leakage_audit"))
    claim = _optional_mapping(bundle.get("claim_language_gate"))
    validation = _optional_mapping(bundle.get("manifest_validation"))
    readiness = _optional_mapping(bundle.get("claim_readiness"))
    report_coverage = _optional_mapping(bundle.get("report_coverage"))

    lines = [
        "# ONMC External Benchmark Evidence Report",
        "",
        f"> **{'PUBLICATION-READY' if ready else 'NOT PUBLICATION-READY'}**",
        "",
        "This report is generated from committed evidence. A successful generation "
        "does not imply that an external performance claim passed.",
        "",
        "## Verdict",
        "",
        f"- experiment: `{bundle.get('experiment_id')}`",
        f"- task set: `{bundle.get('task_set_revision')}`",
        f"- publication ready: `{str(ready).lower()}`",
        f"- claim decision: `{claim.get('decision', 'unknown')}`",
        f"- safe statement: {claim.get('suggested_safe_claim', 'unavailable')}",
        "",
        "## Condition Results",
        "",
        "| Condition | Pass@1 | 95% CI | Mean latency (ms) | Mean cost (USD) | Cost cells |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for condition, values in sorted(summary.items()):
        item = _optional_mapping(values)
        ci = item.get("pass_at_1_ci95")
        lines.append(
            f"| {condition} | {_fmt(item.get('pass_at_1'))} | {_fmt_ci(ci)} | "
            f"{_fmt(item.get('mean_latency_ms'))} | {_fmt(item.get('mean_cost_usd'))} | "
            f"{item.get('cost_reported_cells', 'unknown')}/{item.get('usable', 'unknown')} |"
        )

    lines.extend(
        [
            "",
            "## Paired Delta",
            "",
            f"- baseline: `{paired.get('baseline', 'unknown')}`",
            f"- treatment: `{paired.get('treatment', 'unknown')}`",
            f"- paired tasks: `{paired.get('paired_tasks', 0)}`",
            f"- mean delta: `{_fmt(paired.get('mean_delta'))}`",
            f"- 95% CI: `{_fmt_ci(paired.get('delta_ci95'))}`",
            f"- significant: `{str(paired.get('significant', False)).lower()}`",
            "",
            "## Cost Coverage",
            "",
            f"- status: `{'COMPLETE' if cost.get('complete') is True else 'INCOMPLETE'}`",
            f"- reported usable cells: `{cost.get('reported_cells', 0)}/"
            f"{cost.get('usable_cells', 0)}`",
            f"- mean measured cell cost: `{_fmt(cost.get('mean_cost_usd'))}`",
            "",
            "Cost claims remain blocked whenever either arm has missing telemetry.",
            "",
            "## Leakage Audit",
            "",
            f"- status: `{'COMPLETE' if leakage.get('complete') is True else 'INCOMPLETE'}`",
            f"- manifest notes present: "
            f"`{str(leakage.get('manifest_notes_present', False)).lower()}`",
            f"- report notes present: "
            f"`{str(leakage.get('report_notes_present', False)).lower()}`",
            f"- notes match: `{str(leakage.get('notes_match', False)).lower()}`",
            f"- independent audit recorded: "
            f"`{str(leakage.get('independent_audit_recorded', False)).lower()}`",
            "",
            "## Raw Artifact Index",
            "",
        ]
    )
    artifacts = _optional_mapping(bundle.get("raw_artifact_index"))
    lines.extend(
        [
            f"- complete: `{str(artifacts.get('complete', False)).lower()}`",
            f"- indexed cells: `{artifacts.get('indexed_cells', 0)}/"
            f"{artifacts.get('usable_cells', 0)}`",
            f"- missing entries: `{len(_optional_list(artifacts.get('missing')))}`",
            "",
            "## Publication Blockers",
            "",
        ]
    )
    blockers = [
        str(item) for item in _optional_list(validation.get("blockers"))
    ]
    blockers.extend(str(item) for item in _optional_list(readiness.get("reasons")))
    fields = _optional_list(report_coverage.get("fields"))
    blockers.extend(
        f"report coverage missing {item.get('name')}: {item.get('reason')}"
        for value in fields
        if (item := _optional_mapping(value)) and item.get("covered") is False
    )
    blockers = list(dict.fromkeys(blockers))
    lines.extend(f"- {item}" for item in blockers or ["none"])
    lines.append("")
    return "\n".join(lines)


def _cost_coverage(report: Mapping[str, object]) -> dict[str, object]:
    records = _optional_mapping_list(report.get("records"))
    usable = [record for record in records if record.get("infra_error") is None]
    by_condition: dict[str, dict[str, int]] = {}
    costs: list[float] = []
    for record in usable:
        condition = str(record.get("condition", "unknown"))
        counts = by_condition.setdefault(condition, {"usable_cells": 0, "reported_cells": 0})
        counts["usable_cells"] += 1
        value = _optional_number(record.get("cost_usd"))
        if value is not None:
            counts["reported_cells"] += 1
            costs.append(value)
    complete = bool(usable) and len(costs) == len(usable)
    return {
        "complete": complete,
        "usable_cells": len(usable),
        "reported_cells": len(costs),
        "missing_cells": len(usable) - len(costs),
        "mean_cost_usd": round(sum(costs) / len(costs), 6) if costs else None,
        "by_condition": dict(sorted(by_condition.items())),
    }


def _leakage_audit(
    manifest: Mapping[str, object],
    report: Mapping[str, object],
) -> dict[str, object]:
    publication = _optional_mapping(manifest.get("publication"))
    audit = _optional_mapping(publication.get("leakage_audit"))
    manifest_notes = manifest.get("leakage_notes")
    report_notes = report.get("leakage_notes")
    manifest_present = _non_empty_string(manifest_notes)
    report_present = _non_empty_string(report_notes)
    notes_match = manifest_present and report_present and manifest_notes == report_notes
    independent = (
        audit.get("status") == "passed"
        and audit.get("hidden_material_exposed_to_agent") is False
        and _non_empty_string(audit.get("method"))
        and _non_empty_string(audit.get("auditor"))
    )
    return {
        "complete": bool(notes_match and independent),
        "manifest_notes_present": manifest_present,
        "report_notes_present": report_present,
        "notes_match": notes_match,
        "independent_audit_recorded": bool(independent),
        "hidden_material_exposed_to_agent": audit.get(
            "hidden_material_exposed_to_agent"
        ),
        "method": audit.get("method"),
        "auditor": audit.get("auditor"),
    }


def _cell_id(record: Mapping[str, object]) -> str:
    return (
        f"{record.get('task_id', 'unknown')}/"
        f"{record.get('condition', 'unknown')}/"
        f"trial-{record.get('trial', 'unknown')}"
    )


def _canonical_digest(value: Mapping[str, object]) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def _json_value(value: object) -> object:
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _optional_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_mapping_list(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _optional_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _int_or_zero(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _optional_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        return None
    return float(value)


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _fmt(value: object) -> str:
    number = _optional_number(value)
    return "unknown" if number is None else f"{number:.4f}"


def _fmt_ci(value: object) -> str:
    if not isinstance(value, list) or len(value) != 2:
        return "unknown"
    return f"[{_fmt(value[0])}, {_fmt(value[1])}]"
