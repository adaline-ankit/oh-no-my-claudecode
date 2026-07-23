"""Standard information-retrieval metrics — pure, offline, deterministic.

All functions operate on ranked ID lists and a relevance mapping.  No ML
dependencies.  Each function is self-contained and unit-testable.

Metric definitions
------------------
- **Recall@k**: fraction of relevant documents that appear in the top-k results.
  recall_at_k = |retrieved_k ∩ relevant| / |relevant|

- **Precision@k**: fraction of top-k results that are relevant.
  precision_at_k = |retrieved_k ∩ relevant| / k

- **MRR@k** (Mean Reciprocal Rank): reciprocal rank of the first relevant
  document in the top-k results.  0.0 if no relevant document appears.

- **nDCG@k** (Normalised Discounted Cumulative Gain): uses graded relevance
  when provided; falls back to binary relevance otherwise.  Normalised by the
  ideal DCG for the same set of relevant documents.
"""

from __future__ import annotations

import math


def recall_at_k(
    ranked_ids: list[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    """Return the fraction of relevant documents found in the top-k results.

    Args:
        ranked_ids: Ordered list of retrieved document IDs (rank 1 = index 0).
        relevant_ids: Set of IDs that are ground-truth relevant.
        k: Cutoff rank.

    Returns:
        Float in [0.0, 1.0].  Returns 0.0 when ``relevant_ids`` is empty.
    """
    if not relevant_ids:
        return 0.0
    top_k = set(ranked_ids[:k])
    hits = top_k & relevant_ids
    return len(hits) / len(relevant_ids)


def precision_at_k(
    ranked_ids: list[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    """Return the fraction of top-k results that are relevant.

    Args:
        ranked_ids: Ordered list of retrieved document IDs.
        relevant_ids: Set of ground-truth relevant IDs.
        k: Cutoff rank.

    Returns:
        Float in [0.0, 1.0].  Returns 0.0 when ``k`` is 0.
    """
    if k <= 0:
        return 0.0
    top_k = set(ranked_ids[:k])
    hits = top_k & relevant_ids
    return len(hits) / k


def mrr_at_k(
    ranked_ids: list[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    """Return the reciprocal rank of the first relevant document in top-k.

    Args:
        ranked_ids: Ordered list of retrieved document IDs.
        relevant_ids: Set of ground-truth relevant IDs.
        k: Cutoff rank (ranks beyond k are ignored).

    Returns:
        1/rank for the first relevant document, or 0.0 if none in top-k.
    """
    for rank, doc_id in enumerate(ranked_ids[:k], start=1):
        if doc_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def _dcg(
    ranked_ids: list[str],
    relevant_ids: set[str],
    graded: dict[str, float] | None,
    k: int,
) -> float:
    """Compute Discounted Cumulative Gain at k.

    Uses graded relevance when provided, binary relevance otherwise.
    DCG = sum(rel_i / log2(i + 1)) for i in 1..k where rel_i is the
    relevance of the document at rank i (1-indexed).
    """
    gain = 0.0
    for rank, doc_id in enumerate(ranked_ids[:k], start=1):
        if graded is not None:
            rel = graded.get(doc_id, 0.0)
        else:
            rel = 1.0 if doc_id in relevant_ids else 0.0
        gain += rel / math.log2(rank + 1)
    return gain


def _ideal_dcg(
    relevant_ids: set[str],
    graded: dict[str, float] | None,
    k: int,
) -> float:
    """Compute the ideal DCG (IDCG) at k — the maximum achievable DCG."""
    if graded is not None:
        relevances = sorted(
            [graded.get(r, 0.0) for r in relevant_ids],
            reverse=True,
        )
    else:
        relevances = [1.0] * len(relevant_ids)

    ideal_gain = 0.0
    for rank, rel in enumerate(relevances[:k], start=1):
        ideal_gain += rel / math.log2(rank + 1)
    return ideal_gain


def ndcg_at_k(
    ranked_ids: list[str],
    relevant_ids: set[str],
    k: int,
    *,
    graded: dict[str, float] | None = None,
) -> float:
    """Return the Normalised Discounted Cumulative Gain at k.

    Args:
        ranked_ids: Ordered list of retrieved document IDs.
        relevant_ids: Set of ground-truth relevant IDs.
        k: Cutoff rank.
        graded: Optional mapping of doc_id to relevance grade (e.g. 1-3).
            When absent, binary relevance (0/1) is used.

    Returns:
        Float in [0.0, 1.0].  Returns 0.0 when ``relevant_ids`` is empty or
        all ideal relevances are zero.
    """
    if not relevant_ids:
        return 0.0
    idcg = _ideal_dcg(relevant_ids, graded, k)
    if idcg == 0.0:
        return 0.0
    dcg = _dcg(ranked_ids, relevant_ids, graded, k)
    return dcg / idcg
