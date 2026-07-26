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
from .claim import ClaimReadinessDecision, ClaimReadinessReport, build_claim_readiness
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
    "CalibrationDecision",
    "CalibrationReport",
    "ManifestCalibrationReport",
    "TaskCalibration",
    "BenchmarkPowerPlan",
    "ClaimReadinessDecision",
    "ClaimReadinessReport",
    "PortfolioCoverageGate",
    "PortfolioExpansionPlan",
    "ExternalReportCoverageField",
    "ExternalReportCoverageManifest",
    "DraftTaskSlot",
    "PortfolioExpansionDraft",
    "build_claim_readiness",
    "build_portfolio_expansion_draft",
    "calibrate_external_report",
    "calibrate_portfolio_report",
    "calibrate_records",
    "gate_portfolio_coverage",
    "external_report_coverage_manifest",
    "plan_portfolio_expansion",
    "plan_external_report",
    "plan_portfolio_manifest",
    "is_legal_transition",
]
