"""Tests for the four-way code-retrieval ablation (BM25 / dense / graph / fused).

The claim protocol requires an ablation of "BM25 versus dense versus graph
versus fused retrieval".  These tests pin the honesty properties of that
ablation:

- Every surface either produces metrics or reports a *typed* skip reason.
- No surface silently substitutes a different retriever (a "dense" surface that
  was really BM25, or a "graph" surface that was really lexical, would make the
  ablation lie).
- Absence is reported as ``skipped`` with a machine-readable ``skip_code``,
  never as a metric of 0.0.
- The two frozen baseline surfaces keep their exact pinned metrics when the new
  surfaces are added alongside them.
- Reruns reproduce exactly (the split is frozen; nothing is random).
"""

from __future__ import annotations

import pytest

from oh_no_my_claudecode.retrieval_eval.code_adapters import (
    SKIP_CODE_GRAPH,
    SKIP_EMBEDDINGS_DISABLED,
    CodeDenseAdapter,
    CodeGraphAdapter,
    CodeHybridAdapter,
    CodeLexicalAdapter,
    code_ablation_adapters,
    code_adapters,
)
from oh_no_my_claudecode.retrieval_eval.code_dataset import load_code_dataset
from oh_no_my_claudecode.retrieval_eval.runner import (
    SurfaceReport,
    SurfaceSkip,
    run_code_evaluation,
)

# Frozen baseline on dataset_sha 8e8f6d52… (40 cases).  Metrics only — latency
# is wall-clock and machine-dependent, so it is deliberately not pinned.
FROZEN_BASELINE: dict[str, dict[str, float]] = {
    "code-bm25": {
        "recall@5": 0.95,
        "recall@10": 1.0,
        "p@5": 0.19,
        "mrr@10": 0.8101,
        "ndcg@10": 0.8574,
        "context_tokens": 3299.3,
    },
    "code-hybrid": {
        "recall@5": 0.875,
        "recall@10": 0.95,
        "p@5": 0.175,
        "mrr@10": 0.7637,
        "ndcg@10": 0.8082,
        "context_tokens": 2887.3,
    },
}

ABLATION_SURFACES = ("code-bm25", "code-hybrid", "code-dense", "code-graph")


@pytest.fixture(scope="module")
def ablation_report_dict() -> dict[str, dict[str, object]]:
    """Run the four-way ablation once and index the surfaces by name."""
    report = run_code_evaluation(code_ablation_adapters())
    return {str(s["surface"]): s for s in report.to_dict()["surfaces"]}


def _surface(report_dicts: dict[str, dict[str, object]], name: str) -> dict[str, object]:
    assert name in report_dicts, f"surface '{name}' missing from the ablation report"
    return report_dicts[name]


# ---------------------------------------------------------------------------
# The ablation is runnable: all four surfaces are present and accounted for
# ---------------------------------------------------------------------------


class TestAblationCoverage:
    def test_all_four_surfaces_present(
        self, ablation_report_dict: dict[str, dict[str, object]]
    ) -> None:
        for name in ABLATION_SURFACES:
            assert name in ablation_report_dict

    def test_ablation_adapter_surface_names(self) -> None:
        assert [a.surface_name for a in code_ablation_adapters()] == list(ABLATION_SURFACES)

    def test_baseline_surfaces_come_first(self) -> None:
        """Pinned baselines run before the additive surfaces."""
        names = [a.surface_name for a in code_ablation_adapters()]
        assert names[:2] == ["code-bm25", "code-hybrid"]

    def test_code_adapters_still_returns_only_the_two_baselines(self) -> None:
        """The frozen baseline set stays reproducible in isolation."""
        assert [a.surface_name for a in code_adapters()] == ["code-bm25", "code-hybrid"]

    def test_every_surface_has_metrics_or_a_typed_skip_reason(
        self, ablation_report_dict: dict[str, dict[str, object]]
    ) -> None:
        """The core honesty invariant: measured, or skipped with a machine-readable code."""
        for name in ABLATION_SURFACES:
            surf = _surface(ablation_report_dict, name)
            if surf.get("skipped"):
                assert surf.get("skip_code"), f"{name} skipped without a machine-readable code"
                assert surf.get("skip_reason"), f"{name} skipped without a human reason"
                # A skipped surface must not carry metrics at all.
                assert "recall@10" not in surf
                assert "n_cases" not in surf
            else:
                assert surf["n_cases"] == 40
                assert "recall@10" in surf
                assert "mrr@10" in surf
                assert "ndcg@10" in surf


# ---------------------------------------------------------------------------
# Frozen baseline must not regress when the new surfaces are added
# ---------------------------------------------------------------------------


