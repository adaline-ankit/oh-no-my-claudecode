"""Tests for the hybrid BM25+dense+RRF retrieval module.

Covers (>=8 tests as required):
1.  BM25 correctness — top result for an exact-match query
2.  BM25 top-k cap — returns at most k results
3.  BM25 zero score exclusion — documents with zero BM25 score are excluded
4.  BM25 determinism — same query, same corpus → identical ranking
5.  RRF fusion — document appearing in both lists scores higher than either alone
6.  RRF determinism — same inputs always produce identical fused order
7.  Fallback embedder path — HybridRetriever works with explicit HashNgramEmbedder
8.  No-op on weak evidence — min_score threshold returns empty list
9.  HybridRetriever returns RetrievalHit tuples with all required fields
10. Token budget — stops accumulation after budget is exceeded
11. HybridRecallAdapter smoke — runs on the frozen dataset without crashing
12. HybridAdapter ids are subset of corpus — no phantom IDs returned
13. retrieve() convenience function matches HybridRetriever class output
14. Dense retriever zero-vector query returns empty
"""

from __future__ import annotations

from oh_no_my_claudecode.embeddings.core import HashNgramEmbedder
from oh_no_my_claudecode.retrieval.bm25 import BM25Corpus
from oh_no_my_claudecode.retrieval.core import HybridRetriever, RetrievalHit, retrieve
from oh_no_my_claudecode.retrieval.dense import DenseRetriever
from oh_no_my_claudecode.retrieval.rrf import reciprocal_rank_fusion

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_DOC_IDS = ["doc-a", "doc-b", "doc-c", "doc-d"]
_TEXTS = [
    "sqlite database locked concurrency write busy timeout",
    "FTS5 syntax error hyphen special character tokenise",
    "mypy strict type annotation import guard protocol",
    "embedding vector cosine similarity hash ngram fastembed",
]


# ---------------------------------------------------------------------------
# 1. BM25 correctness — exact-match query
# ---------------------------------------------------------------------------


class TestBM25Correctness:
    def test_exact_match_ranks_first(self) -> None:
        """A query matching a document's unique terms should rank it first."""
        bm25 = BM25Corpus(_DOC_IDS, _TEXTS)
        results = bm25.retrieve("FTS5 hyphen special", k=4)
        assert results, "Expected at least one result"
        top_doc, top_score = results[0]
        assert top_doc == "doc-b", f"Expected 'doc-b' first, got {top_doc!r}"
        assert top_score > 0.0

    def test_bm25_top_k_cap(self) -> None:
        """retrieve(k=2) must return at most 2 results."""
        bm25 = BM25Corpus(_DOC_IDS, _TEXTS)
        results = bm25.retrieve("sqlite embedding FTS5 mypy", k=2)
        assert len(results) <= 2

    def test_bm25_excludes_zero_score(self) -> None:
        """Documents with no query-term overlap should be excluded."""
        bm25 = BM25Corpus(["only-doc"], ["completely unrelated apples oranges"])
        results = bm25.retrieve("sqlite WAL", k=10)
        # No shared tokens → empty
        assert results == []

    def test_bm25_determinism(self) -> None:
        """Same query twice must produce identical ranking."""
        bm25 = BM25Corpus(_DOC_IDS, _TEXTS)
        r1 = bm25.retrieve("cosine similarity embedding vector", k=4)
        r2 = bm25.retrieve("cosine similarity embedding vector", k=4)
        assert r1 == r2, "BM25 must be deterministic"

    def test_bm25_score_method(self) -> None:
        """score() for a non-matching document must be 0."""
        bm25 = BM25Corpus(["x", "y"], ["apples oranges", "sqlite locked"])
        # Query only matches doc 'y' (index 1)
        assert bm25.score("sqlite", 0) == 0.0
        assert bm25.score("sqlite", 1) > 0.0


# ---------------------------------------------------------------------------
# 5–6. RRF fusion correctness and determinism
# ---------------------------------------------------------------------------


