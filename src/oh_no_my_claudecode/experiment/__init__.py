"""ONMC SOTA experiment/evidence layer — frozen shared contracts.

The experiment kernel, run envelope, and eval-gated learning all build on the
vocabulary defined in :mod:`oh_no_my_claudecode.experiment.contracts`.
"""

from __future__ import annotations

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
    "is_legal_transition",
]
