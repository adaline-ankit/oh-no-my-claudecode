"""Promotion evidence for retrieval candidates versus the BM25 floor."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from oh_no_my_claudecode.retrieval_eval.runner import SurfaceReport


class PromotionStatus(StrEnum):
    """Outcome of the retrieval promotion gate."""

    PROMOTED = "promoted"
    REJECTED = "rejected"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True)
class RetrievalPromotionEvidence:
    """Offline, budget, provenance, and downstream evidence for one candidate."""

    baseline_surface: str
    candidate_surface: str
    status: PromotionStatus
    offline_metric: str
    offline_baseline: float
    offline_candidate: float
    offline_delta: float
    baseline_context_tokens: float
    candidate_context_tokens: float
    context_token_delta: float
    downstream_baseline: float | None
    downstream_candidate: float | None
    downstream_delta: float | None
    candidate_provenance: str
    reasons: tuple[str, ...]
    schema_version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "baseline": self.baseline_surface,
            "candidate": self.candidate_surface,
            "status": self.status.value,
            "offline_metric": self.offline_metric,
            "offline_baseline": round(self.offline_baseline, 4),
            "offline_candidate": round(self.offline_candidate, 4),
            "offline_delta": round(self.offline_delta, 4),
            "baseline_context_tokens": round(self.baseline_context_tokens, 1),
            "candidate_context_tokens": round(self.candidate_context_tokens, 1),
            "context_token_delta": round(self.context_token_delta, 1),
            "downstream_baseline": self.downstream_baseline,
            "downstream_candidate": self.downstream_candidate,
            "downstream_delta": (
                round(self.downstream_delta, 4)
                if self.downstream_delta is not None
                else None
            ),
            "candidate_provenance": self.candidate_provenance,
            "reasons": list(self.reasons),
        }


def evaluate_retrieval_candidate(
    baseline: SurfaceReport,
    candidate: SurfaceReport,
    *,
    downstream_baseline: float | None = None,
    downstream_candidate: float | None = None,
    min_offline_delta: float = 0.0,
    downstream_noninferiority_margin: float = 0.0,
) -> RetrievalPromotionEvidence:
    """Gate a retrieval candidate on offline gain and downstream non-regression."""
    offline_baseline = baseline.mean_ndcg_at_10
    offline_candidate = candidate.mean_ndcg_at_10
    offline_delta = offline_candidate - offline_baseline
    context_delta = candidate.mean_context_tokens - baseline.mean_context_tokens
    downstream_delta = (
        downstream_candidate - downstream_baseline
        if downstream_baseline is not None and downstream_candidate is not None
        else None
    )

    reasons: list[str] = []
    if candidate.skipped:
        reasons.append("candidate_skipped")
    if offline_delta <= min_offline_delta:
        reasons.append("offline_metric_not_improved")
    if downstream_delta is not None and downstream_delta < -downstream_noninferiority_margin:
        reasons.append("downstream_regression")

    if reasons:
        status = PromotionStatus.REJECTED
    elif downstream_delta is None:
        status = PromotionStatus.INSUFFICIENT_EVIDENCE
        reasons.append("downstream_evidence_missing")
    else:
        status = PromotionStatus.PROMOTED

    return RetrievalPromotionEvidence(
        baseline_surface=baseline.surface_name,
        candidate_surface=candidate.surface_name,
        status=status,
        offline_metric="ndcg@10",
        offline_baseline=offline_baseline,
        offline_candidate=offline_candidate,
        offline_delta=offline_delta,
        baseline_context_tokens=baseline.mean_context_tokens,
        candidate_context_tokens=candidate.mean_context_tokens,
        context_token_delta=context_delta,
        downstream_baseline=downstream_baseline,
        downstream_candidate=downstream_candidate,
        downstream_delta=downstream_delta,
        candidate_provenance=candidate.notes,
        reasons=tuple(reasons),
    )


__all__ = [
    "PromotionStatus",
    "RetrievalPromotionEvidence",
    "evaluate_retrieval_candidate",
]