class TestFrozenBaselineUnchanged:
    @pytest.mark.parametrize("surface", ["code-bm25", "code-hybrid"])
    def test_baseline_metrics_exact(
        self, ablation_report_dict: dict[str, dict[str, object]], surface: str
    ) -> None:
        surf = _surface(ablation_report_dict, surface)
        assert not surf.get("skipped")
        assert surf["n_cases"] == 40
        for metric, expected in FROZEN_BASELINE[surface].items():
            assert surf[metric] == pytest.approx(expected), (
                f"{surface} {metric} drifted: {surf[metric]} != {expected}"
            )

    def test_baseline_json_shape_unchanged(
        self, ablation_report_dict: dict[str, dict[str, object]]
    ) -> None:
        """Baseline surfaces gain no new JSON keys (no stray notes/skip_code)."""
        expected_keys = {
            "surface",
            "n_cases",
            "recall@5",
            "recall@10",
            "p@5",
            "mrr@10",
            "ndcg@10",
            "latency_p50_ms",
            "latency_p95_ms",
            "context_tokens",
        }
        for surface in ("code-bm25", "code-hybrid"):
            assert set(_surface(ablation_report_dict, surface)) == expected_keys

    def test_adding_surfaces_does_not_change_baseline_metrics(self) -> None:
        """Two-surface run and four-surface run agree on the baseline numbers."""
        pair = {
            sr.surface_name: sr for sr in run_code_evaluation(code_adapters()).surface_reports
        }
        quad = {
            sr.surface_name: sr
            for sr in run_code_evaluation(code_ablation_adapters()).surface_reports
        }
        for surface in ("code-bm25", "code-hybrid"):
            for metric in (
                "mean_recall_at_5",
                "mean_recall_at_10",
                "mean_precision_at_5",
                "mean_mrr_at_10",
                "mean_ndcg_at_10",
                "mean_context_tokens",
            ):
                assert getattr(pair[surface], metric) == getattr(quad[surface], metric)


# ---------------------------------------------------------------------------
# code-dense: implemented for real
# ---------------------------------------------------------------------------


