"""Tests for the onmc benchmark suite.

Methodology notes
-----------------
- Timing is deterministic via an injected timer — tests never read wall-clock.
- Seeded memories are written to a real SQLiteStorage so recall + FTS paths
  exercise genuine code paths.
- SIM metrics must match the deterministic harness exactly.
- Empty/small brain must degrade gracefully (no div-by-zero, no crash).
- CLI tests check exit codes + JSON shape.  Never call a network or LLM.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.bench.harness import BUILTIN_SCENARIO, run_benchmark
from oh_no_my_claudecode.benchmark.suite import (
    BenchmarkMetric,
    BenchmarkReport,
    run_benchmark_suite,
)
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COUNTER = itertools.count()


def _make_memory(*, kind: MemoryKind = MemoryKind.FAILED_APPROACH) -> MemoryEntry:
    idx = next(_COUNTER)
    now = utc_now()
    return MemoryEntry(
        id=f"bench-test-mem-{idx}",
        kind=kind,
        title=f"cache invalidation race condition {idx}",
        summary=f"bypass cache layer entirely in worker causes stale reads {idx}",
        details=f"use explicit key to invalidate_cache for deterministic results {idx}",
        source_type=SourceType.MANUAL,
        source_ref=f"src/worker_{idx}.py",
        tags=[kind.value],
        confidence=0.85,
        created_at=now,
        updated_at=now,
    )


def _seeded_storage(tmp_path: Path, *, count: int = 5) -> SQLiteStorage:
    """Return an initialised SQLiteStorage with *count* seeded memories."""
    db = SQLiteStorage(tmp_path / "bench_test.db")
    db.initialize()
    if count > 0:
        entries = [_make_memory() for _ in range(count)]
        db.upsert_memories(entries)
    return db


def _make_timer(values: list[float]) -> object:
    """Return a zero-argument timer that pops values from *values* in order.

    If values are exhausted the timer returns 0.0.  Values should be provided
    in pairs (start, end) so that each timing call pair yields a positive delta.
    """
    idx = 0

    def _timer() -> float:
        nonlocal idx
        if idx < len(values):
            v = values[idx]
            idx += 1
            return v
        return 0.0

    return _timer


# ---------------------------------------------------------------------------
# BenchmarkMetric + BenchmarkReport structural tests
# ---------------------------------------------------------------------------


class TestBenchmarkMetricStructure:
    def test_metric_is_frozen(self) -> None:
        m = BenchmarkMetric(name="x", value=1.0, unit="ms", kind="measured")
        with pytest.raises((AttributeError, TypeError)):
            m.name = "y"  # type: ignore[misc]

    def test_metric_kind_values(self) -> None:
        m_measured = BenchmarkMetric(name="a", value=0.0, unit="ms", kind="measured")
        m_sim = BenchmarkMetric(name="b", value=0.0, unit="%", kind="sim")
        assert m_measured.kind == "measured"
        assert m_sim.kind == "sim"

    def test_report_metrics_by_kind(self) -> None:
        report = BenchmarkReport(
            metrics=[
                BenchmarkMetric(name="a", value=1.0, unit="ms", kind="measured"),
                BenchmarkMetric(name="b", value=2.0, unit="%", kind="sim"),
                BenchmarkMetric(name="c", value=3.0, unit="count", kind="measured"),
            ],
            brain_memory_count=10,
        )
        measured = report.metrics_by_kind("measured")
        sim = report.metrics_by_kind("sim")
        assert len(measured) == 2
        assert len(sim) == 1
        assert all(m.kind == "measured" for m in measured)
        assert all(m.kind == "sim" for m in sim)


# ---------------------------------------------------------------------------
# run_benchmark_suite — metric set presence + kind labels
# ---------------------------------------------------------------------------


class TestRunBenchmarkSuiteMetricSet:
    """Verify all expected metrics are present with correct kind labels."""

    def setup_method(self) -> None:
        pass  # storage created per-test

    def _run(self, tmp_path: Path, *, count: int = 5) -> BenchmarkReport:
        storage = _seeded_storage(tmp_path, count=count)
        # Use a deterministic timer: alternating start/end pairs producing 1 ms each.
        pairs = [(i * 0.002, i * 0.002 + 0.001) for i in range(1000)]
        timer_values = [v for pair in pairs for v in pair]
        timer = _make_timer(timer_values)
        repo_root = tmp_path / "test-repo"
        repo_root.mkdir(exist_ok=True)
        return run_benchmark_suite(
            storage,
            repo_root,
            runs=2,
            now="2099-01-01T00:00:00Z",
            timer=timer,  # type: ignore[arg-type]
        )

    def test_measured_metrics_present(self, tmp_path: Path) -> None:
        report = self._run(tmp_path)
        names = {m.name for m in report.metrics}
        assert "brain_memory_count" in names
        assert "recall_p50_ms" in names
        assert "recall_p95_ms" in names
        assert "recall_hits_per_query" in names
        assert "terse_vs_verbose_char_reduction_pct" in names
        assert "toon_vs_json_char_reduction_pct" in names

    def test_sim_metrics_present(self, tmp_path: Path) -> None:
        report = self._run(tmp_path)
        names = {m.name for m in report.metrics}
        assert "sim_repeated_failure_rate_delta" in names
        assert "sim_wasted_attempts_saved" in names
        assert "sim_context_tokens_pct_reduction" in names
        assert "sim_tasks_resolved_delta" in names

    def test_measured_metrics_have_correct_kind(self, tmp_path: Path) -> None:
        report = self._run(tmp_path)
        measured_names = {
            "brain_memory_count",
            "recall_p50_ms",
            "recall_p95_ms",
            "recall_hits_per_query",
            "terse_vs_verbose_char_reduction_pct",
            "toon_vs_json_char_reduction_pct",
        }
        for m in report.metrics:
            if m.name in measured_names:
                assert m.kind == "measured", f"{m.name} should be 'measured', got {m.kind!r}"

    def test_sim_metrics_have_correct_kind(self, tmp_path: Path) -> None:
        report = self._run(tmp_path)
        sim_names = {
            "sim_repeated_failure_rate_delta",
            "sim_wasted_attempts_saved",
            "sim_context_tokens_pct_reduction",
            "sim_tasks_resolved_delta",
        }
        for m in report.metrics:
            if m.name in sim_names:
                assert m.kind == "sim", f"{m.name} should be 'sim', got {m.kind!r}"

    def test_brain_memory_count_matches_seeded(self, tmp_path: Path) -> None:
        report = self._run(tmp_path, count=5)
        assert report.brain_memory_count == 5

    def test_generated_note_contains_repo_name(self, tmp_path: Path) -> None:
        report = self._run(tmp_path)
        assert "test-repo" in report.generated_note

    def test_generated_note_contains_reproduce_hint(self, tmp_path: Path) -> None:
        report = self._run(tmp_path)
        assert "onmc benchmark" in report.generated_note


# ---------------------------------------------------------------------------
# Reductions are within [0, 100] range
# ---------------------------------------------------------------------------


class TestReductionBounds:
    def test_terse_vs_verbose_in_range(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path, count=10)
        report = run_benchmark_suite(storage, tmp_path, runs=1, now="2099-01-01T00:00:00Z")
        m = next(
            m for m in report.metrics if m.name == "terse_vs_verbose_char_reduction_pct"
        )
        assert -100.0 <= m.value <= 100.0

    def test_toon_vs_json_in_range(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path, count=10)
        report = run_benchmark_suite(storage, tmp_path, runs=1, now="2099-01-01T00:00:00Z")
        m = next(m for m in report.metrics if m.name == "toon_vs_json_char_reduction_pct")
        assert -100.0 <= m.value <= 100.0


# ---------------------------------------------------------------------------
# SIM metrics match the deterministic harness exactly
# ---------------------------------------------------------------------------


class TestSimMetricsMatchHarness:
    """The SIM section must reproduce bench/harness.py numbers exactly."""

    def test_sim_matches_harness_with_empty_brain(self, tmp_path: Path) -> None:
        # SIM always runs BUILTIN_SCENARIO regardless of brain size.
        storage = _seeded_storage(tmp_path, count=0)
        report = run_benchmark_suite(storage, tmp_path, runs=1, now="2099-01-01T00:00:00Z")

        # Reference: canonical BUILTIN_SCENARIO (not an empty-memories variant)
        ref = run_benchmark(BUILTIN_SCENARIO)

        sim_delta = next(
            m for m in report.metrics if m.name == "sim_repeated_failure_rate_delta"
        ).value
        # sim_repeated_failure_rate_delta is now in % (fraction * 100)
        assert sim_delta == pytest.approx(ref.repeated_failure_rate_delta * 100.0, abs=1e-4)

        sim_wasted = next(
            m for m in report.metrics if m.name == "sim_wasted_attempts_saved"
        ).value
        assert sim_wasted == pytest.approx(float(ref.wasted_attempts_delta), abs=1e-6)

        sim_ctx = next(
            m for m in report.metrics if m.name == "sim_context_tokens_pct_reduction"
        ).value
        assert sim_ctx == pytest.approx(ref.context_tokens_pct_reduction, abs=0.1)

    def test_sim_context_token_reduction_is_positive_and_canonical(
        self, tmp_path: Path
    ) -> None:
        """sim_context_tokens_pct_reduction must be ~97% (positive, never negative)."""
        storage = _seeded_storage(tmp_path, count=5)
        report = run_benchmark_suite(storage, tmp_path, runs=1, now="2099-01-01T00:00:00Z")

        sim_ctx = next(
            m for m in report.metrics if m.name == "sim_context_tokens_pct_reduction"
        ).value
        # Must be positive (reduction, not inflation)
        assert sim_ctx > 0.0, f"Expected positive reduction, got {sim_ctx}"
        # Canonical BUILTIN_SCENARIO value: ~97.3%
        ref = run_benchmark(BUILTIN_SCENARIO)
        assert sim_ctx == pytest.approx(ref.context_tokens_pct_reduction, abs=0.2)

    def test_sim_repeated_failure_rate_shown_as_percentage(
        self, tmp_path: Path
    ) -> None:
        """sim_repeated_failure_rate_delta must be ~100.0 (percent), not 1.0 (fraction)."""
        storage = _seeded_storage(tmp_path, count=5)
        report = run_benchmark_suite(storage, tmp_path, runs=1, now="2099-01-01T00:00:00Z")

        m = next(
            m for m in report.metrics if m.name == "sim_repeated_failure_rate_delta"
        )
        # Unit must be % not fraction
        assert m.unit == "%"
        # Value must be ~100 (meaning 100% reduction), not 1.0 (fraction)
        assert m.value == pytest.approx(100.0, abs=1e-4)

    def test_sim_numbers_independent_of_brain_size(self, tmp_path: Path) -> None:
        """SIM values must be identical for a 1-memory and a 100-memory brain."""
        db_small = tmp_path / "small"
        db_small.mkdir()
        db_large = tmp_path / "large"
        db_large.mkdir()

        storage_small = _seeded_storage(db_small, count=1)
        storage_large = _seeded_storage(db_large, count=100)

        report_small = run_benchmark_suite(
            storage_small, db_small, runs=1, now="2099-01-01T00:00:00Z"
        )
        report_large = run_benchmark_suite(
            storage_large, db_large, runs=1, now="2099-01-01T00:00:00Z"
        )

        sim_names = {
            "sim_repeated_failure_rate_delta",
            "sim_wasted_attempts_saved",
            "sim_context_tokens_pct_reduction",
            "sim_tasks_resolved_delta",
        }
        small_sim = {m.name: m.value for m in report_small.metrics if m.name in sim_names}
        large_sim = {m.name: m.value for m in report_large.metrics if m.name in sim_names}

        for name in sim_names:
            assert small_sim[name] == pytest.approx(large_sim[name], abs=1e-4), (
                f"SIM metric {name!r} differs between 1-memory and 100-memory brain: "
                f"{small_sim[name]} vs {large_sim[name]}"
            )


# ---------------------------------------------------------------------------
# Deterministic timing via injected timer
# ---------------------------------------------------------------------------


class TestInjectableTimer:
    def test_p50_ms_reflects_injected_timer(self, tmp_path: Path) -> None:
        """With a synthetic timer producing 5 ms per call pair, p50 should be 5 ms."""
        storage = _seeded_storage(tmp_path, count=0)

        # timer returns 0.0, 0.005, 0.0, 0.005, ... so each pair = 5 ms
        step = 0.005
        timer_values = [v for i in range(500) for v in (i * step * 2, i * step * 2 + step)]
        timer = _make_timer(timer_values)

        report = run_benchmark_suite(
            storage,
            tmp_path,
            runs=2,
            now="2099-01-01T00:00:00Z",
            timer=timer,  # type: ignore[arg-type]
        )
        p50 = next(m for m in report.metrics if m.name == "recall_p50_ms")
        # All latencies are 5 ms → p50 = 5 ms
        assert p50.value == pytest.approx(5.0, abs=0.01)

    def test_p95_ms_reflects_injected_timer(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path, count=0)
        # All 10 ms → p95 also 10 ms
        step = 0.010
        timer_values = [v for i in range(500) for v in (i * step * 2, i * step * 2 + step)]
        timer = _make_timer(timer_values)

        report = run_benchmark_suite(
            storage,
            tmp_path,
            runs=2,
            now="2099-01-01T00:00:00Z",
            timer=timer,  # type: ignore[arg-type]
        )
        p95 = next(m for m in report.metrics if m.name == "recall_p95_ms")
        assert p95.value == pytest.approx(10.0, abs=0.01)


# ---------------------------------------------------------------------------
# Empty / small brain graceful degradation
# ---------------------------------------------------------------------------


class TestEmptyBrainGraceful:
    def test_empty_brain_no_crash(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path, count=0)
        # Must not raise
        report = run_benchmark_suite(storage, tmp_path, runs=1, now="2099-01-01T00:00:00Z")
        assert isinstance(report, BenchmarkReport)

    def test_empty_brain_memory_count_zero(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path, count=0)
        report = run_benchmark_suite(storage, tmp_path, runs=1, now="2099-01-01T00:00:00Z")
        assert report.brain_memory_count == 0

    def test_empty_brain_no_div_zero(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path, count=0)
        report = run_benchmark_suite(storage, tmp_path, runs=1, now="2099-01-01T00:00:00Z")
        for m in report.metrics:
            assert m.value == m.value, f"NaN in metric {m.name}"  # nan check: NaN != NaN

    def test_single_memory_no_crash(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path, count=1)
        report = run_benchmark_suite(storage, tmp_path, runs=1, now="2099-01-01T00:00:00Z")
        assert isinstance(report, BenchmarkReport)
        assert report.brain_memory_count == 1

    def test_recall_hits_zero_when_empty(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path, count=0)
        report = run_benchmark_suite(storage, tmp_path, runs=1, now="2099-01-01T00:00:00Z")
        m = next(m for m in report.metrics if m.name == "recall_hits_per_query")
        assert m.value == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# CLI: onmc benchmark exit codes + JSON shape
# ---------------------------------------------------------------------------


class TestCLIBenchmark:
    def test_cli_exits_nonzero_uninitialised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["benchmark"])
        assert result.exit_code != 0

    def test_cli_exits_zero_on_initialised_repo(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(sample_repo)
        from oh_no_my_claudecode.core.service import OnmcService

        svc = OnmcService(sample_repo)
        svc.init_project()
        svc.ingest()
        runner = CliRunner()
        result = runner.invoke(app, ["benchmark", "--runs", "2"])
        assert result.exit_code == 0, result.output

    def test_cli_json_flag_exits_zero_on_initialised_repo(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(sample_repo)
        from oh_no_my_claudecode.core.service import OnmcService

        svc = OnmcService(sample_repo)
        svc.init_project()
        svc.ingest()
        runner = CliRunner()
        result = runner.invoke(app, ["benchmark", "--runs", "2", "--json"])
        assert result.exit_code == 0, result.output

    def test_cli_json_shape(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(sample_repo)
        from oh_no_my_claudecode.core.service import OnmcService

        svc = OnmcService(sample_repo)
        svc.init_project()
        svc.ingest()
        runner = CliRunner()
        result = runner.invoke(app, ["benchmark", "--runs", "2", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "brain_memory_count" in data
        assert "generated_note" in data
        assert "metrics" in data
        assert isinstance(data["metrics"], list)
        assert len(data["metrics"]) > 0

    def test_cli_json_metrics_have_kind_labels(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(sample_repo)
        from oh_no_my_claudecode.core.service import OnmcService

        svc = OnmcService(sample_repo)
        svc.init_project()
        svc.ingest()
        runner = CliRunner()
        result = runner.invoke(app, ["benchmark", "--runs", "2", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        kinds = {m["kind"] for m in data["metrics"]}
        assert "measured" in kinds
        assert "sim" in kinds

    def test_cli_json_all_required_metric_fields(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(sample_repo)
        from oh_no_my_claudecode.core.service import OnmcService

        svc = OnmcService(sample_repo)
        svc.init_project()
        svc.ingest()
        runner = CliRunner()
        result = runner.invoke(app, ["benchmark", "--runs", "2", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        for m in data["metrics"]:
            assert "name" in m
            assert "value" in m
            assert "unit" in m
            assert "kind" in m
            assert m["kind"] in ("measured", "sim")

    def test_cli_runs_flag_accepted(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(sample_repo)
        from oh_no_my_claudecode.core.service import OnmcService

        svc = OnmcService(sample_repo)
        svc.init_project()
        svc.ingest()
        runner = CliRunner()
        result = runner.invoke(app, ["benchmark", "--runs", "3"])
        assert result.exit_code == 0, result.output
