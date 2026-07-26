from __future__ import annotations

from dataclasses import replace

import pytest

from oh_no_my_claudecode.context_engine import (
    Candidate,
    ContextEngine,
    Evidence,
    PlannerConfig,
    RetrievalMode,
    ScoreSignals,
    StaticCandidateProvider,
    StaticGraphProvider,
)
from oh_no_my_claudecode.embeddings.core import EmbeddingVector
from oh_no_my_claudecode.retrieval import HybridRetriever
from oh_no_my_claudecode.retrieval.query_plan import QueryIntent, build_query_plan


class _ConceptEmbedder:
    """Tiny deterministic semantic backend for policy tests."""

    @property
    def embedder_id(self) -> str:
        return "test/concept-v1"

    @property
    def dim(self) -> int:
        return 2

    def embed(self, text: str) -> EmbeddingVector:
        if "capability boundary" in text or text.strip() == "authorization architecture":
            return [1.0, 0.0]
        return [0.0, 1.0]


def test_evidence_rejects_duplicate_metadata_keys() -> None:
    with pytest.raises(ValueError, match="metadata keys must be unique"):
        Evidence(
            candidate_id="duplicate",
            content="content",
            token_count=1,
            score=1.0,
            context_roi=1.0,
            graph_depth=None,
            signals=ScoreSignals(1.0, 0.0, 0.0, 0.0, None, 1.0),
            citations=(),
            metadata=(("path", "first"), ("path", "second")),
        )


def candidate(
    candidate_id: str,
    content: str,
    *,
    tokens: int = 10,
    source: str | None = None,
    freshness: float = 1.0,
    structural: float = 0.0,
    history: float = 0.0,
    memory: float = 0.0,
    semantic: float | None = None,
) -> Candidate:
    return Candidate(
        id=candidate_id,
        content=content,
        source=source or candidate_id,
        token_count=tokens,
        provenance=(f"index:{candidate_id}",),
        freshness=freshness,
        structural_score=structural,
        history_score=history,
        memory_score=memory,
        semantic_score=semantic,
    )


def test_local_ranking_prefers_exact_lexical_evidence() -> None:
    candidates = [
        candidate("semantic", "generic architecture implementation", semantic=1.0),
        candidate("exact", "deterministic hybrid retrieval planner", semantic=0.1),
        candidate("partial", "hybrid cache", semantic=0.8),
    ]

    packet = ContextEngine().plan(
        "deterministic hybrid retrieval planner",
        candidates=candidates,
        mode=RetrievalMode.LOCAL,
        token_budget=100,
    )

    assert [item.candidate_id for item in packet.evidence] == ["exact", "partial"]
    assert packet.evidence[0].signals.lexical == 1.0
    assert packet.evidence[0].citations[0].source == "exact"


def test_mode_weights_select_the_matching_signal() -> None:
    candidates = [
        candidate("structure", "target helper", structural=1.0),
        candidate("history", "target helper", history=1.0),
        candidate("memory", "target helper", memory=1.0),
    ]
    engine = ContextEngine(PlannerConfig(min_context_roi=0.0))

    impact = engine.plan("target", candidates=candidates, mode="impact", token_budget=10)
    historical = engine.plan("target", candidates=candidates, mode="history", token_budget=10)
    global_packet = engine.plan("target", candidates=candidates, mode="global", token_budget=10)

    assert impact.evidence[0].candidate_id == "structure"
    assert historical.evidence[0].candidate_id == "history"
    assert global_packet.evidence[0].candidate_id == "memory"


def test_budget_packing_skips_oversized_items_and_records_exclusions() -> None:
    candidates = [
        candidate("large", "budget planner exact", tokens=30),
        candidate("small", "budget planner", tokens=8),
        candidate("tiny", "budget", tokens=2),
    ]

    packet = ContextEngine(PlannerConfig(min_context_roi=0.0)).plan(
        "budget planner exact", candidates=candidates, token_budget=10
    )

    assert [item.candidate_id for item in packet.evidence] == ["small", "tiny"]
    assert packet.used_tokens == 10
    assert packet.exclusion_for("large").reason == "token_budget"


