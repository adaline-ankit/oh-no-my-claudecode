"""Tests for the benchmark-report additions: context tokens + wins/losses."""

from __future__ import annotations

from oh_no_my_claudecode.retrieval_eval.runner import (
    QueryResult,
    SurfaceReport,
    compare_surfaces,
)


def _qr(query_id: str, ndcg: float, ctx_tokens: int) -> QueryResult:
    qr = QueryResult(
        query_id=query_id,
        query=query_id,
        surface="s",
        ranked_ids=["a", "b"],
        relevant_ids={"a"},
        graded={},
        latency_ms=1.0,
        context_tokens=ctx_tokens,
    )
    # Override the auto-computed metric to a controlled value for the comparison.
    qr.ndcg_at_10 = ndcg
    return qr


def _surface(name: str, rows: list[tuple[str, float, int]]) -> SurfaceReport:
    sr = SurfaceReport(surface_name=name)
    sr.query_results = [_qr(qid, ndcg, ctx) for qid, ndcg, ctx in rows]
    sr.finalize()
    return sr


def test_mean_context_tokens_aggregated() -> None:
    sr = _surface("code-bm25", [("q1", 0.5, 100), ("q2", 0.5, 300)])
    assert sr.mean_context_tokens == 200.0
    assert sr.to_dict()["context_tokens"] == 200.0


def test_compare_surfaces_counts_wins_losses_ties() -> None:
    baseline = _surface("code-bm25", [("q1", 0.5, 10), ("q2", 0.8, 10), ("q3", 0.4, 10)])
    candidate = _surface("code-hybrid", [("q1", 0.7, 10), ("q2", 0.6, 10), ("q3", 0.4, 10)])
    cmp = compare_surfaces(baseline, candidate, metric="ndcg_at_10")
    assert cmp.wins == 1  # q1: 0.7 > 0.5
    assert cmp.losses == 1  # q2: 0.6 < 0.8
    assert cmp.ties == 1  # q3: equal
    assert cmp.n == 3
    assert abs(cmp.mean_delta - ((0.2) + (-0.2) + 0.0) / 3) < 1e-9


def test_compare_surfaces_verdict() -> None:
    baseline = _surface("code-bm25", [("q1", 0.5, 10), ("q2", 0.5, 10)])
    candidate = _surface("code-hybrid", [("q1", 0.9, 10), ("q2", 0.6, 10)])
    cmp = compare_surfaces(baseline, candidate)
    assert cmp.wins == 2
    assert "BEATS" in cmp.verdict
    assert cmp.to_dict()["verdict"] == cmp.verdict


def test_compare_surfaces_only_matches_shared_query_ids() -> None:
    baseline = _surface("b", [("q1", 0.5, 10)])
    candidate = _surface("c", [("q1", 0.9, 10), ("q_only_candidate", 0.9, 10)])
    cmp = compare_surfaces(baseline, candidate)
    assert cmp.n == 1  # only q1 is shared
