"""Tests for the onmc eval harness.

All tests are deterministic and offline — no LLM calls, no network.
The sample_repo fixture from conftest.py is reused; memories are seeded
inline so each test is self-contained.

Coverage
--------
- files_hit True with memory / False without memory
- deadend_hit True with memory for a FAILED_APPROACH / False without
- compare_evals shows positive with-vs-without delta
- pass_rate / score are deterministic
- --fail-under exits nonzero below threshold, zero above
- eval create --from-memory derives a sane case
- empty suite graceful (vacuous pass, no crash)
- --json output shapes for both `run` and `compare`
- EvalComparison.score_delta, pass_rate_delta, chars_delta semantics
- store.save_eval_case / load_eval_case / load_all_eval_cases round-trip
- EvalReport.to_markdown and EvalComparison.to_markdown
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode import init
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.evals.harness import compare_evals, run_evals
from oh_no_my_claudecode.evals.models import EvalCase, EvalComparison
from oh_no_my_claudecode.evals.store import (
    create_eval_case_from_task,
    load_all_eval_cases,
    load_eval_case,
    save_eval_case,
)
from oh_no_my_claudecode.models import MemoryKind, SourceType
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers: seed memories into storage
# ---------------------------------------------------------------------------


def _seed_memory(
    storage: SQLiteStorage,
    *,
    kind: MemoryKind = MemoryKind.INVARIANT,
    title: str,
    summary: str,
    tags: list[str] | None = None,
) -> str:
    """Insert a memory and return its id."""
    from oh_no_my_claudecode.models.memory import MemoryEntry

    now = utc_now()
    mid = stable_id(kind.value, title, summary, "test:seed", prefix="ev")
    entry = MemoryEntry(
        id=mid,
        kind=kind,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.MANUAL,
        source_ref="test:seed",
        tags=tags or [kind.value],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return mid


def _seed_failed_approach(
    storage: SQLiteStorage,
    *,
    title: str,
    summary: str,
    tags: list[str] | None = None,
) -> str:
    """Insert a FAILED_APPROACH memory and return its id."""
    return _seed_memory(
        storage,
        kind=MemoryKind.FAILED_APPROACH,
        title=title,
        summary=summary,
        tags=tags,
    )


# ---------------------------------------------------------------------------
# EvalCase dataclass basics
# ---------------------------------------------------------------------------


def test_eval_case_defaults() -> None:
    """EvalCase can be constructed with minimal required fields."""
    case = EvalCase(id="test-case", query="fix the cache bug")
    assert case.id == "test-case"
    assert case.query == "fix the cache bug"
    assert case.expected_files == []
    assert case.expected_deadend_substrings == []
    assert case.note == ""


# ---------------------------------------------------------------------------
# Store: save / load round-trip
# ---------------------------------------------------------------------------


def test_store_round_trip(tmp_path: Path) -> None:
    """EvalCase saves and loads correctly from .onmc/evals/<id>.json."""
    case = EvalCase(
        id="round-trip-case",
        query="cache invalidation bypass",
        expected_files=["src/cache.py", "ev_memid123"],
        expected_deadend_substrings=["sleep", "bypass"],
        note="Test round-trip",
    )
    path = save_eval_case(tmp_path, case)
    assert path.exists()
    assert path.name == "round-trip-case.json"

    loaded = load_eval_case(tmp_path, "round-trip-case")
    assert loaded is not None
    assert loaded.id == case.id
    assert loaded.query == case.query
    assert loaded.expected_files == case.expected_files
    assert loaded.expected_deadend_substrings == case.expected_deadend_substrings
    assert loaded.note == case.note


def test_store_load_nonexistent(tmp_path: Path) -> None:
    """load_eval_case returns None when file does not exist."""
    result = load_eval_case(tmp_path, "does-not-exist")
    assert result is None


def test_store_load_all_empty(tmp_path: Path) -> None:
    """load_all_eval_cases returns empty list when directory is missing."""
    cases = load_all_eval_cases(tmp_path)
    assert cases == []


def test_store_load_all_multiple(tmp_path: Path) -> None:
    """load_all_eval_cases returns all cases sorted by id."""
    for i in range(3):
        save_eval_case(tmp_path, EvalCase(id=f"case-{i:02d}", query=f"query {i}"))
    cases = load_all_eval_cases(tmp_path)
    assert len(cases) == 3
    assert [c.id for c in cases] == ["case-00", "case-01", "case-02"]


# ---------------------------------------------------------------------------
# Harness: with_memory=False baseline
# ---------------------------------------------------------------------------


def test_run_evals_empty_suite(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty suite returns vacuous pass (score=100, pass_rate=1.0)."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()

    report = run_evals(storage, [], with_memory=True)

    assert report.total_cases == 0
    assert report.pass_rate == 1.0
    assert report.score == 100.0
    assert report.results == []


def test_run_evals_without_memory_all_fail(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With without-memory baseline, all cases with expectations fail."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()

    cases = [
        EvalCase(
            id="case-a",
            query="cache invalidation",
            expected_files=["ev_someid"],
        ),
        EvalCase(
            id="case-b",
            query="cache bypass dead-end",
            expected_deadend_substrings=["bypass"],
        ),
    ]
    report = run_evals(storage, cases, with_memory=False)

    assert report.with_memory is False
    assert report.pass_rate == 0.0
    assert report.score == 0.0
    assert all(not r.passed for r in report.results)
    assert all(r.injected_chars == 0 for r in report.results)
    assert all(r.recall_entries == 0 for r in report.results)


# ---------------------------------------------------------------------------
# Harness: files_hit True with memory / False without
# ---------------------------------------------------------------------------


def test_files_hit_true_with_memory(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A seeded memory matching the query is surfaced by recall (files_hit=True)."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()

    mid = _seed_memory(
        storage,
        kind=MemoryKind.GOTCHA,
        title="Cache bypass invalidation gotcha",
        summary="Bypassing the cache module breaks invalidation consistency.",
    )

    case = EvalCase(
        id="files-hit-test",
        query="cache bypass invalidation",
        expected_files=[mid],  # memory_id must appear in recall
    )

    report = run_evals(storage, [case], with_memory=True)

    assert report.with_memory is True
    assert len(report.results) == 1
    r = report.results[0]
    assert r.files_hit is True, (
        f"Expected files_hit=True but got False. "
        f"recall_entries={r.recall_entries}"
    )
    assert r.passed is True


def test_files_hit_false_without_memory(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without memory, files_hit=False for cases with expected_files."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()

    mid = _seed_memory(
        storage,
        kind=MemoryKind.GOTCHA,
        title="Cache bypass invalidation gotcha",
        summary="Bypassing the cache module breaks invalidation consistency.",
    )

    case = EvalCase(
        id="files-hit-false-test",
        query="cache bypass invalidation",
        expected_files=[mid],
    )

    report = run_evals(storage, [case], with_memory=False)

    assert report.with_memory is False
    r = report.results[0]
    assert r.files_hit is False
    assert r.passed is False


# ---------------------------------------------------------------------------
# Harness: deadend_hit for FAILED_APPROACH
# ---------------------------------------------------------------------------


def test_deadend_hit_true_with_memory(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A FAILED_APPROACH memory is surfaced by guard (deadend_hit=True)."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()

    _seed_failed_approach(
        storage,
        title="Direct cache bypass via sleep",
        summary="Tried to bypass the cache boundary by adding a sleep call.",
    )

    case = EvalCase(
        id="deadend-hit-test",
        query="cache bypass sleep invalidation",
        expected_deadend_substrings=["sleep"],
    )

    report = run_evals(storage, [case], with_memory=True)

    r = report.results[0]
    assert r.deadend_hit is True, (
        "Expected deadend_hit=True but got False. Guard should surface the FAILED_APPROACH."
    )
    assert r.passed is True


def test_deadend_hit_false_without_memory(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without memory, deadend_hit=False for cases with expected_deadend_substrings."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()

    _seed_failed_approach(
        storage,
        title="Direct cache bypass via sleep",
        summary="Tried to bypass the cache boundary by adding a sleep call.",
    )

    case = EvalCase(
        id="deadend-hit-false-test",
        query="cache bypass sleep invalidation",
        expected_deadend_substrings=["sleep"],
    )

    report = run_evals(storage, [case], with_memory=False)

    r = report.results[0]
    assert r.deadend_hit is False
    assert r.passed is False


# ---------------------------------------------------------------------------
# compare_evals: positive with-vs-without delta
# ---------------------------------------------------------------------------


def test_compare_evals_positive_delta(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """compare_evals shows a positive score_delta when memory actually helps."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()

    mid = _seed_memory(
        storage,
        kind=MemoryKind.INVARIANT,
        title="Cache invalidation must use explicit key",
        summary="Always pass the explicit key to invalidate_cache.",
    )
    _seed_failed_approach(
        storage,
        title="Add sleep before cache invalidation",
        summary="Tried adding sleep to wait for cache refresh. Broke determinism.",
    )

    cases = [
        EvalCase(
            id="recall-case",
            query="cache invalidation key explicit",
            expected_files=[mid],
        ),
        EvalCase(
            id="guard-case",
            query="cache invalidation sleep",
            expected_deadend_substrings=["sleep"],
        ),
    ]

    comparison = compare_evals(storage, cases)

    assert isinstance(comparison, EvalComparison)
    # With memory should score higher than without
    assert comparison.score_delta > 0, (
        f"Expected positive score_delta but got {comparison.score_delta}. "
        f"with_memory.score={comparison.with_memory.score}, "
        f"without_memory.score={comparison.without_memory.score}"
    )
    assert comparison.pass_rate_delta > 0


