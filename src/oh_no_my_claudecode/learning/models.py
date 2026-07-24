"""Typed domain model for the eval-gated repository-learning state machine.

Everything a learned artifact needs to travel the mandatory lifecycle

    observed -> candidate -> sanitized -> scoped -> shadow-evaluated
             -> promoted -> monitored -> superseded / rolled-back

lives here as small, frozen, explicitly-validated dataclasses. The lifecycle
*state* itself and its legal transitions are owned by the shared experiment
contracts (:class:`~oh_no_my_claudecode.experiment.contracts.CandidateState`);
this module never re-invents them.

Nothing here activates learned behavior. A candidate only influences an agent
once it reaches ``PROMOTED``/``MONITORED`` with a recorded
:class:`PromotionRecord` and an unexpired refresh policy — see
:meth:`LearningCandidate.is_active`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from fnmatch import fnmatch

from oh_no_my_claudecode.experiment.contracts import (
    ArtifactRef,
    CandidateState,
    MetricLabel,
)

from .sanitize import Finding

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")


class CandidateKind(StrEnum):
    """The kinds of repository learning the machine can carry."""

    EPISODE = "episode"
    REPO_FACT = "repo-fact"
    DECISION = "decision"
    FAILED_APPROACH = "failed-approach"
    SKILL = "skill"
    STRATEGY = "strategy"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a candidate came from — trace ids plus content-addressed artifacts.

    Honest provenance is a promotion pre-requisite: a promotion record always
    captures the provenance that justified it (see :class:`PromotionRecord`).
    """

    trace_ids: tuple[str, ...] = ()
    artifacts: tuple[ArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        for tid in self.trace_ids:
            if not isinstance(tid, str) or not tid.strip():
                raise ValueError("trace_ids entries must be non-empty strings")
        for art in self.artifacts:
            if not isinstance(art, ArtifactRef):
                raise ValueError("artifacts entries must be ArtifactRef instances")

    @property
    def is_empty(self) -> bool:
        return not self.trace_ids and not self.artifacts

    def to_dict(self) -> dict[str, object]:
        return {
            "trace_ids": list(self.trace_ids),
            "artifacts": [a.to_dict() for a in self.artifacts],
        }


@dataclass(frozen=True, slots=True)
class Scope:
    """Where a learned artifact is allowed to apply.

    All fields are glob lists. An empty scope is *unscoped* and can never be
    promoted (the gate requires a non-empty scope) — learning must be bounded to
    the repo/branch/path/language/task it was learned from.
    """

    repos: tuple[str, ...] = ()
    branches: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    tasks: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.repos or self.branches or self.paths or self.languages or self.tasks)

    @staticmethod
    def _match_any(globs: tuple[str, ...], value: str | None) -> bool:
        if not globs:
            return True
        if value is None:
            return False
        return any(fnmatch(value, g) for g in globs)

    def matches(
        self,
        *,
        repo: str | None = None,
        branch: str | None = None,
        path: str | None = None,
        language: str | None = None,
        task: str | None = None,
    ) -> bool:
        """Return whether a target context falls inside this scope.

        An empty dimension is a wildcard for that dimension; a populated
        dimension must be satisfied by one of its globs.
        """
        return (
            self._match_any(self.repos, repo)
            and self._match_any(self.branches, branch)
            and self._match_any(self.paths, path)
            and self._match_any(self.languages, language)
            and self._match_any(self.tasks, task)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "repos": list(self.repos),
            "branches": list(self.branches),
            "paths": list(self.paths),
            "languages": list(self.languages),
            "tasks": list(self.tasks),
        }


@dataclass(frozen=True, slots=True)
class ShadowEvaluation:
    """Result of a held-out, matched evaluation of a candidate.

    ``candidate_score`` is the learning-ENABLED arm; ``control_score`` is the
    learning-DISABLED control arm run over the same held-out set. Promotion
    requires a strict improvement over the control AND a passing protected-suite
    non-regression flag.
    """

    candidate_score: float
    control_score: float
    sample_size: int
    protected_suite_passed: bool
    metric_label: MetricLabel = MetricLabel.MEASURED
    held_out: bool = True

    def __post_init__(self) -> None:
        for name in ("candidate_score", "control_score"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a number")
        if not isinstance(self.sample_size, int) or isinstance(self.sample_size, bool):
            raise ValueError("sample_size must be an integer")
        if self.sample_size < 1:
            raise ValueError("sample_size must be >= 1 (an empty eval proves nothing)")

    @property
    def delta(self) -> float:
        """Improvement of the learning arm over the disabled control."""
        return self.candidate_score - self.control_score

    def improves_over_control(self, min_improvement: float = 0.0) -> bool:
        return self.held_out and self.delta > min_improvement

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_score": self.candidate_score,
            "control_score": self.control_score,
            "delta": self.delta,
            "sample_size": self.sample_size,
            "protected_suite_passed": self.protected_suite_passed,
            "metric_label": self.metric_label.value,
            "held_out": self.held_out,
        }


