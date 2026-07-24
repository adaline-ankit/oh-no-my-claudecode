"""Frozen cross-cutting contracts for the ONMC SOTA experiment/evidence layer.

These are the *shared vocabulary* every experiment, run envelope, and learning
component agrees on. They are intentionally small, dependency-free, and stable:
downstream modules (experiment kernel, run envelope, eval-gated learning) import
from here rather than inventing competing versions of the same concept.

Where a canonical type already exists elsewhere on ``main`` it is reused, not
duplicated:

- run/node lifecycle state — :mod:`oh_no_my_claudecode.durable_runtime`
- capability/policy decisions — :mod:`oh_no_my_claudecode.tool_broker`
- run verification receipt — :mod:`oh_no_my_claudecode.harness_run.receipt`
- trace events / OTel mapping — :mod:`oh_no_my_claudecode.trace`

This module adds only what those do not already provide: experiment identity,
the experiment manifest, per-trial outcomes, content-addressed artifact refs,
the candidate-learning lifecycle, and the measured/estimated metric label.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar

SCHEMA_VERSION = "1"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class Condition(StrEnum):
    """The three comparison arms every experiment must be able to express.

    ``BARE_AGENT`` is a real control — the agent with no ONMC retrieval, policy,
    or verifier — never a simulated empty condition (blueprint truth rule 4).
    """

    BARE_AGENT = "bare-agent"
    ONMC_CURRENT = "onmc-current"
    ONMC_CANDIDATE = "onmc-candidate"


class BenchmarkAuditStatus(StrEnum):
    """Honest provenance for a task set — never silently trust a benchmark."""

    VALID = "valid"
    SUSPECT = "suspect"
    BROKEN = "broken"
    EXCLUDED = "excluded"


class MetricLabel(StrEnum):
    """Every reported number is explicitly measured or estimated."""

    MEASURED = "measured"
    ESTIMATED = "estimated"


class CandidateState(StrEnum):
    """The single lifecycle every learned artifact must traverse.

    No code path may activate learned behavior before ``PROMOTED``; promotion
    requires held-out evidence and is always reversible via ``ROLLED_BACK``.
    """

    OBSERVED = "observed"
    CANDIDATE = "candidate"
    SANITIZED = "sanitized"
    SCOPED = "scoped"
    SHADOW_EVALUATED = "shadow-evaluated"
    PROMOTED = "promoted"
    MONITORED = "monitored"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled-back"


#: Legal forward transitions for the candidate-learning state machine. A
#: promotion can only follow a shadow evaluation; a rollback or supersession can
#: follow any active state. Enforced by :func:`is_legal_transition`.
_CANDIDATE_TRANSITIONS: dict[CandidateState, frozenset[CandidateState]] = {
    CandidateState.OBSERVED: frozenset({CandidateState.CANDIDATE}),
    CandidateState.CANDIDATE: frozenset({CandidateState.SANITIZED, CandidateState.ROLLED_BACK}),
    CandidateState.SANITIZED: frozenset({CandidateState.SCOPED, CandidateState.ROLLED_BACK}),
    CandidateState.SCOPED: frozenset(
        {CandidateState.SHADOW_EVALUATED, CandidateState.ROLLED_BACK}
    ),
    CandidateState.SHADOW_EVALUATED: frozenset(
        {CandidateState.PROMOTED, CandidateState.ROLLED_BACK}
    ),
    CandidateState.PROMOTED: frozenset({CandidateState.MONITORED, CandidateState.ROLLED_BACK}),
    CandidateState.MONITORED: frozenset(
        {CandidateState.SUPERSEDED, CandidateState.ROLLED_BACK}
    ),
    CandidateState.SUPERSEDED: frozenset(),
    CandidateState.ROLLED_BACK: frozenset(),
}


def is_legal_transition(src: CandidateState, dst: CandidateState) -> bool:
    """Return whether ``src -> dst`` is an allowed candidate-lifecycle move."""
    return dst in _CANDIDATE_TRANSITIONS[src]


def _require_id(value: str, name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ValueError(f"{name} must match {_ID_RE.pattern!r}, got {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class ExperimentId:
    """Stable, human-readable experiment identity (kebab-case slug)."""

    value: str

    def __post_init__(self) -> None:
        _require_id(self.value, "experiment id")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class RunId:
    """Concurrency-safe identity for one condition trial within an experiment."""

    experiment_id: str
    condition: Condition
    task_id: str
    trial: int

    def __post_init__(self) -> None:
        _require_id(self.experiment_id, "experiment id")
        if not isinstance(self.condition, Condition):
            raise ValueError("condition must be a Condition")
        if not self.task_id.strip():
            raise ValueError("task_id must not be empty")
        if not isinstance(self.trial, int) or isinstance(self.trial, bool) or self.trial < 0:
            raise ValueError("trial must be a non-negative integer")

    @property
    def slug(self) -> str:
        """Deterministic, filesystem-safe run identifier."""
        safe_task = re.sub(r"[^a-zA-Z0-9]+", "-", self.task_id).strip("-").lower()
        return f"{self.experiment_id}.{self.condition.value}.{safe_task}.t{self.trial}"


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Content-addressed reference to a run artifact (patch, log, screenshot)."""

    sha256: str
    media_type: str
    size_bytes: int

    def __post_init__(self) -> None:
        if not _SHA256_RE.match(self.sha256):
            raise ValueError("sha256 must be 64 lowercase hex chars")
        if not self.media_type.strip():
            raise ValueError("media_type must not be empty")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")

    @classmethod
    def of(cls, data: bytes, media_type: str) -> ArtifactRef:
        """Build a ref by hashing *data* — the address IS the content."""
        return cls(hashlib.sha256(data).hexdigest(), media_type, len(data))

    def to_dict(self) -> dict[str, object]:
        return {"sha256": self.sha256, "media_type": self.media_type, "size_bytes": self.size_bytes}


