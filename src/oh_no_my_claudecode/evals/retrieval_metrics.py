"""Retrieval quality, measured — the IR metrics R3 was missing.

R3 gives ONMC hierarchical retrieval interfaces (repo/file/symbol); this
scores how good a ranking actually is against a labeled relevant set, with the
standard information-retrieval metrics an interviewer expects to see named
correctly:

    recall@k       fraction of relevant items found in the top k
    precision@k    fraction of the top k that are relevant
    mrr            mean reciprocal rank of the first relevant hit
    ndcg@k         rank-discounted gain vs the ideal ordering (graded)

nDCG accepts graded relevance (0..n), the rest treat any positive grade as
relevant. Deterministic, offline, no numpy — the math is small and the edge
cases (k>len, no relevant items, all-zero grades) are handled explicitly
because a metric that returns a plausible-but-wrong number is worse than none.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import log2


def recall_at_k(ranking: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    hits = sum(1 for item in ranking[:k] if item in relevant)
    return hits / len(relevant)


def precision_at_k(ranking: Sequence[str], relevant: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top = ranking[:k]
    if not top:
        return 0.0
    return sum(1 for item in top if item in relevant) / len(top)


def reciprocal_rank(ranking: Sequence[str], relevant: set[str]) -> float:
    for index, item in enumerate(ranking, start=1):
        if item in relevant:
            return 1.0 / index
    return 0.0


def _dcg(gains: Sequence[float]) -> float:
    # Standard DCG: gain_i / log2(i+1), i 1-indexed.
    return sum(gain / log2(index + 1) for index, gain in enumerate(gains, start=1))


def ndcg_at_k(ranking: Sequence[str], grades: Mapping[str, float], k: int) -> float:
    """Graded nDCG@k. ``grades`` maps item id -> relevance grade (0 = irrelevant)."""
    gains = [grades.get(item, 0.0) for item in ranking[:k]]
    ideal = sorted((g for g in grades.values() if g > 0), reverse=True)[:k]
    ideal_dcg = _dcg(ideal)
    if ideal_dcg == 0.0:  # nothing relevant exists -> nDCG undefined, report 0
        return 0.0
    return _dcg(gains) / ideal_dcg


@dataclass(frozen=True, slots=True)
class RetrievalScore:
    """One query's scorecard across the standard metrics."""

    recall_at_k: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float
    k: int

    def to_dict(self) -> dict[str, object]:
        return {
            "recall_at_k": round(self.recall_at_k, 4),
            "precision_at_k": round(self.precision_at_k, 4),
            "mrr": round(self.mrr, 4),
            "ndcg_at_k": round(self.ndcg_at_k, 4),
            "k": self.k,
        }


def score_ranking(
    ranking: Sequence[str],
    grades: Mapping[str, float],
    *,
    k: int = 10,
) -> RetrievalScore:
    """Score one ranking against graded relevance. Positive grade = relevant."""
    relevant = {item for item, grade in grades.items() if grade > 0}
    return RetrievalScore(
        recall_at_k=recall_at_k(ranking, relevant, k),
        precision_at_k=precision_at_k(ranking, relevant, k),
        mrr=reciprocal_rank(ranking, relevant),
        ndcg_at_k=ndcg_at_k(ranking, grades, k),
        k=k,
    )


def mean_scores(scores: Sequence[RetrievalScore]) -> RetrievalScore:
    """Macro-average a batch of per-query scores (all sharing one k)."""
    if not scores:
        raise ValueError("cannot average an empty score list")
    n = len(scores)
    return RetrievalScore(
        recall_at_k=sum(s.recall_at_k for s in scores) / n,
        precision_at_k=sum(s.precision_at_k for s in scores) / n,
        mrr=sum(s.mrr for s in scores) / n,
        ndcg_at_k=sum(s.ndcg_at_k for s in scores) / n,
        k=scores[0].k,
    )


__all__ = [
    "RetrievalScore",
    "mean_scores",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
    "score_ranking",
]
