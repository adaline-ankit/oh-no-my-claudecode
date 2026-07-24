"""Reciprocal Rank Fusion (RRF) — deterministic linear combination of ranked lists.

Standard formula from Cormack et al., SIGIR 2009:

  RRF_score(d) = sum_i  1 / (rrf_k + rank_i(d))

where:
  - ``rank_i(d)`` is the 1-based rank of document ``d`` in the i-th list.
  - Documents absent from a list contribute 0 (not penalised by ∞ rank).
  - ``rrf_k = 60`` is the smoothing constant from the original paper.

Properties:
  - Fully deterministic: no randomness or floating-point instability.
  - Monotone: a document retrieved higher in ANY input list always scores
    at least as well as one ranked lower in all lists.
  - Handles missing documents gracefully (no appearance → no contribution).
"""

from __future__ import annotations


def reciprocal_rank_fusion(
    rankings: list[list[tuple[str, float]]],
    *,
    rrf_k: int = 60,
) -> list[tuple[str, float]]:
    """Fuse multiple ranked lists via Reciprocal Rank Fusion.

    Parameters
    ----------
    rankings:
        Each element is an ordered list of ``(doc_id, score)`` pairs from one
        retrieval method.  Only the rank order matters; per-method scores are
        ignored during fusion.
    rrf_k:
        Smoothing constant (default 60, per Cormack et al.).  Higher values
        reduce the influence of top-ranked documents; lower values amplify it.

    Returns
    -------
    A merged list of ``(doc_id, rrf_score)`` pairs, sorted descending by RRF
    score.  Ties are broken by doc_id lexicographic order for determinism.

    Examples
    --------
    >>> bm25 = [("a", 5.0), ("b", 3.0), ("c", 1.0)]
    >>> dense = [("b", 0.9), ("a", 0.8), ("d", 0.7)]
    >>> fused = reciprocal_rank_fusion([bm25, dense])
    >>> [doc_id for doc_id, _ in fused[:2]]
    ['a', 'b']
    """
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank_0based, (doc_id, _score) in enumerate(ranking):
            rank_1based = rank_0based + 1
            contribution = 1.0 / (rrf_k + rank_1based)
            fused[doc_id] = fused.get(doc_id, 0.0) + contribution

    # Sort: primary = rrf_score descending, secondary = doc_id ascending.
    return sorted(fused.items(), key=lambda x: (-x[1], x[0]))
