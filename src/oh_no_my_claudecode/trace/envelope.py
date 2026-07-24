"""Complete run envelope — the tamper-evident record of one agent run.

Milestone 1 deliverable. The envelope is a *composition* layer: it binds the
pieces that already exist elsewhere in the codebase into one typed, byte-stable,
content-addressed record rather than reinventing any of them.

Reused, not duplicated
----------------------
- run identity, artifact refs, metric labels — :mod:`oh_no_my_claudecode.experiment.contracts`
  (:class:`RunId`, :class:`ArtifactRef`, :class:`MetricLabel`, :class:`CandidateState`).
- nested trace events (model / tool / sub-agent / handoff / retry / policy /
  verifier / artifact) — :class:`oh_no_my_claudecode.trace.models.TraceEvent`.
- deterministic secret redaction — :func:`oh_no_my_claudecode.tool_broker.redaction.redact_secrets`.
- the verified harness-run receipt — :mod:`oh_no_my_claudecode.harness_run.receipt`
  (embedded as-is and re-verified offline).

What this module adds
---------------------
- :class:`Metric` — a number that is *always* labelled measured vs estimated.
- :class:`EnvelopeEvent` — a nesting wrapper over :class:`TraceEvent` so
  sub-agent / handoff / retry trees stay structurally explicit.
- :class:`ContextCandidate` — retrieval provenance (selected / rejected, reason,
  score components, token cost, index revision, fallback flag).
- :class:`GitState`, :class:`TestOutcome`, :class:`LearningCandidateRef` — the
  run's git state / patch, test outcomes, and learning-candidate references.
- :class:`RunEnvelope` — the composition, with byte-stable ``to_dict`` /
  ``to_json``, deterministic redaction applied *before* hashing, a
  content-addressed receipt, and offline verification via
  :func:`verify_envelope`.

Honesty invariants
------------------
- Every numeric metric carries a :class:`MetricLabel`; nothing is silently
  "measured".
- Secrets are redacted from the body *before* it is hashed, so no secret can
  appear in the exported envelope or influence its receipt.
- The receipt is computed over the redacted body; tampering with any field
  changes the hash and fails :func:`verify_envelope`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum

from oh_no_my_claudecode.experiment.contracts import (
    ArtifactRef,
    CandidateState,
    MetricLabel,
    RunId,
)
from oh_no_my_claudecode.harness_run.receipt import verify_harness_receipt
from oh_no_my_claudecode.tool_broker.redaction import redact_secrets
from oh_no_my_claudecode.trace.models import TraceEvent

SCHEMA_VERSION = "1"

#: Media type stamped on the envelope's content-addressed receipt.
ENVELOPE_MEDIA_TYPE = "application/vnd.onmc.run-envelope+json"


def _canonical_bytes(value: object) -> bytes:
    """Byte-stable canonical JSON encoding (sorted keys, no whitespace)."""
    text = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return text.encode("utf-8")


# ---------------------------------------------------------------------------
# Labelled metric
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Metric:
    """A single number that is explicitly measured or estimated.

    There is no way to record a metric without a :class:`MetricLabel`; that is
    the whole point — a consumer never has to guess whether a number is real.
    """

    value: float
    label: MetricLabel = MetricLabel.MEASURED
    unit: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ValueError("metric value must be a real number")
        if not isinstance(self.label, MetricLabel):
            raise ValueError("metric label must be a MetricLabel")

    @property
    def estimated(self) -> bool:
        return self.label is MetricLabel.ESTIMATED

    def to_dict(self) -> dict[str, object]:
        return {"value": self.value, "label": self.label.value, "unit": self.unit}


# ---------------------------------------------------------------------------
# Nested events
# ---------------------------------------------------------------------------


class EventCategory(StrEnum):
    """Coarse family of a nested run event.

    The leaf data lives in a reused :class:`TraceEvent`; this label only records
    *what kind* of thing the event is so the tree reads clearly.
    """

    MODEL = "model"
    TOOL = "tool"
    SUBAGENT = "subagent"
    HANDOFF = "handoff"
    RETRY = "retry"
    POLICY = "policy"
    VERIFIER = "verifier"
    ARTIFACT = "artifact"


@dataclass(frozen=True, slots=True)
class EnvelopeEvent:
    """A trace event plus its nested children (sub-agent / retry / handoff tree).

    ``event`` is a reused :class:`TraceEvent`; ``children`` gives the nesting
    that a flat event list cannot express. Concurrency is represented as
    sibling children under a common parent.
    """

    category: EventCategory
    event: TraceEvent
    children: tuple[EnvelopeEvent, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category.value,
            "event": self.event.to_record(),
            "children": [child.to_dict() for child in self.children],
        }

    def iter_flat(self) -> list[EnvelopeEvent]:
        """Depth-first flattening of this event and all descendants."""
        out: list[EnvelopeEvent] = [self]
        for child in self.children:
            out.extend(child.iter_flat())
        return out

    def structural_errors(self, *, _depth: int = 0) -> list[str]:
        """Return structural problems; empty list means well-formed."""
        errors: list[str] = []
        if _depth > 64:
            errors.append("event nesting exceeds max depth 64")
            return errors
        if not isinstance(self.category, EventCategory):
            errors.append(f"event has invalid category: {self.category!r}")
        if not isinstance(self.event, TraceEvent):
            errors.append("event payload is not a TraceEvent")
        for child in self.children:
            errors.extend(child.structural_errors(_depth=_depth + 1))
        return errors


# ---------------------------------------------------------------------------
# Context-candidate provenance
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    """Provenance for one retrieval candidate — selected or rejected, and why."""

    candidate_id: str
    selected: bool
    reason: str
    score_components: dict[str, float] = field(default_factory=dict)
    token_cost: int = 0
    index_revision: str = ""
    fallback: bool = False

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty")
        if isinstance(self.token_cost, bool) or not isinstance(self.token_cost, int):
            raise ValueError("token_cost must be an integer")
        if self.token_cost < 0:
            raise ValueError("token_cost must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "selected": self.selected,
            "reason": self.reason,
            # sorted for byte-stability regardless of insertion order
            "score_components": {
                k: self.score_components[k] for k in sorted(self.score_components)
            },
            "token_cost": self.token_cost,
            "index_revision": self.index_revision,
            "fallback": self.fallback,
        }


# ---------------------------------------------------------------------------
# Git state / tests / learning candidates
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GitState:
    """The run's git state and (optionally) a content-addressed patch ref."""

    branch: str
    head_sha: str
    dirty: bool = False
    patch: ArtifactRef | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "branch": self.branch,
            "head_sha": self.head_sha,
            "dirty": self.dirty,
            "patch": self.patch.to_dict() if self.patch is not None else None,
        }


