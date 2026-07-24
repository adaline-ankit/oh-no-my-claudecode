"""Tests for the code-retrieval evaluation split.

Covers:
- Frozen code dataset SHA integrity (pinned constant)
- Code dataset loader correctness (corpus size, case structure, surface names)
- CodeLexicalAdapter smoke (setup, retrieve, teardown)
- CodeHybridAdapter smoke
- run_code_evaluation() produces a report with the expected surface names
- Delta: BM25 and hybrid surface reports are both present and non-skipped
- CLI --split code flag produces correct surfaces (via run_code_evaluation)
"""

from __future__ import annotations

from oh_no_my_claudecode.retrieval_eval.code_dataset import (
    EXPECTED_CODE_DATASET_SHA,
    load_code_dataset,
)
from oh_no_my_claudecode.retrieval_eval.runner import run_code_evaluation

# ---------------------------------------------------------------------------
# Frozen SHA integrity
# ---------------------------------------------------------------------------


class TestCodeDatasetIntegrity:
    def test_dataset_loads_without_error(self) -> None:
        ds = load_code_dataset(verify_sha=True)
        assert len(ds.corpus) >= 100
        assert len(ds.cases) >= 40

    def test_dataset_sha_matches_expected_constant(self) -> None:
        ds = load_code_dataset(verify_sha=False)
        assert ds.dataset_sha == EXPECTED_CODE_DATASET_SHA

    def test_dataset_sha_verifies_against_content(self) -> None:
        # Must not raise — SHA is pinned correctly.
        ds = load_code_dataset(verify_sha=True)
        assert ds.dataset_sha == EXPECTED_CODE_DATASET_SHA

    def test_corpus_ids_are_unique(self) -> None:
        ds = load_code_dataset()
        ids = [e.id for e in ds.corpus]
        assert len(ids) == len(set(ids)), "Corpus chunk IDs must be unique"

    def test_case_query_ids_are_unique(self) -> None:
        ds = load_code_dataset()
        qids = [c.query_id for c in ds.cases]
        assert len(qids) == len(set(qids)), "Case query IDs must be unique"

    def test_relevant_ids_are_in_corpus(self) -> None:
        ds = load_code_dataset()
        corpus_ids = {e.id for e in ds.corpus}
        for case in ds.cases:
            for rel_id in case.relevant_ids:
                assert rel_id in corpus_ids, (
                    f"Case {case.query_id}: relevant_id '{rel_id}' not in corpus"
                )

    def test_surfaces_are_code_bm25_and_code_hybrid(self) -> None:
        ds = load_code_dataset()
        surfaces = {c.surface for c in ds.cases}
        assert "code-bm25" in surfaces
        assert "code-hybrid" in surfaces

    def test_bm25_and_hybrid_case_counts_are_equal(self) -> None:
        ds = load_code_dataset()
        bm25_cases = ds.cases_for_surface("code-bm25")
        hybrid_cases = ds.cases_for_surface("code-hybrid")
        assert len(bm25_cases) == len(hybrid_cases), (
            "code-bm25 and code-hybrid must have the same number of cases"
        )
        assert len(bm25_cases) >= 30, "Expected at least 30 cases per surface"

    def test_parallel_cases_share_query_text(self) -> None:
        """Every code-bm25 query must have an identical code-hybrid counterpart."""
        ds = load_code_dataset()
        bm25 = sorted(ds.cases_for_surface("code-bm25"), key=lambda c: c.query_id)
        hybrid = sorted(ds.cases_for_surface("code-hybrid"), key=lambda c: c.query_id)
        assert len(bm25) == len(hybrid)
        for b, h in zip(bm25, hybrid, strict=True):
            assert b.query == h.query, (
                f"BM25 case {b.query_id} and hybrid case {h.query_id} must share query text"
            )
            assert b.relevant_ids == h.relevant_ids

    def test_corpus_has_code_chunk_fields(self) -> None:
        ds = load_code_dataset()
        entry = ds.corpus[0]
        assert entry.id
        assert entry.kind in {"function", "class", "method"}
        assert entry.path
        assert entry.symbol
        assert entry.content


# ---------------------------------------------------------------------------
# Adapter smoke tests
# ---------------------------------------------------------------------------


