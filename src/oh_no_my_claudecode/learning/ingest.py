"""Opt-in gated memory ingestion — route a proposed write through the gate.

This module is the *live seam* between the pure eval-gated learning core
(:mod:`.gate`, :mod:`.models`) and whatever actually persists a memory. It adds
nothing to the state machine and reinvents none of it; it simply drives a
proposed learning candidate along the mandatory lifecycle

    observed -> candidate -> sanitized -> scoped -> shadow-evaluated -> promoted

and lets a write reach the memory store **only** once the candidate is
``PROMOTED`` — i.e. it is sanitize-clean, scoped, backed by a held-out matched
evaluation that beats the learning-DISABLED control, and non-regressing on the
protected suite. A candidate that fails sanitize (prompt injection / secret) or
lacks held-out evidence is *never* handed to the sink.

Design goals:

* **Additive & opt-in.** The default memory path is untouched. Nothing here
  wraps or replaces the existing store; a caller must explicitly build a
  :class:`GatedIngestor` and route writes through it. Code that keeps writing to
  the store directly is unaffected.
* **Store-agnostic seam.** The destination is an injected :class:`MemorySink`
  (a small Protocol) — a memory-write callable — so tests need no real store and
  any adapter (SQLite, in-memory, remote) can be plugged in.
* **No active memory without a promotion record.** Every :class:`IngestedMemory`
  handed to the sink carries the :class:`~.models.PromotionRecord` that
  authorized it, plus its provenance, scope, and bumped version — and can be
  rolled back.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from oh_no_my_claudecode.experiment.contracts import CandidateState, is_legal_transition

from .gate import (
    AdvanceEvent,
    LearningError,
    PromotionDecision,
    PromotionGate,
    advance,
)
from .gate import rollback as _gate_rollback
from .models import (
    LearningCandidate,
    PromotionRecord,
    Provenance,
    Scope,
    ShadowEvaluation,
)

#: The canonical forward path from a raw proposal up to (but excluding)
#: promotion. The ingestor advances through whichever of these steps legally
#: follow the candidate's current state, so a caller may hand in a candidate at
#: any pre-promotion state and have it driven the rest of the way.
_FORWARD_TO_SHADOW: tuple[CandidateState, ...] = (
    CandidateState.CANDIDATE,
    CandidateState.SANITIZED,
    CandidateState.SCOPED,
    CandidateState.SHADOW_EVALUATED,
)


@dataclass(frozen=True, slots=True)
class IngestedMemory:
    """The record hand-off given to a :class:`MemorySink` on promotion.

    It intentionally carries the full authorization trail — provenance, scope,
    version and the :class:`~.models.PromotionRecord` — so a store can persist
    honest provenance and so nothing lands as active memory without proof.
    """

    memory_id: str
    kind: str
    content: str
    scope: Scope
    provenance: Provenance
    version: int
    promotion: PromotionRecord

    def to_dict(self) -> dict[str, object]:
        return {
            "memory_id": self.memory_id,
            "kind": self.kind,
            "content": self.content,
            "scope": self.scope.to_dict(),
            "provenance": self.provenance.to_dict(),
            "version": self.version,
            "promotion": self.promotion.to_dict(),
        }


class MemorySink(Protocol):
    """The injected memory-write seam.

    A real adapter would wrap the project's storage (e.g. upsert a
    :class:`~oh_no_my_claudecode.models.memory.MemoryEntry`); tests pass a tiny
    recording double. ``write`` persists a promoted memory and returns the stored
    id; ``remove`` reverses that write and reports whether anything was removed.
    """

    def write(self, memory: IngestedMemory) -> str: ...

    def remove(self, memory_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of one :meth:`GatedIngestor.ingest` call.

    Either ``ingested`` (a promotion record exists and the sink was called
    exactly once) or rejected (``reasons`` explains why; the sink was never
    called).
    """

    ingested: bool
    candidate: LearningCandidate
    decision: PromotionDecision
    memory_id: str | None = None
    reasons: tuple[str, ...] = ()

    @property
    def rejected(self) -> bool:
        return not self.ingested

    @property
    def promotion(self) -> PromotionRecord | None:
        return self.candidate.promotion

    def to_dict(self) -> dict[str, object]:
        return {
            "ingested": self.ingested,
            "memory_id": self.memory_id,
            "reasons": list(self.reasons),
            "decision": self.decision.to_dict(),
            "candidate": self.candidate.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RollbackResult:
    """Outcome of :meth:`GatedIngestor.rollback`."""

    rolled_back: bool
    memory_id: str
    removed_from_sink: bool = False
    candidate: LearningCandidate | None = None
    reason: str = ""


def _default_clock() -> int:
    return int(time.time() * 1000)


class GatedIngestor:
    """Opt-in adapter: promote-then-write, gated by :class:`PromotionGate`.

    ``GatedIngestor(gate, sink)`` binds a promotion gate to a memory-write sink.
    :meth:`ingest` drives a proposed candidate through sanitize + scope +
    held-out evaluation and writes to the sink **only** on promotion;
    :meth:`rollback` reverses an ingested memory and removes it from the sink.

    The ingestor keeps an in-process registry of what it has written so it can
    roll those writes back; it never touches any store except through the
    injected sink.
    """

    def __init__(
        self,
        gate: PromotionGate,
        sink: MemorySink,
        *,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self._gate = gate
        self._sink = sink
        # ``clock`` is an optional zero-arg callable returning epoch-ms; tests
        # inject a deterministic stub, production uses wall-clock ms.
        self._clock: Callable[[], int] = clock if clock is not None else _default_clock
        self._ingested: dict[str, LearningCandidate] = {}

    # -- ingestion ----------------------------------------------------------

    def ingest(
        self,
        candidate: LearningCandidate,
        evidence: ShadowEvaluation | None = None,
        *,
        reason: str = "",
    ) -> IngestResult:
        """Route a proposed memory write through the promotion gate.

        Returns an :class:`IngestResult`. The sink is called **exactly once**
        iff the candidate is promoted; on any rejection (illegal state,
        sanitizer finding, empty scope, missing/failing held-out evidence) the
        sink is never called and ``reasons`` explains why.
        """
        at_ms = int(self._clock())

        try:
            prepared = self._drive_to_shadow_evaluated(candidate, evidence, at_ms=at_ms)
        except LearningError as exc:
            # A barrier fired (sanitize / illegal transition / missing payload).
            # No promotion record was created; the sink is never touched.
            reasons = (str(exc),)
            return IngestResult(
                ingested=False,
                candidate=candidate,
                decision=PromotionDecision(eligible=False, reasons=reasons),
                reasons=reasons,
            )

        decision = self._gate.evaluate(prepared)
        if not decision.eligible:
            return IngestResult(
                ingested=False,
                candidate=prepared,
                decision=decision,
                reasons=decision.reasons,
            )

        promoted = advance(
            prepared,
            AdvanceEvent(to=CandidateState.PROMOTED, at_ms=at_ms, reason=reason),
            gate=self._gate,
        )
        record = promoted.promotion
        # Guaranteed by the gate: an eligible candidate has a held-out evaluation
        # and, once advanced, a promotion record. This is the invariant that
        # makes "no active memory without a promotion record" hold.
        assert record is not None  # noqa: S101

        memory = IngestedMemory(
            memory_id=promoted.id,
            kind=promoted.kind.value,
            content=promoted.content,
            scope=promoted.scope,
            provenance=promoted.provenance,
            version=promoted.version,
            promotion=record,
        )
        memory_id = self._sink.write(memory)
        self._ingested[memory_id] = promoted
        return IngestResult(
            ingested=True,
            candidate=promoted,
            decision=decision,
            memory_id=memory_id,
        )

    def _drive_to_shadow_evaluated(
        self,
        candidate: LearningCandidate,
        evidence: ShadowEvaluation | None,
        *,
        at_ms: int,
    ) -> LearningCandidate:
        """Advance *candidate* through the pre-promotion lifecycle steps.

        Only steps that legally follow the current state are applied, so a
        candidate handed in already ``SCOPED`` resumes at the evaluation step.
        Raises :class:`LearningError` on any barrier — the caller converts that
        into a rejection.
        """
        current = candidate
        for target in _FORWARD_TO_SHADOW:
            if not is_legal_transition(current.state, target):
                continue
            event = AdvanceEvent(to=target, at_ms=at_ms)
            if target is CandidateState.SCOPED:
                event = AdvanceEvent(to=target, scope=current.scope, at_ms=at_ms)
            elif target is CandidateState.SHADOW_EVALUATED:
                event = AdvanceEvent(to=target, evaluation=evidence, at_ms=at_ms)
            current = advance(current, event, gate=self._gate)
        return current

    # -- reversal -----------------------------------------------------------

    def rollback(self, memory_id: str, *, reason: str = "ingest rollback") -> RollbackResult:
        """Reverse a previously-ingested memory and remove it from the sink.

        Idempotent-ish: rolling back an unknown id is a no-op that reports
        ``rolled_back=False``.
        """
        candidate = self._ingested.get(memory_id)
        if candidate is None:
            return RollbackResult(
                rolled_back=False,
                memory_id=memory_id,
                reason="unknown memory id — nothing ingested under it",
            )

        reversed_candidate = _gate_rollback(candidate, at_ms=int(self._clock()), reason=reason)
        removed = self._sink.remove(memory_id)
        del self._ingested[memory_id]
        return RollbackResult(
            rolled_back=True,
            memory_id=memory_id,
            removed_from_sink=removed,
            candidate=reversed_candidate,
        )

    # -- introspection ------------------------------------------------------

    def ingested_ids(self) -> tuple[str, ...]:
        """Ids of memories currently live through this ingestor (sorted)."""
        return tuple(sorted(self._ingested))


__all__ = [
    "GatedIngestor",
    "IngestResult",
    "IngestedMemory",
    "MemorySink",
    "RollbackResult",
]
