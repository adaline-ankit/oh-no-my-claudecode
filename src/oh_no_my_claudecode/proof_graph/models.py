"""Typed values used by the proof-graph planner and evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TaskKind(StrEnum):
    """High-level change classification used to select proof obligations."""

    BUGFIX = "bugfix"
    FEATURE = "feature"
    REFACTOR = "refactor"
    MAINTENANCE = "maintenance"


class ClaimKind(StrEnum):
    """The property a claim says is true after the change."""

    BUGFIX = "bugfix"
    BEHAVIOR = "behavior"
    REGRESSION = "regression"
    SECURITY = "security"
    PERFORMANCE = "performance"
    UI = "ui"


class VerifierKind(StrEnum):
    """Stable verifier categories emitted by the synthesizer."""

    REPRODUCE = "reproduce"
    TARGETED_TESTS = "targeted-tests"
    REGRESSION = "regression"
    STATIC_ANALYSIS = "static-analysis"
    TYPE_CHECK = "type-check"
    LINT = "lint"
    SECURITY = "security"
    BROWSER = "browser"
    PERFORMANCE = "performance"


class Outcome(StrEnum):
    """Observed process outcome, independent of what a verifier expects."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class EvidenceSource(StrEnum):
    """Origin of evidence; agent prose is deliberately non-authoritative."""

    VERIFIER = "verifier"
    AGENT = "agent"


@dataclass(frozen=True, slots=True)
class Claim:
    """A falsifiable statement that must be backed by verifier evidence."""

    claim_id: str
    statement: str
    kind: ClaimKind


@dataclass(frozen=True, slots=True)
class TaskMetadata:
    """Task inputs used to synthesize a verifier graph."""

    task_id: str
    summary: str
    kind: TaskKind
    claims: tuple[Claim, ...] = ()


@dataclass(frozen=True, slots=True)
class RiskMetadata:
    """Explicit risk signals that require additional verification."""

    security: bool = False
    browser: bool = False
    performance: bool = False


@dataclass(frozen=True, slots=True)
class DiffMetadata:
    """Deterministic, caller-supplied description of the intended diff."""

    changed_files: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VerifierNode:
    """One planned verifier; ``argv`` is data and is never executed here."""

    verifier_id: str
    kind: VerifierKind
    argv: tuple[str, ...]
    expected_outcome: Outcome
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProofGraph:
    """A deterministic verifier DAG plus the metadata from which it was built."""

    task: TaskMetadata
    risk: RiskMetadata
    diff: DiffMetadata
    verifiers: tuple[VerifierNode, ...]

    @property
    def claims(self) -> tuple[Claim, ...]:
        """Return claims in their canonical order."""
        return self.task.claims


@dataclass(frozen=True, slots=True)
class Evidence:
    """Content-addressed output that links a verifier to one or more claims."""

    evidence_id: str
    verifier_id: str
    outcome: Outcome
    artifact_digest: str
    claim_ids: tuple[str, ...]
    source: EvidenceSource = EvidenceSource.VERIFIER


@dataclass(frozen=True, slots=True)
class VerifierResult:
    """Recorded result of a separately executed verifier plan node."""

    verifier_id: str
    outcome: Outcome
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProofAssessment:
    """Pure evaluation verdict. Only this type, never agent prose, declares completion."""

    complete: bool
    false_green: bool
    reasons: tuple[str, ...]
