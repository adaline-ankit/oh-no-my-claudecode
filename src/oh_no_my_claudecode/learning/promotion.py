"""Governed promotion service for prediction-backed, reversible learning."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from oh_no_my_claudecode.experiment.contracts import CandidateState, MetricLabel

from .candidate_registry import (
    CandidateDisposition,
    CandidateRecord,
    CandidateRegistry,
)
from .gate import AdvanceEvent, PromotionGate, advance, rollback
from .models import LearningCandidate, ShadowEvaluation
from .prediction import PromotionPrediction


@dataclass(frozen=True, slots=True)
class PromotionManifest:
    """Frozen evidence required before a candidate may leave quarantine."""

    prediction: PromotionPrediction | None = None
    dataset_revision: str = ""
    held_out_result: ShadowEvaluation | None = None
    protected_non_regression: bool = False
    rollback_pointer: str = ""
    schema_version: str = "1"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "prediction": self.prediction.to_dict() if self.prediction else None,
            "dataset_revision": self.dataset_revision,
            "held_out_result": (
                self.held_out_result.to_dict() if self.held_out_result else None
            ),
            "protected_non_regression": self.protected_non_regression,
            "rollback_pointer": self.rollback_pointer,
        }

    def digest(self, candidate: LearningCandidate) -> str:
        """Content address the candidate and its pre-registered manifest."""
        payload = {
            "candidate": candidate.to_dict(),
            "manifest": self.to_dict(),
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class GovernedPromotionDecision:
    """Audit result; an ineligible result always leaves the record quarantined."""

    eligible: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {"eligible": self.eligible, "reasons": list(self.reasons)}


@dataclass(frozen=True, slots=True)
class GovernedPromotionGate:
    """Require prediction, frozen data, held-out gain, protection, and rollback."""

    learning_enabled: bool = True

    def evaluate(
        self,
        candidate: LearningCandidate,
        manifest: PromotionManifest,
    ) -> GovernedPromotionDecision:
        reasons: list[str] = []

        if not self.learning_enabled:
            reasons.append("learning-disabled")
        if candidate.state is not CandidateState.SHADOW_EVALUATED:
            reasons.append("candidate-not-shadow-evaluated")
        if candidate.provenance.is_empty:
            reasons.append("provenance-missing")
        if candidate.scope.is_empty:
            reasons.append("scope-missing")

        prediction = manifest.prediction
        if prediction is None:
            reasons.append("prediction-missing")
        if not manifest.dataset_revision.strip():
            reasons.append("dataset-revision-missing")
        if not manifest.protected_non_regression:
            reasons.append("protected-non-regression-missing")
        if not manifest.rollback_pointer.strip():
            reasons.append("rollback-pointer-missing")

        result = manifest.held_out_result
        if result is None:
            reasons.append("held-out-result-missing")
        else:
            if not result.held_out:
                reasons.append("result-not-held-out")
            if result.metric_label is not MetricLabel.MEASURED:
                reasons.append("held-out-result-not-measured")
            if not result.protected_suite_passed:
                reasons.append("protected-suite-regression")
            if candidate.evaluation != result:
                reasons.append("candidate-result-mismatch")
            if prediction is not None and result.delta <= prediction.minimum_effect:
                reasons.append("held-out-improvement-below-prediction")

        return GovernedPromotionDecision(eligible=not reasons, reasons=tuple(reasons))


class GovernedPromotionService:
    """Atomic registry facade: quarantine, evaluate, promote, or roll back."""

    def __init__(
        self,
        registry: CandidateRegistry,
        *,
        gate: GovernedPromotionGate | None = None,
    ) -> None:
        self._registry = registry
        self._gate = gate if gate is not None else GovernedPromotionGate()

    def promote(
        self,
        candidate: LearningCandidate,
        manifest: PromotionManifest,
        *,
        at_ms: int,
        reason: str = "",
    ) -> CandidateRecord:
        """Promote only after the complete governed manifest passes."""
        record = self._registry.register(candidate, manifest, at_ms=at_ms)
        if record.disposition is not CandidateDisposition.QUARANTINED:
            return record

        decision = self._gate.evaluate(record.candidate, record.manifest)
        if not decision.eligible:
            return self._registry.record_decision(
                candidate.id,
                decision,
                at_ms=at_ms,
            )

        prediction = record.manifest.prediction
        assert prediction is not None  # guaranteed by the governed gate  # noqa: S101
        promoted = advance(
            record.candidate,
            AdvanceEvent(to=CandidateState.PROMOTED, at_ms=at_ms, reason=reason),
            gate=PromotionGate(
                min_improvement=prediction.minimum_effect,
                learning_enabled=self._gate.learning_enabled,
            ),
        )
        return self._registry.record_decision(
            candidate.id,
            decision,
            candidate=promoted,
            disposition=CandidateDisposition.PROMOTED,
            at_ms=at_ms,
        )

    def rollback(
        self,
        candidate_id: str,
        *,
        at_ms: int,
        reason: str,
    ) -> CandidateRecord:
        """Deactivate a candidate without deleting its governance evidence."""
        record = self._registry.get(candidate_id)
        if record.disposition is CandidateDisposition.ROLLED_BACK:
            return record
        reversed_candidate = rollback(record.candidate, at_ms=at_ms, reason=reason)
        decision = record.decision or GovernedPromotionDecision(
            eligible=False,
            reasons=("rolled-back-before-promotion",),
        )
        return self._registry.record_decision(
            candidate_id,
            decision,
            candidate=reversed_candidate,
            disposition=CandidateDisposition.ROLLED_BACK,
            at_ms=at_ms,
            rollback_reason=reason,
        )


__all__ = [
    "GovernedPromotionDecision",
    "GovernedPromotionGate",
    "GovernedPromotionService",
    "PromotionManifest",
]
