"""Tests for the bench harness.

All assertions on exact numbers are intentional — the harness is deterministic
and these numbers must not change unless the built-in scenario changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.bench.harness import (
    BUILTIN_SCENARIO,
    BenchScenario,
    MemoryRecord,
    TaskSpec,
    run_benchmark,
)
from oh_no_my_claudecode.cli import app

# ---------------------------------------------------------------------------
# Determinism: two consecutive runs must be identical
# ---------------------------------------------------------------------------


def test_run_benchmark_is_deterministic() -> None:
    result_a = run_benchmark(BUILTIN_SCENARIO)
    result_b = run_benchmark(BUILTIN_SCENARIO)

    assert (
        result_a.without_memory.repeated_failure_rate
        == result_b.without_memory.repeated_failure_rate
    )
    assert result_a.without_memory.wasted_attempts == result_b.without_memory.wasted_attempts
    assert result_a.without_memory.context_tokens == result_b.without_memory.context_tokens
    assert result_a.without_memory.tasks_resolved == result_b.without_memory.tasks_resolved

    assert result_a.with_memory.repeated_failure_rate == result_b.with_memory.repeated_failure_rate
    assert result_a.with_memory.wasted_attempts == result_b.with_memory.wasted_attempts
    assert result_a.with_memory.context_tokens == result_b.with_memory.context_tokens
    assert result_a.with_memory.tasks_resolved == result_b.with_memory.tasks_resolved


# ---------------------------------------------------------------------------
# Exact stable numbers for the built-in scenario
# ---------------------------------------------------------------------------
# The built-in scenario has 5 tasks.
# WITHOUT memory:
#   - task-cache: hits 2 dead-ends before correct → 2 wasted, repeated_failure=True
#   - task-sqlite: hits 2 dead-ends → 2 wasted, repeated_failure=True
#   - task-cli: hits 1 dead-end → 1 wasted, repeated_failure=True
#   - task-hook: hits 2 dead-ends → 2 wasted, repeated_failure=True
#   - task-ruff: hits 2 dead-ends → 2 wasted, repeated_failure=True
#   Total: 5/5 repeated failures, 9 wasted attempts, 5 resolved (budget=3, enough)
#   Context tokens: 800 * 5 = 4000
#
# WITH memory:
#   - all dead-ends covered by memory → 0 wasted, 0 repeated failures
#   - all tasks resolve on first non-dead-end candidate
#   Context tokens: sum of tokenize(relevant memories per task)
#   All 5 resolved.


def test_builtin_without_memory_exact() -> None:
    result = run_benchmark(BUILTIN_SCENARIO)
    w = result.without_memory

    assert w.repeated_failure_rate == pytest.approx(1.0)  # 5/5
    assert w.wasted_attempts == 9
    assert w.context_tokens == 4000  # 800 * 5
    assert w.tasks_resolved == 5


def test_builtin_with_memory_exact() -> None:
    result = run_benchmark(BUILTIN_SCENARIO)
    m = result.with_memory

    assert m.repeated_failure_rate == pytest.approx(0.0)
    assert m.wasted_attempts == 0
    assert m.tasks_resolved == 5
    # Context tokens must be substantially less than baseline (800*5=4000)
    assert m.context_tokens < 4000


# ---------------------------------------------------------------------------
# WITH memory beats WITHOUT on key metrics
# ---------------------------------------------------------------------------


def test_with_memory_beats_without_repeated_failure() -> None:
    result = run_benchmark(BUILTIN_SCENARIO)
    assert result.with_memory.repeated_failure_rate < result.without_memory.repeated_failure_rate


def test_with_memory_beats_without_context_tokens() -> None:
    result = run_benchmark(BUILTIN_SCENARIO)
    assert result.with_memory.context_tokens < result.without_memory.context_tokens


def test_with_memory_beats_without_wasted_attempts() -> None:
    result = run_benchmark(BUILTIN_SCENARIO)
    assert result.with_memory.wasted_attempts < result.without_memory.wasted_attempts


# ---------------------------------------------------------------------------
# Delta helpers
# ---------------------------------------------------------------------------


def test_deltas_are_positive() -> None:
    result = run_benchmark(BUILTIN_SCENARIO)
    assert result.repeated_failure_rate_delta > 0.0
    assert result.wasted_attempts_delta > 0
    assert result.context_tokens_pct_reduction > 0.0


# ---------------------------------------------------------------------------
# Minimal custom scenario: partial memory coverage
# ---------------------------------------------------------------------------


def test_partial_memory_coverage() -> None:
    """Memory only covers one dead-end of two; wasted_attempts is reduced but not to zero."""
    scenario = BenchScenario(
        name="partial-coverage",
        description="Only one dead-end is in memory.",
        tasks=[
            TaskSpec(
                task_id="t1",
                description="example task",
                dead_ends=["bad-a", "bad-b"],
                correct_approach="good",
                candidate_pool_without=["bad-a", "bad-b", "good"],
                attempt_budget=5,
            )
        ],
        memories=[
            MemoryRecord(kind="failed_approach", summary="bad-a", relevant_to=["t1"]),
        ],
        baseline_context_tokens=100,
    )
    result = run_benchmark(scenario)
    # WITHOUT: tries bad-a, bad-b, then good → 2 wasted
    assert result.without_memory.wasted_attempts == 2
    # WITH: skips bad-a (in memory), tries bad-b (not in memory → wasted), then good
    assert result.with_memory.wasted_attempts == 1
    # Still fewer wasted attempts with memory
    assert result.with_memory.wasted_attempts < result.without_memory.wasted_attempts


def test_empty_memory_equals_without() -> None:
    """When the memory store is empty, with-memory behaves identically to without."""
    scenario = BenchScenario(
        name="no-memory",
        description="Empty memory store.",
        tasks=list(BUILTIN_SCENARIO.tasks),
        memories=[],
        baseline_context_tokens=BUILTIN_SCENARIO.baseline_context_tokens,
    )
    result = run_benchmark(scenario)
    # With no memories: no dead-ends blocked, same wasted attempts
    assert result.with_memory.wasted_attempts == result.without_memory.wasted_attempts
    # Context tokens from empty brief = 0
    assert result.with_memory.context_tokens == 0


# ---------------------------------------------------------------------------
# to_markdown produces a non-empty table
# ---------------------------------------------------------------------------


def test_to_markdown_contains_metrics() -> None:
    result = run_benchmark(BUILTIN_SCENARIO)
    md = result.to_markdown()
    assert "Repeated-failure rate" in md
    assert "Wasted attempts" in md
    assert "Context tokens" in md
    assert "Tasks resolved" in md
    assert "deterministic simulation" in md


# ---------------------------------------------------------------------------
# CLI: onmc bench exits 0 and prints the deltas
# ---------------------------------------------------------------------------


def test_cli_bench_exits_zero() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["bench"])
    assert result.exit_code == 0, result.output


def test_cli_bench_prints_headline_deltas() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["bench"])
    assert result.exit_code == 0
    # The headline delta line must mention context tokens reduction
    assert "context tokens" in result.output.lower()


def test_cli_bench_json_flag() -> None:
    import json

    runner = CliRunner()
    result = runner.invoke(app, ["bench", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "scenario" in data
    assert "without_memory" in data
    assert "with_memory" in data
    assert "deltas" in data
    # Key deltas must be positive (memory helps)
    assert data["deltas"]["repeated_failure_rate"] > 0
    assert data["deltas"]["context_tokens_pct_reduction"] > 0


# ---------------------------------------------------------------------------
# CLI: --repo-memory flag requires an initialized repo
# ---------------------------------------------------------------------------


def test_cli_bench_repo_memory_requires_init(tmp_path: Path, monkeypatch: object) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["bench", "--repo-memory"])
    # Should exit non-zero because no .onmc/config.yaml found
    assert result.exit_code != 0


def test_cli_bench_repo_memory_on_initialized_repo(
    sample_repo: Path, monkeypatch: object
) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    from oh_no_my_claudecode.core.service import OnmcService

    svc = OnmcService(sample_repo)
    svc.init_project()
    svc.ingest()
    runner = CliRunner()
    result = runner.invoke(app, ["bench", "--repo-memory"])
    assert result.exit_code == 0, result.output