class TestCodeLexicalAdapter:
    def test_setup_and_retrieve_returns_list(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.code_adapters import CodeLexicalAdapter

        ds = load_code_dataset()
        adapter = CodeLexicalAdapter()
        adapter.setup(ds)  # type: ignore[arg-type]
        try:
            result = adapter.retrieve("function that recall at k", k=10)
            assert isinstance(result, list)
            assert len(result) <= 10
            assert all(isinstance(r, str) for r in result)
        finally:
            adapter.teardown()

    def test_retrieve_ids_are_in_corpus(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.code_adapters import CodeLexicalAdapter

        ds = load_code_dataset()
        corpus_ids = {e.id for e in ds.corpus}
        adapter = CodeLexicalAdapter()
        adapter.setup(ds)  # type: ignore[arg-type]
        try:
            result = adapter.retrieve("BM25 retrieval corpus search", k=10)
            for rid in result:
                assert rid in corpus_ids, f"'{rid}' is not a corpus chunk ID"
        finally:
            adapter.teardown()

    def test_surface_name_is_code_bm25(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.code_adapters import CodeLexicalAdapter

        assert CodeLexicalAdapter.surface_name == "code-bm25"


class TestCodeHybridAdapter:
    def test_setup_and_retrieve_returns_list(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.code_adapters import CodeHybridAdapter

        ds = load_code_dataset()
        adapter = CodeHybridAdapter()
        adapter.setup(ds)  # type: ignore[arg-type]
        try:
            result = adapter.retrieve("function that computes recall at k", k=10)
            assert isinstance(result, list)
            assert len(result) <= 10
        finally:
            adapter.teardown()

    def test_surface_name_is_code_hybrid(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.code_adapters import CodeHybridAdapter

        assert CodeHybridAdapter.surface_name == "code-hybrid"


# ---------------------------------------------------------------------------
# run_code_evaluation integration
# ---------------------------------------------------------------------------


class TestRunCodeEvaluation:
    def test_report_has_code_dataset_sha(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.code_adapters import code_adapters

        report = run_code_evaluation(code_adapters())
        assert report.dataset_sha == EXPECTED_CODE_DATASET_SHA

    def test_report_has_both_surfaces(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.code_adapters import code_adapters

        report = run_code_evaluation(code_adapters())
        surface_names = {sr.surface_name for sr in report.surface_reports}
        assert "code-bm25" in surface_names
        assert "code-hybrid" in surface_names

    def test_both_surfaces_not_skipped(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.code_adapters import code_adapters

        report = run_code_evaluation(code_adapters())
        for sr in report.surface_reports:
            assert not sr.skipped, (
                f"Surface {sr.surface_name} unexpectedly skipped: {sr.skip_reason}"
            )

    def test_surfaces_have_nonzero_cases(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.code_adapters import code_adapters

        report = run_code_evaluation(code_adapters())
        for sr in report.surface_reports:
            assert sr.n_cases >= 30

    def test_metrics_are_in_range(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.code_adapters import code_adapters

        report = run_code_evaluation(code_adapters())
        for sr in report.surface_reports:
            assert 0.0 <= sr.mean_recall_at_10 <= 1.0
            assert 0.0 <= sr.mean_mrr_at_10 <= 1.0
            assert 0.0 <= sr.mean_ndcg_at_10 <= 1.0
            assert sr.latency_p50_ms >= 0.0

    def test_to_dict_contains_code_surfaces(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.code_adapters import code_adapters

        report = run_code_evaluation(code_adapters())
        d = report.to_dict()
        surfaces = {s["surface"] for s in d["surfaces"]}
        assert "code-bm25" in surfaces
        assert "code-hybrid" in surfaces

    def test_to_markdown_contains_code_surfaces(self) -> None:
        from oh_no_my_claudecode.retrieval_eval.code_adapters import code_adapters

        report = run_code_evaluation(code_adapters())
        md = report.to_markdown()
        assert "code-bm25" in md
        assert "code-hybrid" in md

    def test_bm25_recall_at_10_above_zero(self) -> None:
        """BM25 should find at least SOME of the 40 code queries correctly."""
        from oh_no_my_claudecode.retrieval_eval.code_adapters import code_adapters

        report = run_code_evaluation(code_adapters())
        bm25_sr = next(
            sr for sr in report.surface_reports if sr.surface_name == "code-bm25"
        )
        assert bm25_sr.mean_recall_at_10 > 0.0

    def test_hybrid_recall_at_10_above_zero(self) -> None:
        """Hybrid should also find at least some queries."""
        from oh_no_my_claudecode.retrieval_eval.code_adapters import code_adapters

        report = run_code_evaluation(code_adapters())
        hybrid_sr = next(
            sr for sr in report.surface_reports if sr.surface_name == "code-hybrid"
        )
        assert hybrid_sr.mean_recall_at_10 > 0.0


# ---------------------------------------------------------------------------
# Frozen hash guard — pinned value must never silently drift
# ---------------------------------------------------------------------------


class TestFrozenHashGuard:
    def test_expected_sha_constant_matches_file_sha(self) -> None:
        """The EXPECTED_CODE_DATASET_SHA constant must match the actual file content.

        This test will fail if anyone edits retrieval_code_v1.json without
        updating both the constant and the dataset_sha field in the file.
        """
        import hashlib  # noqa: PLC0415
        import json  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        dataset_path = (
            Path(__file__).resolve().parents[1] / "datasets" / "retrieval_code_v1.json"
        )
        raw = json.loads(dataset_path.read_text(encoding="utf-8"))
        content = {
            "version": raw["version"],
            "corpus": raw["corpus"],
            "cases": raw["cases"],
        }
        computed = hashlib.sha256(
            json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        assert computed == EXPECTED_CODE_DATASET_SHA, (
            f"retrieval_code_v1.json SHA changed!\n"
            f"  Expected: {EXPECTED_CODE_DATASET_SHA}\n"
            f"  Computed: {computed}\n"
            "Update EXPECTED_CODE_DATASET_SHA in code_dataset.py if you intentionally"
            " rebuilt the dataset."
        )
