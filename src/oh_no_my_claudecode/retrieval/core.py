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
from typing import Any

from oh_no_my_claudecode.embeddings.core import Embedder, embeddings_enabled
from oh_no_my_claudecode.retrieval.bm25 import BM25Corpus
from oh_no_my_claudecode.retrieval.dense import DenseRetriever
from oh_no_my_claudecode.retrieval.query_plan import QueryPlan, build_query_plan
from oh_no_my_claudecode.retrieval.rerank import Reranker, apply_reranker
from oh_no_my_claudecode.retrieval.rrf import reciprocal_rank_fusion

_VALID_MODES = frozenset({"hybrid", "bm25", "dense"})


@dataclass(frozen=True)
class RetrievalHit:
    """One ranked document returned by :class:`HybridRetriever`."""

    doc_id: str
    score: float
    evidence: str  # cited text for downstream context / provenance
    rank: int  # 1-based position in the final ranked list


@dataclass(frozen=True, slots=True)
class RetrievalProvenance:
    """One retrieval stage actually explored for a measured decision."""

    stage: str
    backend: str
    result_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "backend": self.backend,
            "result_ids": list(self.result_ids),
        }


@dataclass(frozen=True, slots=True)
class RetrievalDecision:
    """Auditable result of the BM25-floor measured retrieval policy."""

    query_plan: QueryPlan
    selected_stage: str
    hits: tuple[RetrievalHit, ...]
    confidence: float
    min_candidate_confidence: float
    token_budget: int
    used_tokens: int
    abstained: bool
    fallback_reason: str
    candidate_promoted: bool
    provenance: tuple[RetrievalProvenance, ...]
    schema_version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "query_plan": self.query_plan.to_dict(),
            "selected_stage": self.selected_stage,
            "hits": [
                {
                    "doc_id": hit.doc_id,
                    "score": hit.score,
                    "evidence": hit.evidence,
                    "rank": hit.rank,
                }
                for hit in self.hits
            ],
            "confidence": self.confidence,
            "min_candidate_confidence": self.min_candidate_confidence,
            "token_budget": self.token_budget,
            "used_tokens": self.used_tokens,
            "abstained": self.abstained,
            "fallback_reason": self.fallback_reason,
            "candidate_promoted": self.candidate_promoted,
            "provenance": [item.to_dict() for item in self.provenance],
        }


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
        self._texts: list[str] = list(texts)
        self._evidence_texts: list[str] = (
            list(evidence_texts) if evidence_texts is not None else list(texts)
        )
        self._embedder = embedder
        self._rrf_k = rrf_k
        self._min_score = min_score
        self._token_budget = token_budget

        # Fast index: doc_id → position.
        self._id_to_idx: dict[str, int] = {d: i for i, d in enumerate(self._doc_ids)}

        # Sub-retrievers (index built once here).
        self._bm25 = BM25Corpus(doc_ids, texts)
        # Dense construction may load an optional local model.  Keep it lazy so
        # the BM25 production floor never initializes an unselected dependency.
        self._dense: DenseRetriever | None = None

    @property
    def embedder_id(self) -> str:
        """Stable ID of the dense embedder for provenance reporting."""
        return self._dense_retriever().embedder_id

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
            ranked = self._dense_retriever().retrieve(query, n)
        else:  # hybrid
            bm25_ranked = self._bm25.retrieve(query, n)
            dense_ranked = self._dense_retriever().retrieve(query, n)
            ranked = reciprocal_rank_fusion(
                [bm25_ranked, dense_ranked], rrf_k=self._rrf_k
            )

        hits, _used = self._pack(
            ranked,
            k=k,
            token_budget=self._token_budget,
            allow_oversized_first=True,
        )
        return list(hits)

    def retrieve_measured(
        self,
        query: str,
        k: int,
        *,
        requested_mode: str = "bm25",
        candidate_promoted: bool = False,
        min_candidate_confidence: float = 0.65,
        token_budget: int,
        reranker: Reranker | None = None,
    ) -> RetrievalDecision:
        """Run the lexical floor plus eligible candidate stages.

        Candidate results are explored and attributed, but they replace BM25
        only for conceptual queries after an explicit promotion decision and a
        query-level confidence pass.  The token budget is a hard gate here:
        unlike the legacy raw ``retrieve`` API, an oversized first item is
        omitted rather than allowed to overrun the budget.
        """
        if not 0.0 <= min_candidate_confidence <= 1.0:
            raise ValueError("min_candidate_confidence must be between 0 and 1")
        plan = build_query_plan(
            query,
            requested_mode=requested_mode,
            k=k,
            token_budget=token_budget,
            dense_available=embeddings_enabled(),
            reranker_available=reranker is not None,
        )

        n = len(self._doc_ids)
        bm25_ranked = self._bm25.retrieve(query, n)
        bm25_hits, bm25_tokens = self._pack(
            bm25_ranked,
            k=k,
            token_budget=token_budget,
            allow_oversized_first=False,
        )
        provenance: list[RetrievalProvenance] = [
            RetrievalProvenance(
                stage="bm25",
                backend="okapi-bm25",
                result_ids=tuple(doc_id for doc_id, _score in bm25_ranked[:k]),
            )
        ]
        selected_stage = "bm25"
        selected_hits = bm25_hits
        used_tokens = bm25_tokens
        confidence = _bm25_confidence(bm25_ranked)
        fallback_reason = ""

        if plan.candidate_stages:
            dense = self._dense_retriever()
            dense_ranked = dense.retrieve(query, n)
            provenance.append(
                RetrievalProvenance(
                    stage="dense",
                    backend=dense.embedder_id,
                    result_ids=tuple(doc_id for doc_id, _score in dense_ranked[:k]),
                )
            )
            candidate_ranked = dense_ranked
            candidate_stage = "dense"
            if "rrf" in plan.candidate_stages:
                candidate_ranked = reciprocal_rank_fusion(
                    [bm25_ranked, dense_ranked], rrf_k=self._rrf_k
                )
                candidate_stage = "hybrid"
                provenance.append(
                    RetrievalProvenance(
                        stage="rrf",
                        backend=f"rrf-k{self._rrf_k}",
                        result_ids=tuple(
                            doc_id for doc_id, _score in candidate_ranked[:k]
                        ),
                    )
                )
            if "rerank" in plan.candidate_stages and reranker is not None:
                candidate_ranked = apply_reranker(
                    reranker,
                    query,
                    candidate_ranked,
                    dict(zip(self._doc_ids, self._texts, strict=True)),
                )
                candidate_stage = f"{candidate_stage}+rerank"
                provenance.append(
                    RetrievalProvenance(
                        stage="rerank",
                        backend=reranker.reranker_id,
                        result_ids=tuple(
                            doc_id for doc_id, _score in candidate_ranked[:k]
                        ),
                    )
                )

            candidate_hits, candidate_tokens = self._pack(
                candidate_ranked,
                k=k,
                token_budget=token_budget,
                allow_oversized_first=False,
            )
            candidate_confidence = _dense_confidence(dense_ranked)
            if not candidate_promoted:
                fallback_reason = "candidate_not_promoted"
            elif candidate_confidence < min_candidate_confidence:
                fallback_reason = "candidate_low_confidence"
            elif not candidate_hits:
                fallback_reason = "candidate_token_budget_exhausted"
            else:
                selected_stage = candidate_stage
                selected_hits = candidate_hits
                used_tokens = candidate_tokens
                confidence = candidate_confidence
        elif requested_mode != "bm25":
            reasons = {reason for _stage, reason in plan.suppressed_stages}
            fallback_reason = (
                "lexical_dominant_query"
                if "lexical_dominant_query" in reasons
                else "candidate_dependency_unavailable"
            )

        if not selected_hits:
            fallback_reason = (
                "token_budget_exhausted"
                if bm25_ranked and token_budget >= 0
                else fallback_reason or "no_relevant_context"
            )

        return RetrievalDecision(
            query_plan=plan,
            selected_stage=selected_stage,
            hits=selected_hits,
            confidence=round(confidence, 6),
            min_candidate_confidence=min_candidate_confidence,
            token_budget=token_budget,
            used_tokens=used_tokens,
            abstained=not selected_hits,
            fallback_reason=fallback_reason,
            candidate_promoted=candidate_promoted,
            provenance=tuple(provenance),
        )

    def _dense_retriever(self) -> DenseRetriever:
        dense = self._dense
        if dense is None:
            dense = DenseRetriever(self._doc_ids, self._texts, self._embedder)
            self._dense = dense
        return dense

    def _pack(
        self,
        ranked: list[tuple[str, float]],
        *,
        k: int,
        token_budget: int | None,
        allow_oversized_first: bool,
    ) -> tuple[tuple[RetrievalHit, ...], int]:
        if not ranked:
            return (), 0
        top_score = ranked[0][1]
        if self._min_score > 0.0 and top_score < self._min_score:
            return (), 0

        hits: list[RetrievalHit] = []
        accumulated_tokens = 0
        for doc_id, score in ranked[:k]:
            idx = self._id_to_idx.get(doc_id, -1)
            evidence = self._evidence_texts[idx] if idx >= 0 else ""
            evidence_tokens = len(evidence.split())
            if (
                token_budget is not None
                and accumulated_tokens + evidence_tokens > token_budget
                and (hits or not allow_oversized_first)
            ):
                break
            accumulated_tokens += evidence_tokens
            hits.append(
                RetrievalHit(
                    doc_id=doc_id,
                    score=score,
                    evidence=evidence,
                    rank=len(hits) + 1,
                )
            )
        return tuple(hits), accumulated_tokens


def _bm25_confidence(ranking: list[tuple[str, float]]) -> float:
    if not ranking:
        return 0.0
    top = max(0.0, ranking[0][1])
    return min(1.0, top / (top + 1.0))


def _dense_confidence(ranking: list[tuple[str, float]]) -> float:
    if not ranking:
        return 0.0
    top = max(0.0, min(1.0, ranking[0][1]))
    second = max(0.0, min(1.0, ranking[1][1])) if len(ranking) > 1 else 0.0
    margin = max(0.0, top - second)
    return min(1.0, 0.85 * top + 0.15 * margin)


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
