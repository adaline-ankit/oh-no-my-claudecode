"""In-process registry that quarantines learning candidates by default."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from .models import LearningCandidate

if TYPE_CHECKING:
    from .promotion import GovernedPromotionDecision, PromotionManifest


class CandidateDisposition(StrEnum):
    """Registry disposition, deliberately separate from lifecycle state."""

    QUARANTINED = "quarantined"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled-back"


class CandidateConflictError(ValueError):
    """The same candidate id was reused with a different frozen manifest."""


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    """Candidate, frozen governance evidence, and its current disposition."""

    candidate: LearningCandidate
    manifest: PromotionManifest
    manifest_digest: str
    disposition: CandidateDisposition = CandidateDisposition.QUARANTINED
    decision: GovernedPromotionDecision | None = None
    created_at_ms: int = 0
    updated_at_ms: int = 0
    rollback_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.to_dict(),
            "manifest": self.manifest.to_dict(),
            "manifest_digest": self.manifest_digest,
            "disposition": self.disposition.value,
            "decision": self.decision.to_dict() if self.decision else None,
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
            "rollback_reason": self.rollback_reason,
        }


class CandidateRegistry:
    """Deterministic registry with quarantine-on-register semantics."""

    def __init__(self) -> None:
        self._records: dict[str, CandidateRecord] = {}

    def register(
        self,
        candidate: LearningCandidate,
        manifest: PromotionManifest,
        *,
        at_ms: int = 0,
    ) -> CandidateRecord:
        """Register once; identical submissions return the existing record."""
        digest = manifest.digest(candidate)
        existing = self._records.get(candidate.id)
        if existing is not None:
            if existing.manifest_digest != digest:
                raise CandidateConflictError(
                    f"candidate {candidate.id!r} already has a different frozen manifest"
                )
            return existing
        record = CandidateRecord(
            candidate=candidate,
            manifest=manifest,
            manifest_digest=digest,
            created_at_ms=at_ms,
            updated_at_ms=at_ms,
        )
        self._records[candidate.id] = record
        return record

    def get(self, candidate_id: str) -> CandidateRecord:
        try:
            return self._records[candidate_id]
        except KeyError as exc:
            raise KeyError(f"unknown learning candidate: {candidate_id}") from exc

    def record_decision(
        self,
        candidate_id: str,
        decision: GovernedPromotionDecision,
        *,
        candidate: LearningCandidate | None = None,
        disposition: CandidateDisposition | None = None,
        at_ms: int,
        rollback_reason: str = "",
    ) -> CandidateRecord:
        current = self.get(candidate_id)
        updated = replace(
            current,
            candidate=candidate if candidate is not None else current.candidate,
            disposition=disposition if disposition is not None else current.disposition,
            decision=decision,
            updated_at_ms=at_ms,
            rollback_reason=rollback_reason,
        )
        self._records[candidate_id] = updated
        return updated

    def records(self) -> tuple[CandidateRecord, ...]:
        """All records in stable candidate-id order."""
        return tuple(self._records[key] for key in sorted(self._records))


__all__ = [
    "CandidateConflictError",
    "CandidateDisposition",
    "CandidateRecord",
    "CandidateRegistry",
]
