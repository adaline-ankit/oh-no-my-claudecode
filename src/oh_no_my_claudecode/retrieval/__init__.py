"""Hybrid BM25 + dense + RRF retrieval module.

Public API
----------

:class:`HybridRetriever`
    Build the index once; call ``retrieve(query, k)`` many times.

:class:`RetrievalHit`
    Single ranked result (doc_id, score, evidence, rank).

:func:`retrieve`
    One-shot convenience wrapper for single-query use.

:class:`BM25Corpus`
    Standalone BM25 index (pure Python, zero dependencies).

:class:`DenseRetriever`
    Dense embedding retriever (FastEmbed / sentence-transformers / hash-ngram).

:func:`reciprocal_rank_fusion`
    Raw RRF combiner for arbitrary ranked lists.

:func:`fastembed_info`
    Returns a dict with FastEmbed availability and model metadata when in use.

All components are offline, deterministic, and require no LLM calls.
"""

from __future__ import annotations

from oh_no_my_claudecode.retrieval.bm25 import BM25Corpus, tokenize
from oh_no_my_claudecode.retrieval.core import HybridRetriever, RetrievalHit, retrieve
from oh_no_my_claudecode.retrieval.dense import DenseRetriever
from oh_no_my_claudecode.retrieval.rrf import reciprocal_rank_fusion


def fastembed_info() -> dict[str, object]:
    """Return metadata about the FastEmbed backend.

    Returns a dict with:
      ``available`` (bool) — whether ``fastembed`` can be imported.
      ``selected``  (bool) — whether the env var selects it (ONMC_EMBEDDER=fastembed).
      ``model``     (str | None) — model name when selected and available.
      ``version``   (str | None) — fastembed package version when available.
    """
    from oh_no_my_claudecode.embeddings.core import fastembed_available, fastembed_selected

    available = fastembed_available()
    selected = fastembed_selected()
    model: str | None = None
    version: str | None = None

    if available:
        try:
            import fastembed  # noqa: PLC0415

            version = str(getattr(fastembed, "__version__", "unknown"))
        except Exception:  # noqa: BLE001
            version = None

    if selected and available:
        # The default model used by _try_fastembed in embeddings/core.py.
        model = "BAAI/bge-small-en-v1.5"

    return {
        "available": available,
        "selected": selected,
        "model": model,
        "version": version,
    }


__all__ = [
    "BM25Corpus",
    "DenseRetriever",
    "HybridRetriever",
    "RetrievalHit",
    "fastembed_info",
    "reciprocal_rank_fusion",
    "retrieve",
    "tokenize",
]
