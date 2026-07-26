#!/usr/bin/env python
"""Offline calibration gate for ONMC external benchmark reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from oh_no_my_claudecode.experiment.calibration import (  # noqa: E402
    calibrate_external_report,
    calibrate_portfolio_report,
)
from oh_no_my_claudecode.experiment.claim import (  # noqa: E402
    build_claim_readiness,
    gate_claim_language,
)
from oh_no_my_claudecode.experiment.coverage import (  # noqa: E402
    gate_portfolio_coverage,
    plan_portfolio_expansion,
)
from oh_no_my_claudecode.experiment.expansion import (  # noqa: E402
    build_portfolio_expansion_draft,
)
from oh_no_my_claudecode.experiment.power import (  # noqa: E402
    plan_external_report,
    plan_portfolio_manifest,
)
from oh_no_my_claudecode.experiment.reporting import (  # noqa: E402
    external_report_coverage_manifest,
)
from oh_no_my_claudecode.experiment.verifier_calibration import (  # noqa: E402
    calibrate_default_verifier,
)

_DEFAULT_EXTERNAL_CLAIM = (
    "ONMC improves coding-agent quality and lowers cost versus plain Claude Code, "
    "Codex, and OpenCode."
)


def calibrate_report_file(
    report_path: Path,
    *,
    manifest_path: Path | None,
    min_discriminative_tasks: int,
    min_pass_delta: float,
    per_cell_cost_usd: float | None,
    budget_ceiling_usd: float | None,
    min_effect: float,
    assumed_task_delta_sd: float,
    min_tasks_floor: int,
    min_repos: int,
    min_task_kinds: int,
    max_kind_fraction: float,
    max_repo_fraction: float,
) -> dict[str, object]:
    """Return the calibration payload for one saved JSON report."""
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("report JSON root must be an object")
    payload: dict[str, object] = {
        "report_path": str(report_path),
        "experiment_id": raw.get("experiment_id"),
        "task_set_revision": raw.get("task_set_revision"),
        "task_set_sha256": raw.get("task_set_sha256"),
        "report_coverage": external_report_coverage_manifest(raw).to_dict(),
        "verifier_calibration": calibrate_default_verifier().to_dict(),
    }
    if manifest_path is not None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest JSON root must be an object")
        payload["manifest_path"] = str(manifest_path)
        payload["benchmark_plan"] = plan_portfolio_manifest(
            manifest,
            per_cell_cost_usd=per_cell_cost_usd,
            budget_ceiling_usd=budget_ceiling_usd,
            min_effect=min_effect,
            assumed_task_delta_sd=assumed_task_delta_sd,
            min_tasks_floor=min_tasks_floor,
        ).to_dict()
        payload["coverage_gate"] = gate_portfolio_coverage(
            manifest,
            min_repos=min_repos,
            min_task_kinds=min_task_kinds,
            max_kind_fraction=max_kind_fraction,
            max_repo_fraction=max_repo_fraction,
        ).to_dict()
        payload["portfolio_gap_plan"] = plan_portfolio_expansion(
            benchmark_plan=_mapping(payload["benchmark_plan"]),
            coverage_gate=_mapping(payload["coverage_gate"]),
        ).to_dict()
        payload["portfolio_expansion_draft"] = build_portfolio_expansion_draft(
            manifest=manifest,
            benchmark_plan=_mapping(payload["benchmark_plan"]),
            coverage_gate=_mapping(payload["coverage_gate"]),
        ).to_dict()
        payload["manifest_gate"] = calibrate_portfolio_report(
            manifest,
            raw,
            min_discriminative_tasks=min_discriminative_tasks,
            min_pass_delta=min_pass_delta,
        ).to_dict()
        payload["claim_readiness"] = build_claim_readiness(
            benchmark_plan=_mapping(payload["benchmark_plan"]),
            coverage_gate=_mapping(payload["coverage_gate"]),
            calibration_gate=_mapping(payload["manifest_gate"]),
            report_coverage_gate=_mapping(payload["report_coverage"]),
            verifier_calibration_gate=_mapping(payload["verifier_calibration"]),
        ).to_dict()
    else:
        payload["benchmark_plan"] = plan_external_report(
            raw,
            per_cell_cost_usd=per_cell_cost_usd,
            budget_ceiling_usd=budget_ceiling_usd,
            min_effect=min_effect,
            assumed_task_delta_sd=assumed_task_delta_sd,
            min_tasks_floor=min_tasks_floor,
        ).to_dict()
        calibration = calibrate_external_report(
            raw,
            min_discriminative_tasks=min_discriminative_tasks,
            min_pass_delta=min_pass_delta,
        )
        payload["calibration"] = calibration.to_dict()
        payload["claim_readiness"] = build_claim_readiness(
            benchmark_plan=_mapping(payload["benchmark_plan"]),
            calibration_gate=_mapping(payload["calibration"]),
            report_coverage_gate=_mapping(payload["report_coverage"]),
            verifier_calibration_gate=_mapping(payload["verifier_calibration"]),
        ).to_dict()
    payload["claim_language_gate"] = gate_claim_language(
        _DEFAULT_EXTERNAL_CLAIM,
        _mapping(payload["claim_readiness"]),
        report_coverage=_mapping(payload["report_coverage"]),
    ).to_dict()
    return payload


def _render_markdown(payload: dict[str, object]) -> str:
    gate = payload.get("manifest_gate")
    calibration = _mapping(gate if gate is not None else payload["calibration"])
    plan = _mapping(payload["benchmark_plan"])
    coverage = payload.get("coverage_gate")
    gap_plan = payload.get("portfolio_gap_plan")
    expansion_draft = payload.get("portfolio_expansion_draft")
    metadata_audit = calibration.get("metadata_audit")
    claim = _mapping(payload["claim_readiness"])
    reasons = calibration.get("reasons", [])
    plan_reasons = plan.get("reasons", [])
    claim_reasons = claim.get("reasons", [])
    next_actions = claim.get("next_actions", [])
    language_gate = _mapping(payload["claim_language_gate"])
    language_reasons = language_gate.get("reasons", [])
    report_coverage = _mapping(payload["report_coverage"])
    verifier_calibration = _mapping(payload["verifier_calibration"])
    lines = [
        "# ONMC External Report Calibration",
        "",
        f"- report: `{payload['report_path']}`",
        *([f"- manifest: `{payload['manifest_path']}`"] if "manifest_path" in payload else []),
        f"- experiment: `{payload.get('experiment_id')}`",
        f"- task_set_revision: `{payload.get('task_set_revision')}`",
        f"- task_set_sha256: `{payload.get('task_set_sha256')}`",
        f"- external_claim_decision: `{claim['decision']}`",
        f"- external_quality_claim_ready: `{str(claim['quality_claim_ready']).lower()}`",
        f"- external_cost_claim_ready: `{str(claim['cost_claim_ready']).lower()}`",
        f"- blocked_gates: `{claim['blocked_gates']}`",
        f"- claim_language_decision: `{language_gate['decision']}`",
        f"- report_coverage_claim_ready: `{str(report_coverage['claim_ready']).lower()}`",
        f"- verifier_calibration_claim_ready: `{str(verifier_calibration['claim_ready']).lower()}`",
        f"- decision: `{_decision(calibration)}`",
        f"- quality_claim_ready: `{str(calibration['quality_claim_ready']).lower()}`",
        f"- cost_claim_ready: `{str(calibration['cost_claim_ready']).lower()}`",
        f"- discriminative_tasks: `{_nested(calibration, 'discriminative_tasks')}`",
        f"- saturated_tasks: `{_nested(calibration, 'saturated_tasks')}`",
        f"- incomplete_cell_count: `{_nested(calibration, 'incomplete_cell_count')}`",
        *(
            [
                f"- manifest_task_set_sha256: `{calibration['manifest_task_set_sha256']}`",
                (
                    "- computed_manifest_task_set_sha256: "
                    f"`{calibration['computed_manifest_task_set_sha256']}`"
                ),
                f"- expected_cells: `{calibration['expected_cells']}`",
                f"- reported_cells: `{calibration['reported_cells']}`",
                f"- missing_cells: `{calibration['missing_cells']}`",
                f"- duplicate_cells: `{calibration['duplicate_cells']}`",
                f"- unexpected_cells: `{calibration['unexpected_cells']}`",
            ]
            if gate is not None
            else []
        ),
        "",
        "## Benchmark Plan",
        "",
        f"- claim_ready: `{str(plan['claim_ready']).lower()}`",
        f"- sample_size_ready: `{str(plan['sample_size_ready']).lower()}`",
        f"- budget_ready: `{str(plan['budget_ready']).lower()}`",
        f"- tasks: `{plan['task_count']}`",
        f"- total_cells: `{plan['total_cells']}`",
        f"- min_tasks_required: `{plan['min_tasks_required']}`",
        f"- min_total_cells_required: `{plan['min_total_cells_required']}`",
        f"- estimated_cost_usd: `{plan['estimated_cost_usd']}`",
        f"- estimated_required_cost_usd: `{plan['estimated_required_cost_usd']}`",
        "",
        "### Plan Reasons",
        "",
        *(
            [f"- {reason}" for reason in plan_reasons]
            if isinstance(plan_reasons, list) and plan_reasons
            else ["- none"]
        ),
        *(_coverage_markdown(_mapping(coverage)) if coverage is not None else []),
        *(_gap_plan_markdown(_mapping(gap_plan)) if gap_plan is not None else []),
        *(
            _expansion_draft_markdown(_mapping(expansion_draft))
            if expansion_draft is not None
            else []
        ),
        *(
            _metadata_audit_markdown(_mapping(metadata_audit))
            if metadata_audit is not None
            else []
        ),
        *_verifier_calibration_markdown(verifier_calibration),
        "",
        "## External Claim Readiness",
        "",
        f"- decision: `{claim['decision']}`",
        f"- quality_claim_ready: `{str(claim['quality_claim_ready']).lower()}`",
        f"- cost_claim_ready: `{str(claim['cost_claim_ready']).lower()}`",
        f"- blocked_gates: `{claim['blocked_gates']}`",
        "",
        "### Claim Reasons",
        "",
        *(
            [f"- {reason}" for reason in claim_reasons]
            if isinstance(claim_reasons, list) and claim_reasons
            else ["- none"]
        ),
        "",
        "### Next Actions",
        "",
        *(
            [f"- {action}" for action in next_actions]
            if isinstance(next_actions, list) and next_actions
            else ["- none"]
        ),
        "",
        "## Claim Language Gate",
        "",
        f"- decision: `{language_gate['decision']}`",
        f"- proposed_claim: {language_gate['claim_text']}",
        f"- detected_claims: `{language_gate['detected_claims']}`",
        f"- suggested_safe_claim: {language_gate['suggested_safe_claim']}",
        "",
        "### Claim Language Reasons",
        "",
        *(
            [f"- {reason}" for reason in language_reasons]
            if isinstance(language_reasons, list) and language_reasons
            else ["- none"]
        ),
        *(_report_coverage_markdown(report_coverage)),
        "",
        "## Reasons",
        "",
    ]
    if isinstance(reasons, list) and reasons:
        lines.extend(f"- {reason}" for reason in reasons)
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("expected an object")
    return value


def _decision(calibration: dict[str, Any]) -> object:
    if "decision" in calibration:
        return calibration["decision"]
    nested = _mapping(calibration["calibration"])
    return nested["decision"]


def _nested(calibration: dict[str, Any], key: str) -> object:
    if key in calibration:
        return calibration[key]
    nested = _mapping(calibration["calibration"])
    return nested[key]


def _coverage_markdown(coverage: dict[str, Any]) -> list[str]:
    reasons = coverage.get("reasons", [])
    return [
        "",
        "## Portfolio Coverage",
        "",
        f"- claim_ready: `{str(coverage['claim_ready']).lower()}`",
        f"- task_kind_coverage_ready: `{str(coverage['task_kind_coverage_ready']).lower()}`",
        f"- repo_coverage_ready: `{str(coverage['repo_coverage_ready']).lower()}`",
        f"- balance_ready: `{str(coverage['balance_ready']).lower()}`",
        f"- metadata_ready: `{str(coverage['metadata_ready']).lower()}`",
        f"- task_kind_counts: `{coverage['task_kind_counts']}`",
        f"- repo_counts: `{coverage['repo_counts']}`",
        "",
        "### Coverage Reasons",
        "",
        *(
            [f"- {reason}" for reason in reasons]
            if isinstance(reasons, list) and reasons
            else ["- none"]
        ),
    ]


def _gap_plan_markdown(gap_plan: dict[str, Any]) -> list[str]:
    return [
        "",
        "## Portfolio Gap Plan",
        "",
        f"- current_tasks: `{gap_plan['current_tasks']}`",
        f"- target_tasks: `{gap_plan['target_tasks']}`",
        f"- minimum_total_additions: `{gap_plan['minimum_total_additions']}`",
        f"- suggested_minimum_additions_by_kind: "
        f"`{gap_plan['suggested_minimum_additions_by_kind']}`",
        f"- unallocated_non_dominant_additions: "
        f"`{gap_plan['unallocated_non_dominant_additions']}`",
        f"- dominant_kind: `{gap_plan['dominant_kind']}`",
        f"- max_additional_dominant_kind_at_target: "
        f"`{gap_plan['max_additional_dominant_kind_at_target']}`",
        "",
        "### Gap Notes",
        "",
        *[f"- {note}" for note in _list_value(gap_plan.get("notes"))],
    ]


def _expansion_draft_markdown(draft: dict[str, Any]) -> list[str]:
    return [
        "",
        "## Portfolio Expansion Draft",
        "",
        f"- slot_count: `{draft['slot_count']}`",
        f"- slots_by_kind: `{draft['slots_by_kind']}`",
        f"- slots_by_repo: `{draft['slots_by_repo']}`",
        "",
        "### First Slots",
        "",
        *[
            "- "
            f"{slot['slot_id']} "
            f"kind={slot['task_kind']} "
            f"repo={slot['suggested_repo']} "
            f"required_by={slot['required_by']}"
            for slot in _list_value(draft.get("slots"))[:10]
            if isinstance(slot, dict)
        ],
    ]


def _metadata_audit_markdown(audit: dict[str, Any]) -> list[str]:
    return [
        "",
        "## Report Metadata Audit",
        "",
        f"- ready: `{str(audit['ready']).lower()}`",
        f"- manifest_audit_status: `{audit['manifest_audit_status']}`",
        f"- report_audit_status: `{audit['report_audit_status']}`",
        f"- expected_code_sha: `{audit['expected_code_sha']}`",
        f"- report_code_sha: `{audit['report_code_sha']}`",
        f"- code_sha_under_test: `{audit['code_sha_under_test']}`",
        f"- environment_manifest_present: "
        f"`{str(audit['environment_manifest_present']).lower()}`",
        f"- environment_manifest_matches: "
        f"`{str(audit['environment_manifest_matches']).lower()}`",
        f"- failure_taxonomy_present: "
        f"`{str(audit['failure_taxonomy_present']).lower()}`",
        f"- failure_taxonomy_complete: "
        f"`{str(audit['failure_taxonomy_complete']).lower()}`",
        f"- token_telemetry_present: "
        f"`{str(audit['token_telemetry_present']).lower()}`",
        f"- token_telemetry_complete: "
        f"`{str(audit['token_telemetry_complete']).lower()}`",
        f"- trajectory_artifacts_present: "
        f"`{str(audit['trajectory_artifacts_present']).lower()}`",
        f"- trajectory_artifacts_complete: "
        f"`{str(audit['trajectory_artifacts_complete']).lower()}`",
        f"- verifier_artifacts_present: "
        f"`{str(audit['verifier_artifacts_present']).lower()}`",
        f"- verifier_artifacts_complete: "
        f"`{str(audit['verifier_artifacts_complete']).lower()}`",
        f"- leakage_notes_present: `{str(audit['leakage_notes_present']).lower()}`",
        f"- report_leakage_notes_present: "
        f"`{str(audit['report_leakage_notes_present']).lower()}`",
        f"- missing_fields: `{audit['missing_fields']}`",
        f"- mismatched_fields: `{audit['mismatched_fields']}`",
    ]


def _report_coverage_markdown(coverage: dict[str, Any]) -> list[str]:
    fields = [
        item
        for item in _list_value(coverage.get("fields"))
        if isinstance(item, dict)
    ]
    missing = [
        str(item.get("name"))
        for item in fields
        if item.get("covered") is False and item.get("name")
    ]
    return [
        "",
        "## Report Coverage",
        "",
        f"- claim_ready: `{str(coverage['claim_ready']).lower()}`",
        f"- covered_count: `{coverage['covered_count']}`",
        f"- missing_count: `{coverage['missing_count']}`",
        f"- missing_fields: `{missing}`",
        "",
        "### Report Coverage Fields",
        "",
        *[
            "- "
            f"{item['name']}: "
            f"{'covered' if item['covered'] else 'missing'} "
            f"({item['reason']})"
            for item in fields
        ],
    ]


def _verifier_calibration_markdown(calibration: dict[str, Any]) -> list[str]:
    reasons = calibration.get("reasons", [])
    return [
        "",
        "## Verifier Calibration",
        "",
        f"- claim_ready: `{str(calibration['claim_ready']).lower()}`",
        f"- sensitivity: `{calibration['sensitivity']}`",
        f"- specificity: `{calibration['specificity']}`",
        f"- false_green_cases: `{calibration['false_green_cases']}`",
        f"- legitimate_cases: `{calibration['legitimate_cases']}`",
        f"- caught_false_green: `{calibration['caught_false_green']}`",
        f"- missed_false_green: `{calibration['missed_false_green']}`",
        f"- cleared_legitimate: `{calibration['cleared_legitimate']}`",
        f"- false_positive_legitimate: `{calibration['false_positive_legitimate']}`",
        "",
        "### Verifier Calibration Reasons",
        "",
        *(
            [f"- {reason}" for reason in reasons]
            if isinstance(reasons, list) and reasons
            else ["- none"]
        ),
    ]


def _list_value(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Saved JSON report to calibrate.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Optional frozen portfolio manifest to gate the report against.",
    )
    parser.add_argument("--out", type=Path, default=None, help="Write calibration JSON here.")
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Print a compact markdown summary instead of JSON.",
    )
    parser.add_argument("--min-discriminative-tasks", type=int, default=10)
    parser.add_argument("--min-pass-delta", type=float, default=0.05)
    parser.add_argument(
        "--per-cell-cost-usd",
        type=float,
        default=None,
        help=(
            "Expected cost per benchmark cell. If omitted for a completed report, "
            "the script estimates it from measured cell costs."
        ),
    )
    parser.add_argument(
        "--budget-ceiling-usd",
        type=float,
        default=None,
        help=(
            "Maximum approved spend for the planned run. If omitted for a completed "
            "report, report.budget_ceiling_usd is used when present."
        ),
    )
    parser.add_argument("--min-effect", type=float, default=0.15)
    parser.add_argument("--assumed-task-delta-sd", type=float, default=0.35)
    parser.add_argument("--min-tasks-floor", type=int, default=50)
    parser.add_argument("--min-repos", type=int, default=5)
    parser.add_argument("--min-task-kinds", type=int, default=4)
    parser.add_argument("--max-kind-fraction", type=float, default=0.60)
    parser.add_argument("--max-repo-fraction", type=float, default=0.40)
    args = parser.parse_args(argv)

    payload = calibrate_report_file(
        args.report,
        manifest_path=args.manifest,
        min_discriminative_tasks=args.min_discriminative_tasks,
        min_pass_delta=args.min_pass_delta,
        per_cell_cost_usd=args.per_cell_cost_usd,
        budget_ceiling_usd=args.budget_ceiling_usd,
        min_effect=args.min_effect,
        assumed_task_delta_sd=args.assumed_task_delta_sd,
        min_tasks_floor=args.min_tasks_floor,
        min_repos=args.min_repos,
        min_task_kinds=args.min_task_kinds,
        max_kind_fraction=args.max_kind_fraction,
        max_repo_fraction=args.max_repo_fraction,
    )
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    output = (
        _render_markdown(payload)
        if args.markdown
        else json.dumps(payload, indent=2, sort_keys=True)
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