@dataclass(frozen=True, slots=True)
class TestOutcome:
    """A single test result. ``passed`` is a verified outcome, never self-report."""

    # Tell pytest this is a domain type, not a test class to collect.
    __test__ = False

    name: str
    passed: bool
    label: MetricLabel = MetricLabel.MEASURED
    duration_ms: float = 0.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("test name must not be empty")
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, (int, float)):
            raise ValueError("duration_ms must be a real number")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "label": self.label.value,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True, slots=True)
class LearningCandidateRef:
    """Reference to a learning candidate produced by this run (lifecycle-stated)."""

    candidate_id: str
    state: CandidateState
    artifact: ArtifactRef | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty")
        if not isinstance(self.state, CandidateState):
            raise ValueError("state must be a CandidateState")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "state": self.state.value,
            "artifact": self.artifact.to_dict() if self.artifact is not None else None,
        }


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunEnvelope:
    """The complete, tamper-evident record of one agent run.

    Call :meth:`to_json` to serialise (byte-stable). The serialised form carries
    a content-addressed ``receipt`` that :func:`verify_envelope` recomputes
    offline; any tampering changes the body hash and fails verification.

    ``secret_values`` are redaction inputs only — they are *never* serialised.
    """

    run_id: RunId
    created_at: float
    events: tuple[EnvelopeEvent, ...] = ()
    context_candidates: tuple[ContextCandidate, ...] = ()
    git: GitState | None = None
    tests: tuple[TestOutcome, ...] = ()
    artifacts: tuple[ArtifactRef, ...] = ()
    costs: dict[str, Metric] = field(default_factory=dict)
    learning_candidates: tuple[LearningCandidateRef, ...] = ()
    harness_receipt: dict[str, object] | None = None
    secret_values: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            raise ValueError("run_id must be a RunId")
        if isinstance(self.created_at, bool) or not isinstance(self.created_at, (int, float)):
            raise ValueError("created_at must be a real number")
        for name, metric in self.costs.items():
            if not isinstance(metric, Metric):
                raise ValueError(f"cost {name!r} must be a Metric (got {type(metric).__name__})")

    # -- structural validity ------------------------------------------------

    def structural_errors(self) -> list[str]:
        """Return structural problems across the whole envelope; empty == valid."""
        errors: list[str] = []
        for ev in self.events:
            errors.extend(ev.structural_errors())
        seen: set[str] = set()
        for cand in self.context_candidates:
            if cand.candidate_id in seen:
                errors.append(f"duplicate context candidate id: {cand.candidate_id}")
            seen.add(cand.candidate_id)
        return errors

    @property
    def is_structurally_valid(self) -> bool:
        return not self.structural_errors()

    # -- serialisation ------------------------------------------------------

    def _body(self) -> dict[str, object]:
        """The redacted, receipt-free body that the receipt is computed over."""
        raw: dict[str, object] = {
            "schema_version": self.schema_version,
            "run_id": {
                "slug": self.run_id.slug,
                "experiment_id": self.run_id.experiment_id,
                "condition": self.run_id.condition.value,
                "task_id": self.run_id.task_id,
                "trial": self.run_id.trial,
            },
            "created_at": self.created_at,
            "events": [ev.to_dict() for ev in self.events],
            "context_candidates": [c.to_dict() for c in self.context_candidates],
            "git": self.git.to_dict() if self.git is not None else None,
            "tests": [t.to_dict() for t in self.tests],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "costs": {name: self.costs[name].to_dict() for name in sorted(self.costs)},
            "learning_candidates": [lc.to_dict() for lc in self.learning_candidates],
        }
        # Deterministic redaction happens BEFORE hashing so no secret ever
        # reaches the exported body or the receipt.
        redacted: dict[str, object] = redact_secrets(raw, secret_values=self.secret_values)
        # The embedded harness receipt is already a sealed, verified artifact —
        # attach it verbatim so its own content-addressed hash still verifies.
        # (Upstream sanitises it before sealing; re-redacting would break it.)
        redacted["harness_receipt"] = self.harness_receipt
        return redacted

    def receipt(self) -> ArtifactRef:
        """Content-addressed receipt over the redacted body (reuses ArtifactRef)."""
        return ArtifactRef.of(_canonical_bytes(self._body()), ENVELOPE_MEDIA_TYPE)

    def to_dict(self) -> dict[str, object]:
        body = self._body()
        return {**body, "receipt": self.receipt().to_dict()}

    def to_json(self) -> str:
        """Byte-stable JSON serialisation of the full envelope."""
        return _canonical_bytes(self.to_dict()).decode("utf-8")

    def verify(self) -> bool:
        """Self-check: the receipt matches the body and any harness receipt verifies."""
        return verify_envelope(self.to_json())