@dataclass(frozen=True, slots=True)
class RefreshPolicy:
    """Freshness contract for a learned artifact.

    ``expires_at_ms`` is an absolute wall-clock deadline (epoch ms); once passed
    the artifact is stale and :meth:`LearningCandidate.is_active` treats it as
    inactive even while its state still reads ``PROMOTED``.
    """

    expires_at_ms: int | None = None
    refresh_interval_ms: int | None = None

    def __post_init__(self) -> None:
        for name in ("expires_at_ms", "refresh_interval_ms"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer or None")

    def is_expired(self, now_ms: int) -> bool:
        return self.expires_at_ms is not None and now_ms >= self.expires_at_ms

    def to_dict(self) -> dict[str, object]:
        return {
            "expires_at_ms": self.expires_at_ms,
            "refresh_interval_ms": self.refresh_interval_ms,
        }


@dataclass(frozen=True, slots=True)
class PromotionRecord:
    """Immutable audit stamp written the moment a candidate is promoted.

    Its existence is the *only* thing that authorizes learned behavior to go
    live, and it captures everything needed to justify or reverse that decision:
    the version, the held-out evidence, the provenance, and the scope.
    """

    version: int
    evaluation: ShadowEvaluation
    provenance: Provenance
    scope: Scope
    promoted_at_ms: int
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ValueError("promotion version must be a positive integer")
        if not isinstance(self.promoted_at_ms, int) or isinstance(self.promoted_at_ms, bool):
            raise ValueError("promoted_at_ms must be an integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "evaluation": self.evaluation.to_dict(),
            "provenance": self.provenance.to_dict(),
            "scope": self.scope.to_dict(),
            "promoted_at_ms": self.promoted_at_ms,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LearningCandidate:
    """A single learned artifact travelling the eval-gated lifecycle.

    Frozen: state transitions produce *new* candidates (via
    :func:`dataclasses.replace`, exposed as :meth:`evolve`), so history is never
    silently mutated in place.
    """

    id: str
    kind: CandidateKind
    content: str
    provenance: Provenance = field(default_factory=Provenance)
    scope: Scope = field(default_factory=Scope)
    state: CandidateState = CandidateState.OBSERVED
    version: int = 0
    findings: tuple[Finding, ...] = ()
    evaluation: ShadowEvaluation | None = None
    promotion: PromotionRecord | None = None
    refresh: RefreshPolicy = field(default_factory=RefreshPolicy)
    created_at_ms: int = 0
    updated_at_ms: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _ID_RE.match(self.id):
            raise ValueError(f"candidate id must match {_ID_RE.pattern!r}, got {self.id!r}")
        if not isinstance(self.kind, CandidateKind):
            raise ValueError("kind must be a CandidateKind")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("content must be a non-empty string")
        if not isinstance(self.state, CandidateState):
            raise ValueError("state must be a CandidateState")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 0:
            raise ValueError("version must be a non-negative integer")

    # -- derived predicates -------------------------------------------------

    @property
    def is_sanitized_clean(self) -> bool:
        """True when the sanitizer left no findings on this candidate."""
        return not self.findings

    def is_active(self, now_ms: int) -> bool:
        """Whether this candidate's learned behavior may currently influence an agent.

        Active requires a live state (``PROMOTED`` or ``MONITORED``), a recorded
        promotion, and a refresh policy that has not expired. Every other state —
        including ``SUPERSEDED`` and ``ROLLED_BACK`` — is inactive, and a stale
        (expired) artifact is inactive even while promoted.
        """
        if self.state not in (CandidateState.PROMOTED, CandidateState.MONITORED):
            return False
        if self.promotion is None:
            return False
        return not self.refresh.is_expired(now_ms)

    def is_stale(self, now_ms: int) -> bool:
        return self.refresh.is_expired(now_ms)

    # -- immutable update ---------------------------------------------------

    def evolve(self, **changes: object) -> LearningCandidate:
        """Return a copy with *changes* applied (re-validated by ``__post_init__``)."""
        # ``replace`` type-checks kwargs against each field; a **dict expansion
        # is necessarily untyped here, so the per-field arg-type errors are
        # expected. Validation still runs via ``__post_init__`` on the copy.
        return replace(self, **changes)  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "content": self.content,
            "provenance": self.provenance.to_dict(),
            "scope": self.scope.to_dict(),
            "state": self.state.value,
            "version": self.version,
            "findings": [f.to_dict() for f in self.findings],
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
            "promotion": self.promotion.to_dict() if self.promotion else None,
            "refresh": self.refresh.to_dict(),
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
        }


__all__ = [
    "CandidateKind",
    "LearningCandidate",
    "PromotionRecord",
    "Provenance",
    "RefreshPolicy",
    "Scope",
    "ShadowEvaluation",
]