class TestRRF:
    def test_rrf_boosts_shared_document(self) -> None:
        """A document present in both lists should score higher than docs in only one."""
        list_a = [("doc-x", 10.0), ("doc-shared", 5.0), ("doc-y", 1.0)]
        list_b = [("doc-shared", 8.0), ("doc-z", 4.0)]
        fused = dict(reciprocal_rank_fusion([list_a, list_b]))
        # doc-shared appears in both lists; doc-x only in list_a
        assert fused["doc-shared"] > fused["doc-x"], (
            "Shared document should fuse higher than list_a-only document"
        )

    def test_rrf_determinism(self) -> None:
        """Same inputs must produce identical fused order."""
        list_a = [("a", 3.0), ("b", 2.0), ("c", 1.0)]
        list_b = [("b", 5.0), ("a", 4.0), ("d", 3.0)]
        r1 = reciprocal_rank_fusion([list_a, list_b])
        r2 = reciprocal_rank_fusion([list_a, list_b])
        assert r1 == r2

    def test_rrf_single_list_passthrough(self) -> None:
        """With one list, RRF should preserve rank order (modulo score rescaling)."""
        ranking = [("a", 9.0), ("b", 5.0), ("c", 1.0)]
        fused = reciprocal_rank_fusion([ranking])
        fused_ids = [doc_id for doc_id, _ in fused]
        assert fused_ids == ["a", "b", "c"]

    def test_rrf_empty_lists(self) -> None:
        """All-empty input must return an empty list."""
        assert reciprocal_rank_fusion([[], []]) == []


# ---------------------------------------------------------------------------
# 7. Fallback embedder path
# ---------------------------------------------------------------------------


class TestFallbackEmbedder:
    def test_hybrid_retriever_with_hash_ngram(self) -> None:
        """HybridRetriever with an explicit HashNgramEmbedder must work end-to-end."""
        embedder = HashNgramEmbedder()
        retriever = HybridRetriever(
            doc_ids=_DOC_IDS,
            texts=_TEXTS,
            embedder=embedder,
        )
        hits = retriever.retrieve("sqlite locked busy timeout", k=3)
        assert isinstance(hits, list)
        assert all(isinstance(h, RetrievalHit) for h in hits)
        # doc-a is about sqlite — should appear in results
        returned_ids = [h.doc_id for h in hits]
        assert "doc-a" in returned_ids, f"Expected 'doc-a' in results; got {returned_ids}"


# ---------------------------------------------------------------------------
# 8. No-op on weak evidence (min_score threshold)
# ---------------------------------------------------------------------------


class TestMinScoreNoOp:
    def test_min_score_returns_empty_below_threshold(self) -> None:
        """When top score is below min_score, retrieve() must return []."""
        retriever = HybridRetriever(
            doc_ids=["doc1"],
            texts=["completely irrelevant apples"],
            embedder=HashNgramEmbedder(),
            min_score=999.0,  # impossibly high threshold
        )
        hits = retriever.retrieve("sqlite WAL concurrency", k=5)
        assert hits == [], f"Expected empty result below min_score, got {hits}"

    def test_min_score_zero_passes_through(self) -> None:
        """min_score=0.0 (default) should never suppress results."""
        retriever = HybridRetriever(
            doc_ids=_DOC_IDS,
            texts=_TEXTS,
            embedder=HashNgramEmbedder(),
            min_score=0.0,
        )
        hits = retriever.retrieve("sqlite embedding", k=4)
        assert len(hits) > 0, "Expected results with min_score=0.0"


# ---------------------------------------------------------------------------
# 9. RetrievalHit fields
# ---------------------------------------------------------------------------


class TestRetrievalHitFields:
    def test_hit_has_all_required_fields(self) -> None:
        retriever = HybridRetriever(
            doc_ids=_DOC_IDS,
            texts=_TEXTS,
            evidence_texts=[f"Evidence for {d}" for d in _DOC_IDS],
            embedder=HashNgramEmbedder(),
        )
        hits = retriever.retrieve("sqlite locked", k=2)
        assert hits
        hit = hits[0]
        assert isinstance(hit.doc_id, str)
        assert isinstance(hit.score, float)
        assert isinstance(hit.evidence, str)
        assert isinstance(hit.rank, int)
        assert hit.rank >= 1

    def test_hits_rank_are_consecutive_from_one(self) -> None:
        retriever = HybridRetriever(
            doc_ids=_DOC_IDS,
            texts=_TEXTS,
            embedder=HashNgramEmbedder(),
        )
        hits = retriever.retrieve("embedding cosine", k=4)
        ranks = [h.rank for h in hits]
        assert ranks == list(range(1, len(hits) + 1))


# ---------------------------------------------------------------------------
# 10. Token budget
# ---------------------------------------------------------------------------


