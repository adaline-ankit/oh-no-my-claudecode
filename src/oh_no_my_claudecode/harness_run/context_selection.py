"""Auditable context-selection manifest for ONMC harness runs.

The retrieval engine already returns ranked evidence plus exclusions. This
module turns that packet into a compact runtime contract so context choice is
visible in plans, receipts, and run specs instead of being implicit helper
state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oh_no_my_claudecode.context_engine import EvidencePacket
from oh_no_my_claudecode.retrieval import RetrievalDecision

_SCHEMA_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ContextSelectionManifest:
    """Serializable proof of what context ONMC explored, used, and rejected."""

    policy: str
    mode: str
    explored_count: int
    used_count: int
    excluded_count: int
    used_tokens: int
    token_budget: int
    confidence: float
    low_confidence: bool
    abstained: bool
    fallback_decision: str
    fallbacks: tuple[str, ...]
    explored_context_ids: tuple[str, ...]
    used_context_ids: tuple[str, ...]
    excluded_context_ids: tuple[str, ...]
    used_provenance: tuple[str, ...]
    exclusion_reasons: tuple[tuple[str, int], ...]
    query_intent: str
    retrieval_stage: str
    lexical_floor: bool
    candidate_promoted: bool
    retrieval_fallback_reason: str
    retrieval_provenance: tuple[tuple[str, str], ...]
    schema_version: str = _SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy": self.policy,
            "mode": self.mode,
            "explored_count": self.explored_count,
            "used_count": self.used_count,
            "excluded_count": self.excluded_count,
            "used_tokens": self.used_tokens,
            "token_budget": self.token_budget,
            "confidence": self.confidence,
            "low_confidence": self.low_confidence,
            "abstained": self.abstained,
            "fallback_decision": self.fallback_decision,
            "fallbacks": list(self.fallbacks),
            "explored_context_ids": list(self.explored_context_ids),
            "used_context_ids": list(self.used_context_ids),
            "excluded_context_ids": list(self.excluded_context_ids),
            "used_provenance": list(self.used_provenance),
            "exclusion_reasons": [
                {"reason": reason, "count": count}
                for reason, count in self.exclusion_reasons
            ],
            "query_intent": self.query_intent,
            "retrieval_stage": self.retrieval_stage,
            "lexical_floor": self.lexical_floor,
            "candidate_promoted": self.candidate_promoted,
            "retrieval_fallback_reason": self.retrieval_fallback_reason,
            "retrieval_provenance": [
                {"stage": stage, "backend": backend}
                for stage, backend in self.retrieval_provenance
            ],
        }


def context_selection_manifest(
    packet: EvidencePacket,
    *,
    retrieval_fallbacks: tuple[str, ...] = (),
    retrieval_decision: RetrievalDecision | None = None,
    policy: str = "context_engine.measured-v2",
) -> ContextSelectionManifest:
    """Build the context-selection manifest bound into a harness run.

    ``explored_count`` is the packet's known decision surface: selected evidence
    plus excluded candidates. Providers that never surfaced a candidate cannot be
    counted honestly, so this number is intentionally bounded to recorded
    decisions rather than an inferred repository-wide corpus size.
    """

    exclusion_counts: dict[str, int] = {}
    for exclusion in packet.exclusions:
        exclusion_counts[exclusion.reason] = exclusion_counts.get(exclusion.reason, 0) + 1

    used_provenance: list[str] = []
    for item in packet.evidence:
        if item.citations:
            used_provenance.extend(citation.render() for citation in item.citations)
        else:
            used_provenance.append(item.candidate_id)

    used_count = len(packet.evidence)
    excluded_count = len(packet.exclusions)
    used_context_ids = tuple(item.candidate_id for item in packet.evidence)
    excluded_context_ids = tuple(item.candidate_id for item in packet.exclusions)
    mode = packet.mode.value if hasattr(packet.mode, "value") else str(packet.mode)
    query_intent = (
        retrieval_decision.query_plan.intent.value if retrieval_decision is not None else "unknown"
    )
    retrieval_stage = (
        retrieval_decision.selected_stage if retrieval_decision is not None else "unspecified"
    )
    lexical_floor = (
        retrieval_decision.query_plan.lexical_floor
        if retrieval_decision is not None
        else False
    )
    candidate_promoted = (
        retrieval_decision.candidate_promoted if retrieval_decision is not None else False
    )
    retrieval_fallback_reason = (
        retrieval_decision.fallback_reason if retrieval_decision is not None else ""
    )
    retrieval_provenance = (
        tuple((item.stage, item.backend) for item in retrieval_decision.provenance)
        if retrieval_decision is not None
        else ()
    )
    return ContextSelectionManifest(
        policy=policy,
        mode=mode,
        explored_count=used_count + excluded_count,
        used_count=used_count,
        excluded_count=excluded_count,
        used_tokens=packet.used_tokens,
        token_budget=packet.token_budget,
        confidence=packet.confidence,
        low_confidence=packet.low_confidence,
        abstained=packet.no_op or used_count == 0,
        fallback_decision="degraded" if retrieval_fallbacks else "none",
        fallbacks=tuple(retrieval_fallbacks),
        explored_context_ids=tuple(dict.fromkeys((*used_context_ids, *excluded_context_ids))),
        used_context_ids=used_context_ids,
        excluded_context_ids=excluded_context_ids,
        used_provenance=tuple(dict.fromkeys(used_provenance)),
        exclusion_reasons=tuple(sorted(exclusion_counts.items())),
        query_intent=query_intent,
        retrieval_stage=retrieval_stage,
        lexical_floor=lexical_floor,
        candidate_promoted=candidate_promoted,
        retrieval_fallback_reason=retrieval_fallback_reason,
        retrieval_provenance=retrieval_provenance,
    )


__all__ = ["ContextSelectionManifest", "context_selection_manifest"]