def test_result_is_deterministic_across_candidate_and_graph_order() -> None:
    alpha = candidate("alpha", "graph target", structural=0.5)
    beta = candidate("beta", "graph target", structural=0.5)
    graph_a = StaticGraphProvider({"alpha": ["beta"], "beta": ["alpha"]})
    graph_b = StaticGraphProvider({"beta": ["alpha"], "alpha": ["beta"]})

    first = ContextEngine(graph_provider=graph_a).plan(
        "graph target", candidates=[beta, alpha], mode="impact", token_budget=30
    )
    second = ContextEngine(graph_provider=graph_b).plan(
        "graph target", candidates=[alpha, beta], mode="impact", token_budget=30
    )

    assert first.to_dict() == second.to_dict()


def test_stale_and_unprovenanced_candidates_are_excluded() -> None:
    fresh = candidate("fresh", "retrieval target", freshness=0.9)
    stale = candidate("stale", "retrieval target", freshness=0.1)
    unknown = replace(candidate("unknown", "retrieval target"), provenance=())

    packet = ContextEngine(PlannerConfig(min_freshness=0.25)).plan(
        "retrieval target", candidates=[unknown, stale, fresh], token_budget=100
    )

    assert [item.candidate_id for item in packet.evidence] == ["fresh"]
    assert packet.exclusion_for("stale").reason == "stale"
    assert packet.exclusion_for("unknown").reason == "missing_provenance"


def test_deduplication_keeps_best_item_and_merges_citations() -> None:
    weaker = candidate("b", "Same   evidence", source="docs/b.md", memory=0.2)
    stronger = candidate("a", "same evidence", source="src/a.py", memory=0.9)

    packet = ContextEngine(PlannerConfig(min_context_roi=0.0)).plan(
        "same evidence", candidates=[weaker, stronger], mode="global", token_budget=100
    )

    assert [item.candidate_id for item in packet.evidence] == ["a"]
    assert [citation.source for citation in packet.evidence[0].citations] == [
        "docs/b.md",
        "src/a.py",
    ]
    assert packet.exclusion_for("b").reason == "duplicate"


def test_context_roi_threshold_returns_an_explicit_no_op_packet() -> None:
    low_value = candidate("weak", "unrelated material", tokens=1000, semantic=0.01)

    packet = ContextEngine(PlannerConfig(min_context_roi=0.01)).plan(
        "target", candidates=[low_value], mode="global", token_budget=2000
    )

    assert packet.no_op is True
    assert packet.evidence == ()
    assert packet.exclusion_for("weak").reason == "below_roi"


def test_drift_expands_graph_in_bounded_breadth_first_order() -> None:
    candidates = [
        candidate("seed", "payment retry", structural=0.1),
        candidate("near", "retry caller", structural=0.8),
        candidate("far", "failure policy", memory=1.0),
        candidate("beyond", "unbounded distraction", memory=1.0),
    ]
    graph = StaticGraphProvider(
        {"seed": ["near"], "near": ["far"], "far": ["beyond"]}
    )
    engine = ContextEngine(
        PlannerConfig(max_graph_depth=2, max_graph_nodes=3, min_context_roi=0.0),
        graph_provider=graph,
    )

    packet = engine.plan("payment retry", candidates=candidates, mode="drift", token_budget=100)

    selected = {item.candidate_id for item in packet.evidence}
    assert selected == {"seed", "near", "far"}
    assert packet.exclusion_for("beyond").reason == "graph_scope"
    assert packet.evidence_by_id("near").graph_depth == 1
    assert packet.evidence_by_id("far").graph_depth == 2


def test_providers_are_injected_and_combined_without_external_calls() -> None:
    first = StaticCandidateProvider([candidate("a", "provider target")])
    second = StaticCandidateProvider([candidate("b", "provider target memory", memory=1.0)])

    packet = ContextEngine(
        PlannerConfig(min_context_roi=0.0), candidate_providers=(first, second)
    ).plan("provider target", mode="global", token_budget=100)

    assert [item.candidate_id for item in packet.evidence] == ["b", "a"]