@dataclass(frozen=True, slots=True)
class TrialResult:
    """One paired, per-task outcome. ``passed`` reflects verified outcome state,
    never agent self-report (blueprint truth rule 6)."""

    run_id: RunId
    passed: bool
    metric_label: MetricLabel = MetricLabel.MEASURED
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    turns: int = 0
    tool_calls: int = 0
    context_tokens: int = 0
    interventions: int = 0
    artifacts: tuple[ArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        for name in ("cost_usd", "latency_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"{name} must be a non-negative number")
        for name in ("turns", "tool_calls", "context_tokens", "interventions"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id.slug,
            "condition": self.run_id.condition.value,
            "task_id": self.run_id.task_id,
            "trial": self.run_id.trial,
            "passed": self.passed,
            "metric_label": self.metric_label.value,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "context_tokens": self.context_tokens,
            "interventions": self.interventions,
            "artifacts": [a.to_dict() for a in self.artifacts],
        }


@dataclass(frozen=True, slots=True)
class Environment:
    """The provenance stamp that makes a comparison reproducible."""

    code_sha: str
    config_hash: str
    model: str
    provider: str
    image: str = "local"

    def to_dict(self) -> dict[str, object]:
        return {
            "code_sha": self.code_sha,
            "config_hash": self.config_hash,
            "model": self.model,
            "provider": self.provider,
            "image": self.image,
        }


@dataclass(frozen=True, slots=True)
class ExperimentManifest:
    """Versioned, frozen description of a comparison — the unit of reproducibility."""

    experiment_id: ExperimentId
    task_set_revision: str
    conditions: tuple[Condition, ...]
    trials: int
    seed: int
    environment: Environment
    audit_status: BenchmarkAuditStatus = BenchmarkAuditStatus.SUSPECT
    leakage_notes: str = ""
    schema_version: str = SCHEMA_VERSION

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "experiment_id",
            "task_set_revision",
            "conditions",
            "trials",
            "seed",
            "environment",
            "audit_status",
            "leakage_notes",
            "schema_version",
        }
    )

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported manifest schema version: {self.schema_version}")
        if not self.task_set_revision.strip():
            raise ValueError("task_set_revision must not be empty (freeze the task set)")
        if len(self.conditions) < 2 or len(set(self.conditions)) != len(self.conditions):
            raise ValueError("at least two distinct conditions are required")
        if not isinstance(self.trials, int) or isinstance(self.trials, bool) or self.trials < 1:
            raise ValueError("trials must be a positive integer")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise ValueError("seed must be an integer")

    @property
    def requires_uncertainty(self) -> bool:
        """Nondeterministic comparisons need >1 trial for honest CIs (rule 5)."""
        return self.trials > 1

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id.value,
            "task_set_revision": self.task_set_revision,
            "conditions": [c.value for c in self.conditions],
            "trials": self.trials,
            "seed": self.seed,
            "environment": self.environment.to_dict(),
            "audit_status": self.audit_status.value,
            "leakage_notes": self.leakage_notes,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    """What a coding-agent adapter can honestly do — drives conformance + gates.

    ``enforced_effects`` is True only when every supported effect crosses the
    ONMC broker/proxy/hook (blueprint truth rule 9); otherwise the adapter is
    advisory and must be labeled as such.
    """

    name: str
    supports_real_run: bool
    enforced_effects: bool = False
    capabilities: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("adapter name must not be empty")

    @property
    def advisory_only(self) -> bool:
        return not self.enforced_effects

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "supports_real_run": self.supports_real_run,
            "enforced_effects": self.enforced_effects,
            "advisory_only": self.advisory_only,
            "capabilities": list(self.capabilities),
        }


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