def test_compare_evals_without_memory_all_miss(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without-memory baseline always has score=0.0 for non-empty expected sets."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()

    mid = _seed_memory(
        storage,
        kind=MemoryKind.DECISION,
        title="Use versioned migrations for schema changes",
        summary="Schema changes go through versioned migrations.",
    )

    cases = [
        EvalCase(
            id="schema-case",
            query="schema migration versioned",
            expected_files=[mid],
        ),
    ]

    comparison = compare_evals(storage, cases)

    assert comparison.without_memory.score == 0.0
    assert comparison.without_memory.pass_rate == 0.0


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_run_evals_deterministic(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two consecutive runs with the same cases produce identical scores."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()

    mid = _seed_memory(
        storage,
        kind=MemoryKind.INVARIANT,
        title="Cache key must be deterministic",
        summary="Use stable cache keys for reliable invalidation.",
    )
    cases = [EvalCase(id="det-case", query="cache key deterministic", expected_files=[mid])]

    report_a = run_evals(storage, cases, with_memory=True)
    report_b = run_evals(storage, cases, with_memory=True)

    assert report_a.score == report_b.score
    assert report_a.pass_rate == report_b.pass_rate
    assert report_a.passed_cases == report_b.passed_cases


# ---------------------------------------------------------------------------
# create_eval_case_from_task: derives a sane case
# ---------------------------------------------------------------------------


def test_create_eval_case_from_task_basic(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_eval_case_from_task returns a non-None EvalCase with sensible fields."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()

    mid = _seed_memory(
        storage,
        kind=MemoryKind.DECISION,
        title="Cache boundary must not be bypassed",
        summary="All invalidation goes through the cache module.",
        tags=["cache", "invariant"],
    )

    case = create_eval_case_from_task(storage, mid)

    assert case is not None
    assert case.id.startswith("mem-")
    # Query should contain title or summary content
    assert "cache" in case.query.lower() or "boundary" in case.query.lower()
    # Memory id itself should be in expected_files (always added)
    assert any(mid in ef for ef in case.expected_files)
    assert "Derived from memory" in case.note


def test_create_eval_case_from_task_failed_approach(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILED_APPROACH memory populates expected_deadend_substrings with its own title."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()

    mid = _seed_failed_approach(
        storage,
        title="Sleep before cache refresh breaks worker",
        summary="Tried adding sleep to fix flaky tests.",
    )

    case = create_eval_case_from_task(storage, mid)

    assert case is not None
    # The FAILED_APPROACH title (or prefix) should be a deadend substring
    assert any("sleep" in s.lower() for s in case.expected_deadend_substrings), (
        "Expected 'sleep' in expected_deadend_substrings but got: "
        + repr(case.expected_deadend_substrings)
    )


def test_create_eval_case_from_task_missing_memory(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_eval_case_from_task returns None when memory_id does not exist."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()

    case = create_eval_case_from_task(storage, "nonexistent-id-xyz")
    assert case is None


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def test_eval_report_to_markdown(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EvalReport.to_markdown produces a non-empty table with pass_rate info."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()

    cases = [EvalCase(id="md-case", query="test query")]
    report = run_evals(storage, cases, with_memory=True)
    md = report.to_markdown()

    assert "Eval Report" in md
    assert "passed" in md.lower()
    assert "md-case" in md


def test_eval_comparison_to_markdown(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EvalComparison.to_markdown includes delta table."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()

    cases = [EvalCase(id="cmp-case", query="test query")]
    comparison = compare_evals(storage, cases)
    md = comparison.to_markdown()

    assert "Eval Comparison" in md
    assert "without-memory" in md.lower() or "without memory" in md.lower()
    assert "Delta" in md


# ---------------------------------------------------------------------------
# CLI: onmc eval run
# ---------------------------------------------------------------------------


def test_cli_eval_run_empty_suite(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """onmc eval run with no cases exits 0 and prints a summary."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()
    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 0, result.output


def test_cli_eval_run_json(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """onmc eval run --json outputs valid JSON with expected shape."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()
    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    result = runner.invoke(app, ["eval", "run", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "with_memory" in data
    assert "total_cases" in data
    assert "passed_cases" in data
    assert "pass_rate" in data
    assert "score" in data
    assert "mean_injected_chars" in data
    assert "results" in data
    assert isinstance(data["results"], list)


def test_cli_eval_run_fail_under_exit_zero(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--fail-under exits 0 when score >= threshold (empty suite = 100 score)."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()
    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    # Empty suite → score=100 → above 80 threshold
    result = runner.invoke(app, ["eval", "run", "--fail-under", "80"])
    assert result.exit_code == 0, result.output


def test_cli_eval_run_fail_under_exit_nonzero(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--fail-under exits 1 when score < threshold."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()
    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    # Seed a case that will fail (expected_files that don't exist in brain)
    from oh_no_my_claudecode.evals.models import EvalCase
    from oh_no_my_claudecode.evals.store import save_eval_case

    save_eval_case(
        sample_repo,
        EvalCase(
            id="failing-case",
            query="completely unrelated question zxyq",
            expected_files=["nonexistent-memory-id-zxyq"],
        ),
    )

    result = runner.invoke(app, ["eval", "run", "--fail-under", "50"])
    # Score should be 0 → below 50 → exit 1
    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}: {result.output}"


# ---------------------------------------------------------------------------
# CLI: onmc eval compare
# ---------------------------------------------------------------------------


def test_cli_eval_compare_json(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """onmc eval compare --json outputs valid JSON with expected shape."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()
    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    result = runner.invoke(app, ["eval", "compare", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "with_memory" in data
    assert "without_memory" in data
    assert "deltas" in data
    assert "score_delta" in data["deltas"]
    assert "pass_rate_delta" in data["deltas"]
    assert "chars_delta" in data["deltas"]


def test_cli_eval_compare_baseline_passes(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--baseline exits 0 when delta >= threshold (empty suite: delta=0, threshold=0)."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()
    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    # No cases, no threshold → vacuous pass
    result = runner.invoke(app, ["eval", "compare", "--baseline", "0"])
    assert result.exit_code == 0, result.output


def test_cli_eval_compare_baseline_nonzero(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--baseline exits 1 when score_delta < threshold."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()
    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    # Empty suite: delta=0.0 (both conditions vacuously pass with score=100)
    # so we need a case that fails to get a meaningful delta
    from oh_no_my_claudecode.evals.models import EvalCase
    from oh_no_my_claudecode.evals.store import save_eval_case

    save_eval_case(
        sample_repo,
        EvalCase(
            id="no-match-case",
            query="completely unrelated zxyqzxyq",
            expected_files=["nonexistent-memory-zxyqzxyq"],
        ),
    )

    # With memory: recall might find nothing → score=0
    # Without memory: score=0 always
    # delta = 0 - 0 = 0 < 10 → exit 1
    result = runner.invoke(app, ["eval", "compare", "--baseline", "10"])
    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}: {result.output}"


# ---------------------------------------------------------------------------
# CLI: onmc eval create
# ---------------------------------------------------------------------------


def test_cli_eval_create_manual(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """onmc eval create --query creates a case file."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()
    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    result = runner.invoke(
        app,
        ["eval", "create", "--query", "fix cache invalidation bug", "--id", "my-eval-case"],
    )
    assert result.exit_code == 0, result.output
    assert "my-eval-case" in result.output

    case_path = sample_repo / ".onmc" / "evals" / "my-eval-case.json"
    assert case_path.exists()
    loaded = json.loads(case_path.read_text())
    assert loaded["id"] == "my-eval-case"
    assert loaded["query"] == "fix cache invalidation bug"


def test_cli_eval_create_from_memory(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """onmc eval create --from-memory derives a case from a known memory."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()
    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    # Seed a memory first
    repo = init(sample_repo)
    _, _, storage = repo._service._load_context()
    mid = _seed_memory(
        storage,
        kind=MemoryKind.DECISION,
        title="Cache boundary is the central invalidation point",
        summary="All workers route through the shared cache module.",
    )

    result = runner.invoke(app, ["eval", "create", "--from-memory", mid])
    assert result.exit_code == 0, result.output

    # A case file should exist for this memory
    evals_dir = sample_repo / ".onmc" / "evals"
    assert evals_dir.exists()
    case_files = list(evals_dir.glob("*.json"))
    assert len(case_files) == 1


def test_cli_eval_create_from_memory_not_found(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """onmc eval create --from-memory exits non-zero when memory doesn't exist."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()
    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    result = runner.invoke(app, ["eval", "create", "--from-memory", "nonexistent-id-zxq"])
    assert result.exit_code != 0