def test_identical_candidate_ids_coalesce_but_conflicting_ids_are_rejected() -> None:
    item = candidate("same-id", "same content")
    engine = ContextEngine(PlannerConfig(min_context_roi=0.0))

    packet = engine.plan("same content", candidates=[item, item], token_budget=100)

    assert [evidence.candidate_id for evidence in packet.evidence] == ["same-id"]

    conflicting = replace(item, source="another-source")
    try:
        engine.plan("same content", candidates=[item, conflicting], token_budget=100)
    except ValueError as error:
        assert str(error) == "conflicting candidates share id: same-id"
    else:
        raise AssertionError("conflicting candidate ids must be rejected")


def test_query_plan_preserves_bm25_for_exact_symbol_queries() -> None:
    plan = build_query_plan(
        "HybridRetriever.retrieve",
        requested_mode="hybrid",
        k=10,
        token_budget=1_000,
        dense_available=True,
        reranker_available=True,
    )

    assert plan.intent is QueryIntent.SYMBOL
    assert plan.baseline_stage == "bm25"
    assert plan.candidate_stages == ()
    assert dict(plan.suppressed_stages) == {
        "dense": "lexical_dominant_query",
        "rrf": "lexical_dominant_query",
        "rerank": "lexical_dominant_query",
    }


def test_measured_retrieval_keeps_exact_error_queries_on_lexical_floor() -> None:
    retriever = HybridRetriever(
        doc_ids=["exact", "semantic"],
        texts=[
            "HybridRetriever retrieve raises Unknown mode ValueError",
            "generic retrieval architecture and ranking",
        ],
        embedder=_ConceptEmbedder(),
    )

    decision = retriever.retrieve_measured(
        "HybridRetriever.retrieve ValueError",
        k=2,
        requested_mode="hybrid",
        candidate_promoted=True,
        token_budget=100,
    )

    assert decision.query_plan.intent is QueryIntent.ERROR
    assert decision.selected_stage == "bm25"
    assert [hit.doc_id for hit in decision.hits] == ["exact"]
    assert decision.fallback_reason == "lexical_dominant_query"
    assert [item.stage for item in decision.provenance] == ["bm25"]


def test_conceptual_dense_candidate_requires_promotion_and_confidence() -> None:
    retriever = HybridRetriever(
        doc_ids=["lexical", "semantic"],
        texts=[
            "authorization architecture overview",
            "capability boundary checks policy decisions",
        ],
        embedder=_ConceptEmbedder(),
    )

    shadow = retriever.retrieve_measured(
        "authorization architecture",
        k=2,
        requested_mode="dense",
        candidate_promoted=False,
        min_candidate_confidence=0.8,
        token_budget=100,
    )
    promoted = retriever.retrieve_measured(
        "authorization architecture",
        k=2,
        requested_mode="dense",
        candidate_promoted=True,
        min_candidate_confidence=0.8,
        token_budget=100,
    )

    assert shadow.selected_stage == "bm25"
    assert shadow.fallback_reason == "candidate_not_promoted"
    assert promoted.selected_stage == "dense"
    assert promoted.confidence >= 0.8
    assert promoted.hits[0].doc_id == "semantic"
    assert [item.stage for item in promoted.provenance] == ["bm25", "dense"]


def test_measured_retrieval_hard_budget_abstains_without_overpacking() -> None:
    retriever = HybridRetriever(
        doc_ids=["large"],
        texts=["context budget target"],
        evidence_texts=["word " * 20],
        embedder=_ConceptEmbedder(),
    )

    decision = retriever.retrieve_measured(
        "context budget target",
        k=1,
        requested_mode="bm25",
        token_budget=5,
    )

    assert decision.hits == ()
    assert decision.used_tokens == 0
    assert decision.abstained is True
    assert decision.fallback_reason == "token_budget_exhausted"
    payload = decision.to_dict()
    assert payload["token_budget"] == 5
    assert payload["query_plan"]["baseline_stage"] == "bm25"
