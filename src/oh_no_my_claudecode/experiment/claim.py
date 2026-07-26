"""Unified external-claim readiness for ONMC benchmark evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "ClaimLanguageDecision",
    "ClaimLanguageGate",
    "ClaimReadinessDecision",
    "ClaimReadinessReport",
    "build_claim_readiness",
    "gate_claim_language",
]


class ClaimReadinessDecision(StrEnum):
    """Top-level benchmark claim verdict."""

    READY = "ready"
    NOT_READY = "not-ready"


class ClaimLanguageDecision(StrEnum):
    """Whether a user-facing claim can be published from the available evidence."""

    ALLOW = "allow"
    REFUSE = "refuse"


@dataclass(frozen=True, slots=True)
class ClaimReadinessReport:
    """Single verdict over power, coverage, calibration, and cost gates."""

    decision: ClaimReadinessDecision
    quality_claim_ready: bool
    cost_claim_ready: bool
    benchmark_plan_ready: bool
    portfolio_coverage_ready: bool
    report_coverage_ready: bool
    calibration_ready: bool
    cost_calibration_ready: bool
    blocked_gates: tuple[str, ...]
    reasons: tuple[str, ...]
    next_actions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.value,
            "quality_claim_ready": self.quality_claim_ready,
            "cost_claim_ready": self.cost_claim_ready,
            "benchmark_plan_ready": self.benchmark_plan_ready,
            "portfolio_coverage_ready": self.portfolio_coverage_ready,
            "report_coverage_ready": self.report_coverage_ready,
            "calibration_ready": self.calibration_ready,
            "cost_calibration_ready": self.cost_calibration_ready,
            "blocked_gates": list(self.blocked_gates),
            "reasons": list(self.reasons),
            "next_actions": list(self.next_actions),
        }


@dataclass(frozen=True, slots=True)
class ClaimLanguageGate:
    """Verdict for one proposed external-facing claim string."""

    decision: ClaimLanguageDecision
    claim_text: str
    detected_claims: tuple[str, ...]
    reasons: tuple[str, ...]
    suggested_safe_claim: str

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.value,
            "claim_text": self.claim_text,
            "detected_claims": list(self.detected_claims),
            "reasons": list(self.reasons),
            "suggested_safe_claim": self.suggested_safe_claim,
        }


def build_claim_readiness(
    *,
    benchmark_plan: Mapping[str, object],
    calibration_gate: Mapping[str, object],
    coverage_gate: Mapping[str, object] | None = None,
    report_coverage_gate: Mapping[str, object] | None = None,
) -> ClaimReadinessReport:
    """Combine separate benchmark gates into one externally-citable verdict."""
    benchmark_ready = _bool(benchmark_plan.get("claim_ready"), "benchmark_plan.claim_ready")
    coverage_ready = (
        False
        if coverage_gate is None
        else _bool(coverage_gate.get("claim_ready"), "coverage_gate.claim_ready")
    )
    calibration_ready = _bool(
        calibration_gate.get("quality_claim_ready"),
        "calibration_gate.quality_claim_ready",
    )
    report_coverage_ready = (
        True
        if report_coverage_gate is None
        else _bool(
            report_coverage_gate.get("claim_ready"),
            "report_coverage_gate.claim_ready",
        )
    )
    cost_ready = _bool(
        calibration_gate.get("cost_claim_ready"),
        "calibration_gate.cost_claim_ready",
    )
    quality_claim_ready = (
        benchmark_ready and coverage_ready and calibration_ready and report_coverage_ready
    )
    cost_claim_ready = quality_claim_ready and cost_ready

    blocked: list[str] = []
    reasons: list[str] = []
    next_actions: list[str] = []

    if not benchmark_ready:
        blocked.append("benchmark_plan")
        _extend_reasons(reasons, benchmark_plan.get("reasons"))
        _append_benchmark_next_action(next_actions, benchmark_plan)
    if coverage_gate is None:
        blocked.append("portfolio_coverage")
        reasons.append("manifest missing; portfolio coverage cannot be checked")
        next_actions.append("Provide a frozen portfolio manifest for external-claim gating.")
    elif not coverage_ready:
        blocked.append("portfolio_coverage")
        _extend_reasons(reasons, coverage_gate.get("reasons"))
        next_actions.append(
            "Rebalance the portfolio so required task kinds, repo spread, metadata, "
            "and dominance thresholds pass."
        )
    if not calibration_ready:
        blocked.append("calibration")
        _extend_reasons(reasons, calibration_gate.get("reasons"))
        next_actions.append(
            "Run a fresh, complete, discriminative benchmark report against the current manifest."
        )
    if report_coverage_gate is not None and not report_coverage_ready:
        blocked.append("report_coverage")
        _extend_report_coverage_reasons(reasons, report_coverage_gate)
        next_actions.append(
            "Capture complete report evidence for missing R13 fields before publishing "
            "external claims."
        )
    if calibration_ready and not cost_ready:
        blocked.append("cost_calibration")
        _extend_reasons(reasons, calibration_gate.get("reasons"))
        next_actions.append("Capture complete per-cell cost telemetry for every condition.")

    decision = (
        ClaimReadinessDecision.READY
        if quality_claim_ready and cost_claim_ready
        else ClaimReadinessDecision.NOT_READY
    )
    return ClaimReadinessReport(
        decision=decision,
        quality_claim_ready=quality_claim_ready,
        cost_claim_ready=cost_claim_ready,
        benchmark_plan_ready=benchmark_ready,
        portfolio_coverage_ready=coverage_ready,
        report_coverage_ready=report_coverage_ready,
        calibration_ready=calibration_ready,
        cost_calibration_ready=cost_ready,
        blocked_gates=tuple(dict.fromkeys(blocked)),
        reasons=tuple(dict.fromkeys(reasons)),
        next_actions=tuple(dict.fromkeys(next_actions)),
    )


def gate_claim_language(
    claim_text: str,
    readiness: ClaimReadinessReport | Mapping[str, object],
    *,
    report_coverage: Mapping[str, object] | None = None,
) -> ClaimLanguageGate:
    """Refuse strong marketing claims when the evidence contract is incomplete."""
    text = claim_text.strip()
    if not text:
        raise ValueError("claim_text must not be empty")

    data = readiness.to_dict() if isinstance(readiness, ClaimReadinessReport) else readiness
    detected = _detect_claim_kinds(text)
    reasons: list[str] = []

    quality_ready = _bool(data.get("quality_claim_ready"), "readiness.quality_claim_ready")
    cost_ready = _bool(data.get("cost_claim_ready"), "readiness.cost_claim_ready")
    decision_ready = data.get("decision") == ClaimReadinessDecision.READY.value
    report_ready = _report_coverage_ready(report_coverage)

    if "quality" in detected and not quality_ready:
        reasons.append("quality improvement claim lacks a ready matched benchmark gate")
    if "cost" in detected and not cost_ready:
        reasons.append("cost claim lacks complete cost telemetry and cost gate readiness")
    if "sota" in detected and not decision_ready:
        reasons.append("SOTA claim requires every external benchmark readiness gate to pass")
    if detected and report_coverage is not None and not report_ready:
        reasons.append("receipt/report coverage is incomplete for external claims")

    decision = ClaimLanguageDecision.REFUSE if reasons else ClaimLanguageDecision.ALLOW
    return ClaimLanguageGate(
        decision=decision,
        claim_text=text,
        detected_claims=detected,
        reasons=tuple(dict.fromkeys(reasons)),
        suggested_safe_claim=_safe_claim(data, report_coverage=report_coverage),
    )


def _append_benchmark_next_action(
    next_actions: list[str],
    benchmark_plan: Mapping[str, object],
) -> None:
    task_count = _optional_int(benchmark_plan.get("task_count"))
    min_required = _optional_int(benchmark_plan.get("min_tasks_required"))
    if task_count is not None and min_required is not None and task_count < min_required:
        next_actions.append(
            f"Add at least {min_required - task_count} benchmark task(s) to reach "
            f"the {min_required}-task planning target."
        )
    if benchmark_plan.get("budget_ready") is False:
        next_actions.append(
            "Set an explicit per-cell cost estimate and budget ceiling that covers "
            "the claim-sized benchmark run."
        )


def _extend_reasons(dest: list[str], value: object) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        if isinstance(item, str) and item.strip():
            dest.append(item)


def _extend_report_coverage_reasons(
    dest: list[str],
    report_coverage_gate: Mapping[str, object],
) -> None:
    fields = report_coverage_gate.get("fields")
    if not isinstance(fields, list):
        dest.append("report coverage manifest is missing field-level evidence")
        return
    found_missing = False
    for item in fields:
        if not isinstance(item, Mapping):
            continue
        if item.get("covered") is not False:
            continue
        name = item.get("name")
        reason = item.get("reason")
        if isinstance(name, str) and name.strip() and isinstance(reason, str) and reason.strip():
            dest.append(f"report coverage missing {name}: {reason}")
            found_missing = True
    if not found_missing:
        dest.append("report coverage is incomplete")


def _bool(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{path} must be a bool")
    return value


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


_QUALITY_RE = re.compile(
    r"\b(better|improves?|improved|improvement|boosts?|higher pass|more reliable)\b",
    re.IGNORECASE,
)
_COST_RE = re.compile(
    r"\b(cheaper|saves?|saved|saving|cost reduction|lowers? cost|token reduction)\b",
    re.IGNORECASE,
)
_SOTA_RE = re.compile(r"\b(sota|state[- ]of[- ]the[- ]art|best[- ]in[- ]class)\b", re.IGNORECASE)


def _detect_claim_kinds(text: str) -> tuple[str, ...]:
    kinds: list[str] = []
    if _QUALITY_RE.search(text):
        kinds.append("quality")
    if _COST_RE.search(text):
        kinds.append("cost")
    if _SOTA_RE.search(text):
        kinds.append("sota")
    return tuple(kinds)


def _report_coverage_ready(report_coverage: Mapping[str, object] | None) -> bool:
    if report_coverage is None:
        return True
    return _bool(report_coverage.get("claim_ready"), "report_coverage.claim_ready")


def _safe_claim(
    readiness: Mapping[str, object],
    *,
    report_coverage: Mapping[str, object] | None,
) -> str:
    if readiness.get("decision") == ClaimReadinessDecision.READY.value and _report_coverage_ready(
        report_coverage
    ):
        return (
            "ONMC is ready for externally-citable quality and cost claims under "
            "the attached benchmark evidence."
        )
    blocked = readiness.get("blocked_gates")
    if isinstance(blocked, list) and blocked:
        return (
            "ONMC records harness evidence, but external improvement claims are blocked "
            f"until these gates pass: {', '.join(str(item) for item in blocked)}."
        )
    return (
        "ONMC records harness evidence for this run; broader improvement claims require "
        "matched external benchmarks with complete report coverage."
    )