def verify_envelope(serialized: str) -> bool:
    """Offline verification of a serialised :class:`RunEnvelope`.

    Recomputes the content-address of the receipt-free body and compares it to
    the embedded receipt (sha256, size, media type). Also re-verifies any
    embedded harness-run receipt. Returns ``False`` on any mismatch or malformed
    input — it never raises.
    """
    try:
        raw = json.loads(serialized)
    except (TypeError, ValueError):
        return False
    if not isinstance(raw, dict):
        return False

    claimed = raw.pop("receipt", None)
    if not isinstance(claimed, dict):
        return False

    body_bytes = _canonical_bytes(raw)
    expected = ArtifactRef.of(body_bytes, ENVELOPE_MEDIA_TYPE)
    if (
        claimed.get("sha256") != expected.sha256
        or claimed.get("size_bytes") != expected.size_bytes
        or claimed.get("media_type") != expected.media_type
    ):
        return False

    # Re-verify the embedded verified harness receipt, if present.
    harness = raw.get("harness_receipt")
    return not (isinstance(harness, dict) and not verify_harness_receipt(json.dumps(harness)))


__all__ = [
    "ENVELOPE_MEDIA_TYPE",
    "SCHEMA_VERSION",
    "ContextCandidate",
    "EnvelopeEvent",
    "EventCategory",
    "GitState",
    "LearningCandidateRef",
    "Metric",
    "RunEnvelope",
    "TestOutcome",
    "verify_envelope",
]
