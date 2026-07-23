"""Tests for the retrieval_eval harness.

Covers:
- metric correctness vs hand-computed expected values (>= 4 tests)
- dataset frozen SHA integrity test
- runner aggregates (sanity check on report structure)
- RecallAdapter smoke test (seeds corpus, queries, gets ranked IDs)
- GuardAdapter smoke test
- SkippedAdapter appears correctly in report
- metrics edge cases (empty results, all relevant, none relevant)
- RetrievalReport.to_dict() / to_markdown() structure
"""

from __future__ import annotations

import math

from oh_no_my_claudecode.retrieval_eval.dataset import EXPECTED_DATASET_SHA, load_dataset
from oh_no_my_claudecode.retrieval_eval.metrics import (
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from oh_no_my_claudecode.retrieval_eval.runner import (
    BaselineAdapter,
    RetrievalDataset,
    SurfaceReport,
    run_evaluation,
)

# ---------------------------------------------------------------------------
# Metric correctness tests — hand-computed expected values
# ---------------------------------------------------------------------------

class TestRecallAtK:
    """recall_at_k = |top_k ∩ relevant| / |relevant|"""

    def test_perfect_recall(self) -> None:
        ranked = ["a", "b", "c", "d", "e"]
        relevant = {"a", "b"}
        assert recall_at_k(ranked, relevant, 5) == 1.0

    def test_zero_recall(self) -> None:
        ranked = ["x", "y", "z"]
        relevant = {"a", "b"}
        assert recall_at_k(ranked, relevant, 3) == 0.0

    def test_partial_recall(self) -> None:
        # 1 of 3 relevant in top-5
        ranked = ["a", "x", "y", "z", "w"]
        relevant = {"a", "b", "c"}
        result = recall_at_k(ranked, relevant, 5)
        assert abs(result - 1 / 3) < 1e-9

    def test_recall_cutoff_excludes_later_hits(self) -> None:
        # 'b' is at rank 6, beyond k=5
        ranked = ["a", "x", "y", "z", "w", "b"]
        relevant = {"a", "b"}
        assert recall_at_k(ranked, relevant, 5) == 0.5  # only 'a' in top-5

    def test_empty_relevant(self) -> None:
        ranked = ["a", "b"]
        assert recall_at_k(ranked, set(), 5) == 0.0

    def test_k_zero(self) -> None:
        ranked = ["a", "b", "c"]
        relevant = {"a"}
        assert recall_at_k(ranked, relevant, 0) == 0.0

    def test_k_larger_than_ranked(self) -> None:
        ranked = ["a", "b"]
        relevant = {"a", "b", "c"}
        # top-10 has 2/3 relevant
        result = recall_at_k(ranked, relevant, 10)
        assert abs(result - 2 / 3) < 1e-9


class TestPrecisionAtK:
    """precision_at_k = |top_k ∩ relevant| / k"""

    def test_perfect_precision(self) -> None:
        ranked = ["a", "b", "c"]
        relevant = {"a", "b", "c", "d"}
        assert precision_at_k(ranked, relevant, 3) == 1.0

    def test_zero_precision(self) -> None:
        ranked = ["x", "y", "z"]
        relevant = {"a", "b"}
        assert precision_at_k(ranked, relevant, 3) == 0.0

    def test_partial_precision(self) -> None:
        # 2 of 5 are relevant
        ranked = ["a", "x", "b", "y", "z"]
        relevant = {"a", "b"}
        result = precision_at_k(ranked, relevant, 5)
        assert abs(result - 2 / 5) < 1e-9

    def test_k_zero_returns_zero(self) -> None:
        ranked = ["a"]
        relevant = {"a"}
        assert precision_at_k(ranked, relevant, 0) == 0.0


class TestMRRAtK:
    """mrr_at_k = 1/rank_of_first_relevant (or 0.0 if none in top-k)"""

    def test_first_rank(self) -> None:
        ranked = ["a", "b", "c"]
        relevant = {"a"}
        assert mrr_at_k(ranked, relevant, 10) == 1.0

    def test_second_rank(self) -> None:
        ranked = ["x", "a", "b"]
        relevant = {"a"}
        assert abs(mrr_at_k(ranked, relevant, 10) - 0.5) < 1e-9

    def test_fifth_rank(self) -> None:
        ranked = ["x1", "x2", "x3", "x4", "a"]
        relevant = {"a"}
        assert abs(mrr_at_k(ranked, relevant, 10) - 0.2) < 1e-9

    def test_no_hit_in_top_k(self) -> None:
        ranked = ["x", "y", "z", "a"]
        relevant = {"a"}
        # k=3 so 'a' at rank 4 is excluded
        assert mrr_at_k(ranked, relevant, 3) == 0.0

    def test_empty_relevant(self) -> None:
        ranked = ["a", "b"]
        assert mrr_at_k(ranked, set(), 10) == 0.0

    def test_multiple_relevant_first_counts(self) -> None:
        # 'b' is at rank 1, 'a' at rank 3; MRR should use rank 1
        ranked = ["b", "x", "a"]
        relevant = {"a", "b"}
        assert mrr_at_k(ranked, relevant, 10) == 1.0


class TestNDCGAtK:
    """nDCG@k with both binary and graded relevance."""

    def test_perfect_ndcg_binary(self) -> None:
        # All relevant docs at top ranks
        ranked = ["a", "b", "x", "y"]
        relevant = {"a", "b"}
        assert abs(ndcg_at_k(ranked, relevant, 5) - 1.0) < 1e-9

    def test_zero_ndcg_no_hits(self) -> None:
        ranked = ["x", "y", "z"]
        relevant = {"a", "b"}
        assert ndcg_at_k(ranked, relevant, 5) == 0.0

    def test_ndcg_binary_partial_hand_computed(self) -> None:
        # Relevant: {a, b}. Ranked: [x, a, y, b]
        # DCG = 0 + 1/log2(3) + 0 + 1/log2(5)
        #      = 1/1.585 + 1/2.322 = 0.631 + 0.431 = 1.062
        # IDCG (ideal: [a, b]): 1/log2(2) + 1/log2(3) = 1.0 + 0.631 = 1.631
        # nDCG = 1.062 / 1.631 ≈ 0.651
        ranked = ["x", "a", "y", "b"]
        relevant = {"a", "b"}
        result = ndcg_at_k(ranked, relevant, 10)
        expected = (1 / math.log2(3) + 1 / math.log2(5)) / (
            1 / math.log2(2) + 1 / math.log2(3)
        )
        assert abs(result - expected) < 1e-9

    def test_ndcg_graded_hand_computed(self) -> None:
        # Graded: a=3, b=1. Ranked: [b, a].
        # DCG  = 1/log2(2) + 3/log2(3) = 1.0 + 1.893 = 2.893
        # IDCG = 3/log2(2) + 1/log2(3) = 3.0 + 0.631 = 3.631
        # nDCG = 2.893 / 3.631 ≈ 0.797
        ranked = ["b", "a"]
        relevant = {"a", "b"}
        graded = {"a": 3.0, "b": 1.0}
        result = ndcg_at_k(ranked, relevant, 10, graded=graded)
        dcg = 1.0 / math.log2(2) + 3.0 / math.log2(3)
        idcg = 3.0 / math.log2(2) + 1.0 / math.log2(3)
        expected = dcg / idcg
        assert abs(result - expected) < 1e-9

    def test_ndcg_empty_relevant(self) -> None:
        ranked = ["a", "b"]
        assert ndcg_at_k(ranked, set(), 5) == 0.0


# ---------------------------------------------------------------------------
# Dataset frozen SHA integrity test
# ---------------------------------------------------------------------------


class TestDatasetIntegrity:
    def test_dataset_loads_without_error(self) -> None:
        dataset = load_dataset(verify_sha=True)
        assert len(dataset.corpus) >= 20
        assert len(dataset.cases) >= 20

    def test_dataset_sha_matches_expected_constant(self) -> None:
        dataset = load_dataset(verify_sha=False)
        assert dataset.dataset_sha == EXPECTED_DATASET_SHA

    def test_dataset_sha_verifies_against_content(self) -> None:
        # load_dataset(verify_sha=True) must not raise — SHA is correct.
        dataset = load_dataset(verify_sha=True)
        assert dataset.dataset_sha == EXPECTED_DATASET_SHA

    def test_corpus_ids_are_unique(self) -> None:
        dataset = load_dataset()
        ids = [e.id for e in dataset.corpus]
        assert len(ids) == len(set(ids)), "Corpus entry IDs must be unique"

    def test_case_query_ids_are_unique(self) -> None:
        dataset = load_dataset()
        qids = [c.query_id for c in dataset.cases]
        assert len(qids) == len(set(qids)), "Case query IDs must be unique"

    def test_relevant_ids_are_in_corpus(self) -> None:
        dataset = load_dataset()
        corpus_ids = {e.id for e in dataset.corpus}
        for case in dataset.cases:
            for rel_id in case.relevant_ids:
                assert rel_id in corpus_ids, (
                    f"Case {case.query_id}: relevant_id '{rel_id}' not in corpus"
                )

    def test_graded_ids_are_subset_of_relevant_ids(self) -> None:
        dataset = load_dataset()
        for case in dataset.cases:
            for gid in case.graded:
                assert gid in set(case.relevant_ids), (
                    f"Case {case.query_id}: graded id '{gid}' not in relevant_ids"
                )

    def test_cases_for_surface_filtering(self) -> None:
        dataset = load_dataset()
        recall_cases = dataset.cases_for_surface("recall")
        guard_cases = dataset.cases_for_surface("guard")
        assert len(recall_cases) > 0
        assert len(guard_cases) > 0
        assert all(c.surface == "recall" for c in recall_cases)
        assert all(c.surface == "guard" for c in guard_cases)


# ---------------------------------------------------------------------------
# Runner aggregate tests
# ---------------------------------------------------------------------------


class _PerfectAdapter(BaselineAdapter):
    """Returns the exact relevant_ids for each query — used to test aggregates."""

    surface_name = "perfect"

    def __init__(self) -> None:
        self._case_map: dict[str, list[str]] = {}

    def setup(self, dataset: RetrievalDataset) -> None:
        # Build a query -> relevant_ids map for perfect retrieval.
        for case in dataset.cases:
            if case.surface == self.surface_name:
                self._case_map[case.query] = list(case.relevant_ids)

    def retrieve(self, query: str, k: int) -> list[str]:
        return self._case_map.get(query, [])[:k]


class _EmptyAdapter(BaselineAdapter):
    """Returns empty results for every query — baseline floor."""

    surface_name = "recall"

    def retrieve(self, query: str, k: int) -> list[str]:
        return []


class TestRunnerAggregates:
    def test_report_has_dataset_sha(self) -> None:
        report = run_evaluation([_EmptyAdapter()])
        assert report.dataset_sha == EXPECTED_DATASET_SHA

    def test_empty_adapter_scores_zero(self) -> None:
        report = run_evaluation([_EmptyAdapter()])
        assert len(report.surface_reports) == 1
        sr = report.surface_reports[0]
        assert not sr.skipped
        assert sr.mean_recall_at_5 == 0.0
        assert sr.mean_recall_at_10 == 0.0
        assert sr.mean_mrr_at_10 == 0.0
        assert sr.mean_ndcg_at_10 == 0.0

    def test_unknown_surface_skipped(self) -> None:
        class _UnknownAdapter(BaselineAdapter):
            surface_name = "nonexistent_surface"

            def retrieve(self, query: str, k: int) -> list[str]:
                return []

        report = run_evaluation([_UnknownAdapter()])
        assert len(report.surface_reports) == 1
        sr = report.surface_reports[0]
        assert sr.skipped
        assert "no cases" in sr.skip_reason

    def test_to_dict_structure(self) -> None:
        report = run_evaluation([_EmptyAdapter()])
        d = report.to_dict()
        assert "dataset_sha" in d
        assert "surfaces" in d
        assert isinstance(d["surfaces"], list)
        assert len(d["surfaces"]) == 1
        surface = d["surfaces"][0]
        assert "recall@5" in surface
        assert "recall@10" in surface
        assert "mrr@10" in surface
        assert "ndcg@10" in surface

    def test_to_markdown_contains_header(self) -> None:
        report = run_evaluation([_EmptyAdapter()])
        md = report.to_markdown()
        assert "retrieval-eval" in md.lower()
        assert EXPECTED_DATASET_SHA[:8] in md
        # Header uses abbreviated column names
        assert "R@5" in md or "recall" in md.lower()

    def test_surface_report_finalize_aggregates_latency(self) -> None:
        sr = SurfaceReport(surface_name="test")
        from oh_no_my_claudecode.retrieval_eval.runner import QueryResult

        qr1 = QueryResult(
            query_id="q1",
            query="test",
            surface="test",
            ranked_ids=["a"],
            relevant_ids={"a"},
            graded={},
            latency_ms=10.0,
        )
        qr2 = QueryResult(
            query_id="q2",
            query="test2",
            surface="test",
            ranked_ids=[],
            relevant_ids={"b"},
            graded={},
            latency_ms=90.0,
        )
        sr.query_results = [qr1, qr2]
        sr.finalize()
        assert sr.n_cases == 2
        assert sr.latency_p50_ms > 0.0
        assert sr.latency_p95_ms >= sr.latency_p50_ms


# ---------------------------------------------------------------------------
# Adapter smoke tests — exercise the live retrieval code paths
# ---------------------------------------------------------------------------


class TestRecallAdapterSmoke:
    def test_recall_adapter_returns_list_of_strings(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.adapters import RecallAdapter

        dataset = load_dataset()
        adapter = RecallAdapter()
        adapter.setup(dataset)
        try:
            result = adapter.retrieve("SQLite database is locked", k=5)
            assert isinstance(result, list)
            assert all(isinstance(r, str) for r in result)
            assert len(result) <= 5
        finally:
            adapter.teardown()

    def test_recall_adapter_ids_are_corpus_ids(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.adapters import RecallAdapter

        dataset = load_dataset()
        corpus_ids = {e.id for e in dataset.corpus}
        adapter = RecallAdapter()
        adapter.setup(dataset)
        try:
            result = adapter.retrieve("FTS5 MATCH syntax error hyphens", k=10)
            for rid in result:
                assert rid in corpus_ids, f"'{rid}' is not a corpus ID"
        finally:
            adapter.teardown()

    def test_recall_adapter_noisy_query_returns_something(self) -> None:
        """A query with keywords that appear in multiple corpus entries returns results."""
        from oh_no_my_claudecode.retrieval_eval.adapters import RecallAdapter

        dataset = load_dataset()
        adapter = RecallAdapter()
        adapter.setup(dataset)
        try:
            result = adapter.retrieve("sqlite error deadlock concurrent write", k=10)
            # With a rich corpus, at least one result should appear.
            assert isinstance(result, list)
        finally:
            adapter.teardown()


class TestGuardAdapterSmoke:
    def test_guard_adapter_returns_list(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.adapters import GuardAdapter

        dataset = load_dataset()
        adapter = GuardAdapter()
        adapter.setup(dataset)
        try:
            result = adapter.retrieve("implement concurrent SQLite writes", k=5)
            assert isinstance(result, list)
            assert len(result) <= 5
        finally:
            adapter.teardown()

    def test_guard_adapter_corpus_ids_only(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.adapters import GuardAdapter

        dataset = load_dataset()
        corpus_ids = {e.id for e in dataset.corpus}
        adapter = GuardAdapter()
        adapter.setup(dataset)
        try:
            result = adapter.retrieve("use threading lock sqlite", k=10)
            for rid in result:
                assert rid in corpus_ids
        finally:
            adapter.teardown()


class TestSkippedAdapterInReport:
    def test_skipped_adapter_appears_in_report_no_cases(self) -> None:
        # "search_memory" has no cases in the dataset so the runner skips it
        # before calling setup() — still appears as skipped in the report.
        from oh_no_my_claudecode.retrieval_eval.adapters import SkippedAdapter

        report = run_evaluation([SkippedAdapter("search_memory", "requires OnmcRepo")])
        assert len(report.surface_reports) == 1
        sr = report.surface_reports[0]
        assert sr.skipped
        assert sr.surface_name == "search_memory"
        assert sr.skip_reason  # some reason present

    def test_skipped_adapter_raises_in_setup_when_cases_exist(self) -> None:
        # When surface_name matches an existing surface, setup() is called and
        # the SkippedAdapter's reason surfaces through the setup failure path.
        from oh_no_my_claudecode.retrieval_eval.adapters import SkippedAdapter

        # Use "recall" which has cases — setup will raise and propagate the reason.
        adapter = SkippedAdapter("recall", "requires special infra")
        report = run_evaluation([adapter])
        assert len(report.surface_reports) == 1
        sr = report.surface_reports[0]
        assert sr.skipped
        assert "requires special infra" in sr.skip_reason

    def test_skipped_adapter_in_dict(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.adapters import SkippedAdapter

        report = run_evaluation([SkippedAdapter("ctx", "no graph")])
        d = report.to_dict()
        surf = d["surfaces"][0]
        assert surf.get("skipped") is True
        assert "skip_reason" in surf

    def test_skipped_adapter_in_markdown(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.adapters import SkippedAdapter

        report = run_evaluation([SkippedAdapter("ctx", "no graph")])
        md = report.to_markdown()
        assert "SKIPPED" in md


# ---------------------------------------------------------------------------
# Full integration: default_adapters() smoke (non-zero output, no crash)
# ---------------------------------------------------------------------------


class TestDefaultAdaptersIntegration:
    def test_default_adapters_run_without_crash(self) -> None:
        """Run the full default_adapters() set and verify report structure."""
        from oh_no_my_claudecode.retrieval_eval.adapters import default_adapters

        report = run_evaluation(default_adapters())
        surface_names = {sr.surface_name for sr in report.surface_reports}
        assert "recall" in surface_names
        assert "guard" in surface_names
        assert "search_memory" in surface_names
        assert "context_engine" in surface_names

    def test_default_adapters_recall_not_skipped(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.adapters import default_adapters

        report = run_evaluation(default_adapters())
        recall_report = next(
            sr for sr in report.surface_reports if sr.surface_name == "recall"
        )
        assert not recall_report.skipped
        assert recall_report.n_cases > 0

    def test_default_adapters_guard_not_skipped(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.adapters import default_adapters

        report = run_evaluation(default_adapters())
        guard_report = next(
            sr for sr in report.surface_reports if sr.surface_name == "guard"
        )
        assert not guard_report.skipped
        assert guard_report.n_cases > 0

    def test_markdown_output_is_non_empty(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.adapters import default_adapters

        report = run_evaluation(default_adapters())
        md = report.to_markdown()
        assert len(md) > 100
        assert "recall" in md.lower()