class TestCodeDenseSurface:
    def test_surface_name_and_borrowed_label_set(self) -> None:
        assert CodeDenseAdapter.surface_name == "code-dense"
        assert CodeDenseAdapter.case_surface == "code-bm25"

    def test_dense_is_measured_not_skipped(
        self, ablation_report_dict: dict[str, dict[str, object]]
    ) -> None:
        surf = _surface(ablation_report_dict, "code-dense")
        assert not surf.get("skipped"), f"code-dense skipped: {surf.get('skip_reason')}"
        assert surf["n_cases"] == 40

    def test_dense_metrics_are_in_range_and_nonzero(
        self, ablation_report_dict: dict[str, dict[str, object]]
    ) -> None:
        surf = _surface(ablation_report_dict, "code-dense")
        for metric in ("recall@5", "recall@10", "mrr@10", "ndcg@10"):
            value = float(surf[metric])  # type: ignore[arg-type]
            assert 0.0 < value <= 1.0, f"code-dense {metric} = {value} is not a real measurement"

    def test_dense_reports_embedder_provenance(
        self, ablation_report_dict: dict[str, dict[str, object]]
    ) -> None:
        """A hash-ngram run must never be readable as a neural dense run."""
        notes = str(_surface(ablation_report_dict, "code-dense")["notes"])
        assert "embedder=" in notes
        assert "dense-only" in notes

    def test_dense_scored_on_identical_labels_to_bm25(self) -> None:
        """Borrowing labels must not change a single query or judgement."""
        report = run_code_evaluation([CodeLexicalAdapter(), CodeDenseAdapter()])
        by_name = {sr.surface_name: sr for sr in report.surface_reports}
        bm25 = by_name["code-bm25"].query_results
        dense = by_name["code-dense"].query_results
        assert len(bm25) == len(dense) == 40
        for b, d in zip(bm25, dense, strict=True):
            assert b.query == d.query
            assert b.relevant_ids == d.relevant_ids
            assert b.graded == d.graded

    def test_dense_query_rows_are_attributed_to_dense(self) -> None:
        """Borrowed cases are re-stamped, so no row claims to be a bm25 row."""
        report = run_code_evaluation([CodeDenseAdapter()])
        rows = report.surface_reports[0].query_results
        assert rows
        for row in rows:
            assert row.surface == "code-dense"
            assert row.query_id.endswith("-dense")
            assert "bm25" not in row.query_id

    def test_dense_uses_no_lexical_index(self) -> None:
        """Structural proof the dense surface cannot fall back to BM25."""
        adapter = CodeDenseAdapter()
        ds = load_code_dataset()
        adapter.setup(ds)  # type: ignore[arg-type]
        try:
            assert adapter._dense is not None  # noqa: SLF001
            assert adapter._retriever is None, (  # noqa: SLF001
                "code-dense must not construct a BM25/hybrid index"
            )
        finally:
            adapter.teardown()

    def test_dense_ranking_matches_shipped_dense_mode(self) -> None:
        """The adapter reuses the shipped dense primitive, not a private copy.

        Equivalence with ``HybridRetriever.retrieve(mode="dense")`` proves the
        surface measures ONMC's real dense path.
        """
        from oh_no_my_claudecode.retrieval.core import HybridRetriever  # noqa: PLC0415
        from oh_no_my_claudecode.retrieval_eval.code_adapters import (  # noqa: PLC0415
            _chunk_text,
        )

        ds = load_code_dataset()
        corpus = list(ds.corpus)
        reference = HybridRetriever(
            doc_ids=[e.id for e in corpus],
            texts=[_chunk_text(e) for e in corpus],
        )
        adapter = CodeDenseAdapter()
        adapter.setup(ds)  # type: ignore[arg-type]
        try:
            for case in ds.cases_for_surface("code-bm25")[:5]:
                expected = [h.doc_id for h in reference.retrieve(case.query, 10, mode="dense")]
                assert adapter.retrieve(case.query, 10) == expected
        finally:
            adapter.teardown()

    def test_dense_ranking_differs_from_bm25(self) -> None:
        """A dense surface identical to BM25 would mean silent substitution."""
        ds = load_code_dataset()
        dense = CodeDenseAdapter()
        lexical = CodeLexicalAdapter()
        dense.setup(ds)  # type: ignore[arg-type]
        lexical.setup(ds)  # type: ignore[arg-type]
        try:
            differed = 0
            for case in ds.cases_for_surface("code-bm25"):
                if dense.retrieve(case.query, 10) != lexical.retrieve(case.query, 10):
                    differed += 1
            assert differed > 0, "code-dense produced BM25's exact rankings — not dense at all"
        finally:
            dense.teardown()
            lexical.teardown()

    def test_dense_ranking_differs_from_hybrid(self) -> None:
        """Dense-only must not be a relabelled copy of the fused surface."""
        ds = load_code_dataset()
        dense = CodeDenseAdapter()
        hybrid = CodeHybridAdapter()
        dense.setup(ds)  # type: ignore[arg-type]
        hybrid.setup(ds)  # type: ignore[arg-type]
        try:
            differed = sum(
                dense.retrieve(case.query, 10) != hybrid.retrieve(case.query, 10)
                for case in ds.cases_for_surface("code-hybrid")
            )
            assert differed > 0, "code-dense produced code-hybrid's exact rankings"
        finally:
            dense.teardown()
            hybrid.teardown()

    def test_dense_retrieval_is_deterministic(self) -> None:
        """Frozen split ⇒ reruns must match exactly (no seed-dependent order)."""
        ds = load_code_dataset()
        query = ds.cases_for_surface("code-bm25")[0].query
        rankings = []
        for _ in range(2):
            adapter = CodeDenseAdapter()
            adapter.setup(ds)  # type: ignore[arg-type]
            try:
                rankings.append(adapter.retrieve(query, 10))
            finally:
                adapter.teardown()
        assert rankings[0] == rankings[1]
        assert rankings[0], "dense retrieval returned nothing for a frozen query"

    def test_dense_returns_only_corpus_ids(self) -> None:
        ds = load_code_dataset()
        corpus_ids = {e.id for e in ds.corpus}
        adapter = CodeDenseAdapter()
        adapter.setup(ds)  # type: ignore[arg-type]
        try:
            for rid in adapter.retrieve("reciprocal rank fusion of ranked lists", 10):
                assert rid in corpus_ids
        finally:
            adapter.teardown()

    def test_dense_skips_when_embeddings_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ONMC_EMBEDDINGS=0 must skip, not silently degrade to lexical."""
        monkeypatch.setenv("ONMC_EMBEDDINGS", "0")
        skip = CodeDenseAdapter().precheck()
        assert skip == SKIP_EMBEDDINGS_DISABLED
        assert skip is not None
        assert skip.code == "embeddings_disabled"

        report = run_code_evaluation([CodeDenseAdapter()])
        sr = report.surface_reports[0]
        assert sr.skipped
        assert sr.skip_code == "embeddings_disabled"
        assert sr.n_cases == 0
        # Absence must never be reported as a zeroed measurement.
        assert "recall@10" not in sr.to_dict()

    def test_dense_measured_when_embeddings_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONMC_EMBEDDINGS", "1")
        assert CodeDenseAdapter().precheck() is None


# ---------------------------------------------------------------------------
# code-graph: honestly skipped
# ---------------------------------------------------------------------------


class TestCodeGraphSurface:
    def test_surface_name(self) -> None:
        assert CodeGraphAdapter.surface_name == "code-graph"

    def test_graph_precheck_always_skips(self) -> None:
        skip = CodeGraphAdapter().precheck()
        assert isinstance(skip, SurfaceSkip)
        assert skip.code == "no_graph_query_ranker"

    def test_graph_skip_reason_is_reported(
        self, ablation_report_dict: dict[str, dict[str, object]]
    ) -> None:
        surf = _surface(ablation_report_dict, "code-graph")
        assert surf.get("skipped") is True
        assert surf.get("skip_code") == "no_graph_query_ranker"
        assert surf.get("skip_reason") == SKIP_CODE_GRAPH.reason

    def test_graph_reports_no_metrics_at_all(
        self, ablation_report_dict: dict[str, dict[str, object]]
    ) -> None:
        """An unimplemented surface must not appear as a row of zeros."""
        surf = _surface(ablation_report_dict, "code-graph")
        for key in ("n_cases", "recall@5", "recall@10", "p@5", "mrr@10", "ndcg@10"):
            assert key not in surf

    def test_graph_retrieve_raises_rather_than_returning_empty(self) -> None:
        """Empty results would be scored 0.0 and read as 'graph is bad'."""
        with pytest.raises(NotImplementedError):
            CodeGraphAdapter().retrieve("anything", 10)

    def test_graph_surface_appears_in_markdown_as_skipped(self) -> None:
        report = run_code_evaluation(code_ablation_adapters())
        md = report.to_markdown()
        assert "code-graph" in md
        assert "SKIPPED[no_graph_query_ranker]" in md


# ---------------------------------------------------------------------------
# Runner-level honesty plumbing
# ---------------------------------------------------------------------------


class TestRunnerSkipPlumbing:
    def test_default_adapter_has_no_precheck_or_provenance(self) -> None:
        """Existing adapters are unaffected by the new hooks."""
        for adapter in (CodeLexicalAdapter(), CodeHybridAdapter()):
            assert adapter.precheck() is None
            assert adapter.provenance() == ""
            assert adapter.case_surface == ""

    def test_legacy_no_cases_skip_has_no_skip_code(self) -> None:
        """The pre-existing 'no cases' skip keeps its exact JSON shape."""

        class _UnknownSurfaceAdapter(CodeLexicalAdapter):
            surface_name = "code-nonexistent"
            case_surface = ""

        report = run_code_evaluation([_UnknownSurfaceAdapter()])
        sr = report.surface_reports[0]
        assert sr.skipped
        assert "no cases for surface 'code-nonexistent'" in sr.skip_reason
        assert set(sr.to_dict()) == {"surface", "skipped", "skip_reason"}

    def test_borrowing_requires_the_lender_to_exist(self) -> None:
        """A missing lender falls back to the honest 'no cases' skip."""

        class _BadLenderAdapter(CodeDenseAdapter):
            surface_name = "code-dense-bogus"
            case_surface = "code-does-not-exist"

        report = run_code_evaluation([_BadLenderAdapter()])
        sr = report.surface_reports[0]
        assert sr.skipped
        assert "no cases for surface 'code-dense-bogus'" in sr.skip_reason

    def test_precheck_beats_case_lookup(self) -> None:
        """A missing primitive is reported as such, not as 'no cases'."""
        report = run_code_evaluation([CodeGraphAdapter()])
        sr = report.surface_reports[0]
        assert sr.skip_code == "no_graph_query_ranker"
        assert "no cases" not in sr.skip_reason

    def test_precheck_exception_becomes_a_typed_skip(self) -> None:
        class _ExplodingAdapter(CodeLexicalAdapter):
            surface_name = "code-explodes"

            def precheck(self) -> SurfaceSkip | None:
                raise RuntimeError("boom")

        report = run_code_evaluation([_ExplodingAdapter()])
        sr = report.surface_reports[0]
        assert sr.skipped
        assert sr.skip_code == "precheck_failed"
        assert "boom" in sr.skip_reason

    def test_notes_omitted_when_empty(self) -> None:
        sr = SurfaceReport(surface_name="x")
        sr.finalize()
        assert "notes" not in sr.to_dict()

    def test_skip_code_omitted_when_empty(self) -> None:
        sr = SurfaceReport(surface_name="x", skipped=True, skip_reason="because")
        assert set(sr.to_dict()) == {"surface", "skipped", "skip_reason"}
        assert "SKIPPED: because" in sr.to_markdown_row()
