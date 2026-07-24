"""Hybrid BM25 + dense + RRF retrieval core.

A single ``retrieve()`` entry point composing:

  BM25   → lexical ranked list (exact term-frequency matching)
  Dense  → semantic ranked list (embedding cosine similarity)
  RRF    → Reciprocal Rank Fusion of the two lists

Optional modifiers:
  ``mode="bm25"``    — lexical only.
  ``mode="dense"``   — semantic only.
  ``mode="hybrid"``  — BM25 + dense + RRF (default).

Constraints:
  ``min_score``   — explicit no-op: returns [] when top fused score < threshold.
  ``token_budget``— stops appending results once accumulated evidence tokens
                    exceed the budget (downstream context-window awareness).

Everything is offline, deterministic, and requires no LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from oh_no_my_claudecode.embeddings.core import Embedder
from oh_no_my_claudecode.retrieval.bm25 import BM25Corpus
from oh_no_my_claudecode.retrieval.dense import DenseRetriever
from oh_no_my_claudecode.retrieval.rrf import reciprocal_rank_fusion

_VALID_MODES = frozenset({"hybrid", "bm25", "dense"})


@dataclass(frozen=True)
class RetrievalHit:
    """One ranked document returned by :class:`HybridRetriever`."""

    doc_id: str
    score: float
    evidence: str  # cited text for downstream context / provenance
    rank: int  # 1-based position in the final ranked list


class HybridRetriever:
    """Offline, deterministic hybrid retriever over a fixed in-memory corpus.

    Build the index once on construction; call :meth:`retrieve` many times.

    Parameters
    ----------
    doc_ids:
        Ordered document identifiers (parallel to ``texts``).
    texts:
        Full document text used for both BM25 and dense indexing
        (recommended: concatenate title + summary + details + tags).
    evidence_texts:
        Short citation text surfaced in :attr:`RetrievalHit.evidence`.
        Defaults to ``texts`` when omitted.
    embedder:
        Explicit embedder override.  ``None`` → :func:`get_embedder`
        (FastEmbed > sentence-transformers > HashNgramEmbedder).
    rrf_k:
        RRF smoothing constant (default 60).
    min_score:
        Minimum fused score for the top result.  When the top result falls
        below this threshold the call returns ``[]`` (no-op / no evidence).
    token_budget:
        Maximum total evidence-token count before stopping accumulation.
        ``None`` → no limit.
    """

    def __init__(
        self,
        doc_ids: list[str],
        texts: list[str],
        evidence_texts: list[str] | None = None,
        *,
        embedder: Embedder | None = None,
        rrf_k: int = 60,
        min_score: float = 0.0,
        token_budget: int | None = None,
    ) -> None:
        if len(doc_ids) != len(texts):
            msg = (
                f"doc_ids and texts must be the same length; "
                f"got {len(doc_ids)} vs {len(texts)}"
            )
            raise ValueError(msg)
        if evidence_texts is not None and len(evidence_texts) != len(doc_ids):
            msg = (
                f"evidence_texts must match doc_ids length; "
                f"got {len(evidence_texts)} vs {len(doc_ids)}"
            )
            raise ValueError(msg)

        self._doc_ids: list[str] = list(doc_ids)
        self._evidence_texts: list[str] = (
            list(evidence_texts) if evidence_texts is not None else list(texts)
        )
        self._rrf_k = rrf_k
        self._min_score = min_score
        self._token_budget = token_budget

        # Fast index: doc_id → position.
        self._id_to_idx: dict[str, int] = {d: i for i, d in enumerate(self._doc_ids)}

        # Sub-retrievers (index built once here).
        self._bm25 = BM25Corpus(doc_ids, texts)
        self._dense = DenseRetriever(doc_ids, texts, embedder)

    @property
    def embedder_id(self) -> str:
        """Stable ID of the dense embedder for provenance reporting."""
        return self._dense.embedder_id

    @property
    def corpus_size(self) -> int:
        """Number of documents indexed."""
        return len(self._doc_ids)

    def retrieve(
        self,
        query: str,
        k: int,
        *,
        mode: str = "hybrid",
    ) -> list[RetrievalHit]:
        """Retrieve up to *k* documents for *query*.

        Parameters
        ----------
        query:
            The retrieval query string.
        k:
            Maximum number of results to return.
        mode:
            ``"hybrid"`` (default) — BM25 + dense + RRF.
            ``"bm25"`` — BM25 only.
            ``"dense"`` — dense only.

        Returns
        -------
        List of :class:`RetrievalHit` sorted by score descending, respecting
        ``min_score`` and ``token_budget`` constraints.

        Raises
        ------
        ValueError
            When ``mode`` is not one of ``"hybrid"``, ``"bm25"``, ``"dense"``.
        """
        if mode not in _VALID_MODES:
            msg = f"Unknown mode {mode!r}; expected one of {sorted(_VALID_MODES)}"
            raise ValueError(msg)

        n = len(self._doc_ids)

        if mode == "bm25":
            ranked: list[tuple[str, float]] = self._bm25.retrieve(query, n)
        elif mode == "dense":
            ranked = self._dense.retrieve(query, n)
        else:  # hybrid
            bm25_ranked = self._bm25.retrieve(query, n)
            dense_ranked = self._dense.retrieve(query, n)
            ranked = reciprocal_rank_fusion(
                [bm25_ranked, dense_ranked], rrf_k=self._rrf_k
            )

        if not ranked:
            return []

        # No-op threshold: if the top score is below min_score, signal "no evidence".
        top_score = ranked[0][1]
        if self._min_score > 0.0 and top_score < self._min_score:
            return []

        # Pack results, respecting the optional token budget.
        hits: list[RetrievalHit] = []
        accumulated_tokens = 0

        for rank_0based, (doc_id, score) in enumerate(ranked[:k]):
            idx = self._id_to_idx.get(doc_id, -1)
            evidence = self._evidence_texts[idx] if idx >= 0 else ""

            # Token-budget check (whitespace-split token count as a proxy).
            if self._token_budget is not None:
                ev_tokens = len(evidence.split())
                if accumulated_tokens + ev_tokens > self._token_budget and hits:
                    # Budget exhausted; at least one result already collected.
                    break
                accumulated_tokens += ev_tokens

            hits.append(
                RetrievalHit(
                    doc_id=doc_id,
                    score=score,
                    evidence=evidence,
                    rank=rank_0based + 1,
                )
            )

        return hits


def retrieve(
    query: str,
    k: int,
    *,
    doc_ids: list[str],
    texts: list[str],
    evidence_texts: list[str] | None = None,
    embedder: Embedder | None = None,
    mode: str = "hybrid",
    rrf_k: int = 60,
    min_score: float = 0.0,
    token_budget: int | None = None,
) -> list[tuple[str, float, str]]:
    """One-shot hybrid retrieval over an in-memory corpus.

    Convenience wrapper for callers that don't need a persistent index.  For
    repeated queries over the same corpus, instantiate :class:`HybridRetriever`
    directly so the index is built only once.

    Returns
    -------
    List of ``(doc_id, score, evidence)`` tuples, sorted by score descending.
    """
    retriever = HybridRetriever(
        doc_ids=doc_ids,
        texts=texts,
        evidence_texts=evidence_texts,
        embedder=embedder,
        rrf_k=rrf_k,
        min_score=min_score,
        token_budget=token_budget,
    )
    hits = retriever.retrieve(query, k, mode=mode)
    return [(h.doc_id, h.score, h.evidence) for h in hits]