class TestTokenBudget:
    def test_token_budget_limits_accumulation(self) -> None:
        """With a very small token budget, only the first result should be returned."""
        retriever = HybridRetriever(
            doc_ids=_DOC_IDS,
            texts=_TEXTS,
            evidence_texts=["word " * 50 for _ in _DOC_IDS],  # 50-token evidence each
            embedder=HashNgramEmbedder(),
            token_budget=30,  # less than one evidence block
        )
        hits = retriever.retrieve("sqlite embedding", k=4)
        # Budget is too small for second result after the first.
        assert len(hits) == 1, f"Expected 1 result due to token budget, got {len(hits)}"


# ---------------------------------------------------------------------------
# 11–12. HybridRecallAdapter smoke + corpus ID constraint
# ---------------------------------------------------------------------------


class TestHybridRecallAdapter:
    def test_adapter_runs_without_crash(self) -> None:
        """HybridRecallAdapter must set up, retrieve, and tear down cleanly."""
        from oh_no_my_claudecode.retrieval.eval_adapter import HybridRecallAdapter
        from oh_no_my_claudecode.retrieval_eval.dataset import load_dataset

        dataset = load_dataset()
        adapter = HybridRecallAdapter()
        adapter.setup(dataset)
        try:
            result = adapter.retrieve("sqlite database locked concurrent write", k=5)
            assert isinstance(result, list)
            assert all(isinstance(r, str) for r in result)
            assert len(result) <= 5
        finally:
            adapter.teardown()

    def test_adapter_ids_are_in_corpus(self) -> None:
        """All returned IDs must be valid corpus entry IDs."""
        from oh_no_my_claudecode.retrieval.eval_adapter import HybridRecallAdapter
        from oh_no_my_claudecode.retrieval_eval.dataset import load_dataset

        dataset = load_dataset()
        corpus_ids = {e.id for e in dataset.corpus}
        adapter = HybridRecallAdapter()
        adapter.setup(dataset)
        try:
            result = adapter.retrieve("FTS5 MATCH syntax error hyphens", k=10)
            for rid in result:
                assert rid in corpus_ids, f"'{rid}' is not a valid corpus ID"
        finally:
            adapter.teardown()


# ---------------------------------------------------------------------------
# 13. retrieve() convenience function
# ---------------------------------------------------------------------------


class TestConvenienceFunction:
    def test_retrieve_matches_class_output(self) -> None:
        """retrieve() must return same doc_ids as HybridRetriever.retrieve()."""
        embedder = HashNgramEmbedder()
        query = "sqlite locked busy"
        k = 3

        class_hits = HybridRetriever(
            _DOC_IDS, _TEXTS, embedder=embedder
        ).retrieve(query, k)
        fn_hits = retrieve(query, k, doc_ids=_DOC_IDS, texts=_TEXTS, embedder=embedder)

        class_ids = [h.doc_id for h in class_hits]
        fn_ids = [t[0] for t in fn_hits]
        assert class_ids == fn_ids


# ---------------------------------------------------------------------------
# 14. Dense retriever — zero vector query
# ---------------------------------------------------------------------------


class TestDenseRetriever:
    def test_zero_vector_query_returns_empty(self) -> None:
        """An empty-text query embeds to the zero vector → DenseRetriever returns []."""
        embedder = HashNgramEmbedder()
        dense = DenseRetriever(["x", "y"], ["hello world", "foo bar"], embedder)
        result = dense.retrieve("", k=5)
        assert result == [], f"Expected empty list for zero-vector query, got {result}"


# ---------------------------------------------------------------------------
# Integration: run the full harness and verify report structure
# ---------------------------------------------------------------------------


class TestHarnessIntegration:
    def test_harness_produces_valid_report(self) -> None:
        """Running the harness with HybridRecallAdapter produces a structured report."""
        from oh_no_my_claudecode.retrieval.eval_adapter import HybridRecallAdapter
        from oh_no_my_claudecode.retrieval_eval.runner import run_evaluation

        report = run_evaluation([HybridRecallAdapter()])
        assert len(report.surface_reports) == 1
        sr = report.surface_reports[0]
        assert not sr.skipped, f"Adapter was unexpectedly skipped: {sr.skip_reason}"
        assert sr.surface_name == "recall"
        assert sr.n_cases == 15
        # Scores should be well-defined floats in [0, 1].
        assert 0.0 <= sr.mean_recall_at_10 <= 1.0
        assert 0.0 <= sr.mean_ndcg_at_10 <= 1.0
        assert 0.0 <= sr.mean_mrr_at_10 <= 1.0
        # Latency should be positive.
        assert sr.latency_p50_ms >= 0.0
