"""ONMC SOTA experiment/evidence layer — frozen shared contracts.

The experiment kernel, run envelope, and eval-gated learning all build on the
vocabulary defined in :mod:`oh_no_my_claudecode.experiment.contracts`.
"""

from __future__ import annotations

from .calibration import (
    CalibrationDecision,
    CalibrationReport,
    ManifestCalibrationReport,
    TaskCalibration,
    calibrate_external_report,
    calibrate_portfolio_report,
    calibrate_records,
)
from .claim import (
    ClaimLanguageDecision,
    ClaimLanguageGate,
    ClaimReadinessDecision,
    ClaimReadinessReport,
    build_claim_readiness,
    gate_claim_language,
)
from .contracts import (
    SCHEMA_VERSION,
    AdapterCapabilities,
    ArtifactRef,
    BenchmarkAuditStatus,
    CandidateState,
    Condition,
    Environment,
    ExperimentId,
    ExperimentManifest,
    MetricLabel,
    RunId,
    TrialResult,
    is_legal_transition,
    task_set_sha256,
)
from .coverage import (
    PortfolioCoverageGate,
    PortfolioExpansionPlan,
    gate_portfolio_coverage,
    plan_portfolio_expansion,
)
from .expansion import (
    DraftTaskSlot,
    PortfolioExpansionDraft,
    build_portfolio_expansion_draft,
)
from .power import BenchmarkPowerPlan, plan_external_report, plan_portfolio_manifest
from .reporting import (
    ExternalReportCoverageField,
    ExternalReportCoverageManifest,
    external_report_coverage_manifest,
)
from .routing import (
    RoutingArm,
    RoutingEvaluation,
    RoutingTrial,
    evaluate_routing,
)

__all__ = [
    "SCHEMA_VERSION",
    "AdapterCapabilities",
    "ArtifactRef",
    "BenchmarkAuditStatus",
    "CandidateState",
    "Condition",
    "Environment",
    "ExperimentId",
    "ExperimentManifest",
    "MetricLabel",
    "RunId",
    "TrialResult",
    "task_set_sha256",
    "CalibrationDecision",
    "CalibrationReport",
    "ManifestCalibrationReport",
    "TaskCalibration",
    "BenchmarkPowerPlan",
    "ClaimLanguageDecision",
    "ClaimLanguageGate",
    "ClaimReadinessDecision",
    "ClaimReadinessReport",
    "PortfolioCoverageGate",
    "PortfolioExpansionPlan",
    "ExternalReportCoverageField",
    "ExternalReportCoverageManifest",
    "RoutingArm",
    "RoutingEvaluation",
    "RoutingTrial",
    "DraftTaskSlot",
    "PortfolioExpansionDraft",
    "build_claim_readiness",
    "build_portfolio_expansion_draft",
    "calibrate_external_report",
    "calibrate_portfolio_report",
    "calibrate_records",
    "gate_portfolio_coverage",
    "gate_claim_language",
    "external_report_coverage_manifest",
    "evaluate_routing",
    "plan_portfolio_expansion",
    "plan_external_report",
    "plan_portfolio_manifest",
    "is_legal_transition",
]
