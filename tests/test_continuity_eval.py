"""Tests for the autonomous-continuity eval SIM.

All tests are DETERMINISTIC and OFFLINE — no LLM calls, no subprocess,
no network required.  This is a policy simulation: outcomes are pre-assigned
and both orchestrator policies are applied deterministically.

Coverage
--------
Core model assertions
  - ContinuityTask dataclass fields round-trip correctly
  - TaskRun fields are populated as expected

Naive policy assertions
  - clean tasks before broken: correctly completed
  - false_green before broken: false_completion=True (naive accepts ghost)
  - scope_violation before broken: false_completion=True (naive accepts violation)
  - broken task: fails gate, poisons tree
  - clean tasks AFTER broken: cascade_failure=True (poisoning confirmed)
  - transient_env in healthy tree: fails, NOT a cascade failure
  - transient_env AFTER broken: fails, NOT counted as cascade (would fail anyway)
  - interventions_needed = 1 (poisoned tree) + false_completions count
  - correctly_completed counts only clean non-cascade completions

ONMC policy assertions
  - clean tasks: all completed
  - false_green: rejected (gate_passed=False, completed=False)
  - broken: fails but cascade_failures=0 (isolation)
  - scope_violation: rejected
  - transient_env: skipped, cascade_failures=0
  - false_completions = 0 always
  - cascade_failures = 0 always
  - interventions_needed = 0 always

Comparison assertions
  - correctly_completed_delta: ONMC > naive (ONMC does more real work)
  - false_completions_delta: negative (ONMC has fewer false accepts)
  - cascade_failures_delta: negative (ONMC prevents cascades)
  - interventions_delta: negative (ONMC leaves fewer messes)

Full BUILTIN_TASKS suite
  - naive: correctly_completed=3, false_completions=2, cascade_failures=3
  - naive: interventions_needed=3
  - onmc: correctly_completed=6, false_completions=0, cascade_failures=0
  - onmc: interventions_needed=0
  - to_markdown contains expected sections and values
  - to_dict is JSON-serialisable and has expected shape
  - CLI command 'onmc eval continuity' exits 0 and prints markdown

BUILTIN_TASKS structure
  - has 10 tasks
  - includes exactly 1 broken task
  - broken task is at position 5 (0-indexed, mid-sequence)
  - has exactly 1 false_green, 1 scope_violation, 1 transient_env
  - has 6 clean tasks
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.evals.continuity.harness import run_continuity
from oh_no_my_claudecode.evals.continuity.models import (
    ContinuityComparison,
    ContinuityTask,
    OrchestratorReport,
    TaskRun,
)
from oh_no_my_claudecode.evals.continuity.orchestrators import run_naive, run_onmc
from oh_no_my_claudecode.evals.continuity.suite import (
    BUILTIN_TASKS,
    TASK_BROKEN_DB_REFACTOR,
    TASK_FALSE_GREEN_TYPE_HINTS,
    TASK_SCOPE_VIOLATION_CONFIG,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task(
    task_id: str,
    outcome: str,
    owned_paths: list[str] | None = None,
    protected_paths: list[str] | None = None,
) -> ContinuityTask:
    return ContinuityTask(
        id=task_id,
        outcome=outcome,  # type: ignore[arg-type]
        owned_paths=owned_paths or ["src.py"],
        protected_paths=protected_paths or ["config.py"],
        note=f"test task {task_id}",
    )


def _clean(task_id: str = "clean_1") -> ContinuityTask:
    return _task(task_id, "clean")


def _false_green(task_id: str = "fg_1") -> ContinuityTask:
    return _task(task_id, "false_green")


def _broken(task_id: str = "broken_1") -> ContinuityTask:
    return _task(task_id, "broken")


def _scope_viol(task_id: str = "scope_1") -> ContinuityTask:
    return _task(task_id, "scope_violation")


def _transient(task_id: str = "trans_1") -> ContinuityTask:
    return _task(task_id, "transient_env")


# ---------------------------------------------------------------------------
# ContinuityTask model
# ---------------------------------------------------------------------------


def test_continuity_task_fields() -> None:
    task = _clean("my_task")
    assert task.id == "my_task"
    assert task.outcome == "clean"
    assert isinstance(task.owned_paths, list)
    assert isinstance(task.protected_paths, list)
    assert isinstance(task.note, str)


def test_builtin_tasks_count() -> None:
    assert len(BUILTIN_TASKS) == 10


def test_builtin_tasks_ids_unique() -> None:
    ids = [t.id for t in BUILTIN_TASKS]
    assert len(ids) == len(set(ids)), "Task IDs must be unique"


def test_builtin_tasks_outcome_composition() -> None:
    outcomes = [t.outcome for t in BUILTIN_TASKS]
    assert outcomes.count("clean") == 6
    assert outcomes.count("false_green") == 1
    assert outcomes.count("broken") == 1
    assert outcomes.count("scope_violation") == 1
    assert outcomes.count("transient_env") == 1


def test_broken_task_is_mid_sequence() -> None:
    """broken task at index 5 exposes cascade for tasks 6-8 (3 clean tasks after)."""
    broken_indices = [i for i, t in enumerate(BUILTIN_TASKS) if t.outcome == "broken"]
    assert len(broken_indices) == 1
    broken_idx = broken_indices[0]
    # Must have at least one clean task before AND after the broken task
    before = [t for t in BUILTIN_TASKS[:broken_idx] if t.outcome == "clean"]
    after = [t for t in BUILTIN_TASKS[broken_idx + 1 :] if t.outcome == "clean"]
    assert len(before) >= 1, "Need clean tasks before broken to show naive accepts them"
    assert len(after) >= 1, "Need clean tasks after broken to show cascade"


def test_false_green_and_scope_before_broken() -> None:
    """false_green and scope_violation must appear before broken to expose naive's false-acceptance."""
    broken_idx = next(i for i, t in enumerate(BUILTIN_TASKS) if t.outcome == "broken")
    fg_idx = next(i for i, t in enumerate(BUILTIN_TASKS) if t.outcome == "false_green")
    sv_idx = next(i for i, t in enumerate(BUILTIN_TASKS) if t.outcome == "scope_violation")
    assert fg_idx < broken_idx, "false_green must come before broken"
    assert sv_idx < broken_idx, "scope_violation must come before broken"


# ---------------------------------------------------------------------------
# Naive policy: clean tasks before broken
# ---------------------------------------------------------------------------


def test_naive_clean_before_broken_completes() -> None:
    tasks = [_clean("c1"), _broken()]
    report = run_naive(tasks)
    c1_run = next(r for r in report.runs if r.task_id == "c1")
    assert c1_run.completed is True
    assert c1_run.false_completion is False
    assert c1_run.cascade_failure is False
    assert c1_run.gate_passed is True


def test_naive_correctly_completed_counts_clean_before_broken() -> None:
    tasks = [_clean("c1"), _clean("c2"), _broken(), _clean("c3")]
    report = run_naive(tasks)
    assert report.correctly_completed == 2  # c1, c2 complete; c3 cascades


# ---------------------------------------------------------------------------
# Naive policy: false_green — accepted (false completion)
# ---------------------------------------------------------------------------


def test_naive_false_green_before_broken_is_false_completion() -> None:
    tasks = [_false_green(), _broken()]
    report = run_naive(tasks)
    fg_run = next(r for r in report.runs if r.outcome == "false_green")
    assert fg_run.completed is True, "naive accepts false_green (tests pass)"
    assert fg_run.false_completion is True, "but it is a false completion"
    assert fg_run.cascade_failure is False


def test_naive_false_completions_counted() -> None:
    tasks = [_false_green("fg1"), _false_green("fg2"), _clean()]
    report = run_naive(tasks)
    assert report.false_completions == 2


# ---------------------------------------------------------------------------
# Naive policy: scope_violation — accepted (false completion)
# ---------------------------------------------------------------------------


def test_naive_scope_violation_is_false_completion() -> None:
    tasks = [_scope_viol(), _broken()]
    report = run_naive(tasks)
    sv_run = next(r for r in report.runs if r.outcome == "scope_violation")
    assert sv_run.completed is True, "naive accepts scope_violation (tests pass)"
    assert sv_run.false_completion is True
    assert sv_run.cascade_failure is False


# ---------------------------------------------------------------------------
# Naive policy: broken task — fails gate, poisons tree
# ---------------------------------------------------------------------------


def test_naive_broken_fails_gate() -> None:
    tasks = [_broken()]
    report = run_naive(tasks)
    br = report.runs[0]
    assert br.gate_passed is False
    assert br.completed is False
    assert br.false_completion is False
    assert br.cascade_failure is False


def test_naive_broken_poisons_subsequent_clean() -> None:
    tasks = [_broken(), _clean("c_after")]
    report = run_naive(tasks)
    c_after = next(r for r in report.runs if r.task_id == "c_after")
    assert c_after.cascade_failure is True
    assert c_after.completed is False
    assert c_after.gate_passed is False


def test_naive_broken_poisons_all_subsequent_tasks() -> None:
    tasks = [_clean("c1"), _broken(), _clean("c2"), _clean("c3"), _false_green("fg")]
    report = run_naive(tasks)
    c1 = next(r for r in report.runs if r.task_id == "c1")
    c2 = next(r for r in report.runs if r.task_id == "c2")
    c3 = next(r for r in report.runs if r.task_id == "c3")
    fg = next(r for r in report.runs if r.task_id == "fg")
    assert c1.cascade_failure is False, "c1 is before broken, should not cascade"
    assert c2.cascade_failure is True
    assert c3.cascade_failure is True
    assert fg.cascade_failure is True, "false_green after broken also cascades"


def test_naive_cascade_failures_counted() -> None:
    tasks = [_broken(), _clean("c1"), _clean("c2"), _clean("c3")]
    report = run_naive(tasks)
    assert report.cascade_failures == 3


# ---------------------------------------------------------------------------
# Naive policy: transient_env — fails but NOT cascade victim
# ---------------------------------------------------------------------------


def test_naive_transient_env_healthy_tree_fails() -> None:
    tasks = [_transient()]
    report = run_naive(tasks)
    tr = report.runs[0]
    assert tr.completed is False
    assert tr.cascade_failure is False, "transient_env fails on its own, not from cascade"
    assert tr.gate_passed is False


def test_naive_transient_env_after_broken_not_cascade() -> None:
    """transient_env after broken is NOT a cascade failure (it would fail anyway)."""
    tasks = [_broken(), _transient()]
    report = run_naive(tasks)
    tr = next(r for r in report.runs if r.outcome == "transient_env")
    assert tr.cascade_failure is False, (
        "transient_env would fail even in healthy tree — not a cascade victim"
    )


# ---------------------------------------------------------------------------
# Naive policy: interventions_needed
# ---------------------------------------------------------------------------


def test_naive_interventions_no_poison_no_false() -> None:
    tasks = [_clean("c1")]
    report = run_naive(tasks)
    assert report.interventions_needed == 0


def test_naive_interventions_poisoned_tree() -> None:
    tasks = [_broken()]
    report = run_naive(tasks)
    assert report.interventions_needed == 1  # 1 for poisoned tree


def test_naive_interventions_false_completions() -> None:
    tasks = [_false_green("fg1"), _scope_viol("sv1")]
    report = run_naive(tasks)
    assert report.false_completions == 2
    assert report.interventions_needed == 2  # 2 ghost completions, no poisoned tree


def test_naive_interventions_combined() -> None:
    """Poisoned tree + 2 false completions = 3 interventions."""
    tasks = [_false_green(), _scope_viol(), _broken(), _clean("c_after")]
    report = run_naive(tasks)
    assert report.false_completions == 2
    assert report.cascade_failures == 1
    assert report.interventions_needed == 3  # 1 poisoned tree + 2 false completions


# ---------------------------------------------------------------------------
# ONMC policy: clean tasks always complete
# ---------------------------------------------------------------------------


def test_onmc_clean_always_completes() -> None:
    tasks = [_clean("c1"), _clean("c2"), _clean("c3")]
    report = run_onmc(tasks)
    for r in report.runs:
        assert r.completed is True
        assert r.false_completion is False
        assert r.cascade_failure is False
        assert r.gate_passed is True
    assert report.correctly_completed == 3


# ---------------------------------------------------------------------------
# ONMC policy: false_green rejected
# ---------------------------------------------------------------------------


def test_onmc_false_green_rejected() -> None:
    tasks = [_false_green()]
    report = run_onmc(tasks)
    fg = report.runs[0]
    assert fg.completed is False
    assert fg.false_completion is False, "ONMC never registers false completions"
    assert fg.gate_passed is False
    assert report.false_completions == 0


# ---------------------------------------------------------------------------
# ONMC policy: broken is isolated, no cascade
# ---------------------------------------------------------------------------


def test_onmc_broken_does_not_cascade() -> None:
    tasks = [_broken(), _clean("c_after")]
    report = run_onmc(tasks)
    c_after = next(r for r in report.runs if r.task_id == "c_after")
    assert c_after.completed is True, "clean task after broken still completes under ONMC"
    assert c_after.cascade_failure is False
    assert report.cascade_failures == 0


def test_onmc_broken_clean_sandwich() -> None:
    tasks = [_clean("c1"), _broken(), _clean("c2"), _clean("c3")]
    report = run_onmc(tasks)
    assert report.correctly_completed == 3  # c1, c2, c3
    assert report.cascade_failures == 0


# ---------------------------------------------------------------------------
# ONMC policy: scope_violation rejected
# ---------------------------------------------------------------------------


def test_onmc_scope_violation_rejected() -> None:
    tasks = [_scope_viol()]
    report = run_onmc(tasks)
    sv = report.runs[0]
    assert sv.completed is False
    assert sv.false_completion is False
    assert sv.gate_passed is False
    assert report.false_completions == 0


# ---------------------------------------------------------------------------
# ONMC policy: transient_env skipped safely
# ---------------------------------------------------------------------------


def test_onmc_transient_env_skipped_safely() -> None:
    tasks = [_transient(), _clean("c_after")]
    report = run_onmc(tasks)
    tr = report.runs[0]
    c_after = next(r for r in report.runs if r.task_id == "c_after")
    assert tr.completed is False
    assert tr.cascade_failure is False
    assert c_after.completed is True, "transient does not poison subsequent tasks"
    assert report.cascade_failures == 0


# ---------------------------------------------------------------------------
# ONMC design guarantees (invariants)
# ---------------------------------------------------------------------------


def test_onmc_false_completions_always_zero() -> None:
    """ONMC rich gate guarantees zero false completions across any task mix."""
    tasks = [_false_green(), _scope_viol(), _clean(), _broken(), _transient()]
    report = run_onmc(tasks)
    assert report.false_completions == 0


def test_onmc_cascade_failures_always_zero() -> None:
    """ONMC isolation guarantees zero cascade failures."""
    tasks = [_broken(), _broken("broken_2"), _clean("c1"), _clean("c2")]
    report = run_onmc(tasks)
    assert report.cascade_failures == 0


def test_onmc_interventions_always_zero() -> None:
    """ONMC guarantees zero interventions needed at session end."""
    tasks = [
        _false_green(), _scope_viol(), _broken(), _clean(), _transient()
    ]
    report = run_onmc(tasks)
    assert report.interventions_needed == 0


# ---------------------------------------------------------------------------
# Comparison: ONMC must outperform naive on every safety metric
# ---------------------------------------------------------------------------


def test_comparison_onmc_correctly_completed_beats_naive() -> None:
    """ONMC completes more clean tasks because it prevents cascade."""
    tasks = [_clean("c1"), _broken(), _clean("c2"), _clean("c3")]
    cmp = run_continuity(tasks)
    assert cmp.onmc.correctly_completed > cmp.naive.correctly_completed
    assert cmp.correctly_completed_delta > 0


def test_comparison_onmc_zero_false_completions() -> None:
    tasks = [_false_green(), _scope_viol(), _clean()]
    cmp = run_continuity(tasks)
    assert cmp.onmc.false_completions == 0
    assert cmp.naive.false_completions == 2
    assert cmp.false_completions_delta < 0


def test_comparison_onmc_zero_cascades() -> None:
    tasks = [_broken(), _clean("c1"), _clean("c2")]
    cmp = run_continuity(tasks)
    assert cmp.onmc.cascade_failures == 0
    assert cmp.naive.cascade_failures == 2
    assert cmp.cascade_failures_delta < 0


def test_comparison_onmc_zero_interventions() -> None:
    tasks = [_false_green(), _broken(), _clean("c_after")]
    cmp = run_continuity(tasks)
    assert cmp.onmc.interventions_needed == 0
    assert cmp.naive.interventions_needed >= 1
    assert cmp.interventions_delta < 0


# ---------------------------------------------------------------------------
# Full BUILTIN_TASKS suite — known expected values
# ---------------------------------------------------------------------------


def test_builtin_naive_correctly_completed() -> None:
    """3 clean tasks before the broken task are correctly completed under naive."""
    report = run_naive(BUILTIN_TASKS)
    assert report.correctly_completed == 3


def test_builtin_naive_false_completions() -> None:
    """false_green + scope_violation before broken = 2 false completions under naive."""
    report = run_naive(BUILTIN_TASKS)
    assert report.false_completions == 2


def test_builtin_naive_cascade_failures() -> None:
    """3 clean tasks after broken cascade-fail under naive; transient_env does not."""
    report = run_naive(BUILTIN_TASKS)
    assert report.cascade_failures == 3


def test_builtin_naive_interventions_needed() -> None:
    """1 (poisoned tree) + 2 (false completions) = 3 interventions under naive."""
    report = run_naive(BUILTIN_TASKS)
    assert report.interventions_needed == 3


def test_builtin_onmc_correctly_completed() -> None:
    """All 6 clean tasks complete under ONMC (no cascade)."""
    report = run_onmc(BUILTIN_TASKS)
    assert report.correctly_completed == 6


def test_builtin_onmc_false_completions_zero() -> None:
    report = run_onmc(BUILTIN_TASKS)
    assert report.false_completions == 0


def test_builtin_onmc_cascade_failures_zero() -> None:
    report = run_onmc(BUILTIN_TASKS)
    assert report.cascade_failures == 0


def test_builtin_onmc_interventions_zero() -> None:
    report = run_onmc(BUILTIN_TASKS)
    assert report.interventions_needed == 0


def test_builtin_comparison_all_deltas_favor_onmc() -> None:
    cmp = run_continuity(BUILTIN_TASKS)
    assert cmp.correctly_completed_delta > 0, "ONMC completes more"
    assert cmp.false_completions_delta < 0, "ONMC accepts fewer ghosts"
    assert cmp.cascade_failures_delta < 0, "ONMC prevents cascade"
    assert cmp.interventions_delta < 0, "ONMC needs fewer human fixes"


# ---------------------------------------------------------------------------
# OrchestratorReport helpers
# ---------------------------------------------------------------------------


def test_orchestrator_report_total_tasks() -> None:
    report = run_naive([_clean("c1"), _clean("c2")])
    assert report.total_tasks == 2


def test_orchestrator_report_total_completed() -> None:
    report = run_naive([_clean("c1"), _false_green("fg")])
    assert report.total_completed == 2  # both "complete" under naive (fg is false)


# ---------------------------------------------------------------------------
# to_dict serialisability
# ---------------------------------------------------------------------------


def test_comparison_to_dict_json_serialisable() -> None:
    cmp = run_continuity(BUILTIN_TASKS)
    d = cmp.to_dict()
    json_str = json.dumps(d)
    loaded = json.loads(json_str)
    assert loaded["naive"]["orchestrator"] == "naive"
    assert loaded["onmc"]["orchestrator"] == "onmc"
    assert "deltas" in loaded


def test_comparison_to_dict_shape() -> None:
    cmp = run_continuity(BUILTIN_TASKS)
    d = cmp.to_dict()
    for key in ("naive", "onmc", "deltas"):
        assert key in d
    naive_d = d["naive"]
    assert isinstance(naive_d, dict)
    for metric in ("correctly_completed", "false_completions", "cascade_failures", "interventions_needed"):
        assert metric in naive_d
    assert "runs" in naive_d
    assert len(naive_d["runs"]) == len(BUILTIN_TASKS)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# to_markdown rendering
# ---------------------------------------------------------------------------


def test_comparison_to_markdown_contains_expected_sections() -> None:
    cmp = run_continuity(BUILTIN_TASKS)
    md = cmp.to_markdown()
    assert "Continuity Eval" in md
    assert "SIM" in md, "Must label as SIM (deterministic, no LLM)"
    assert "Naive" in md or "naive" in md
    assert "ONMC" in md or "onmc" in md
    assert "Correctly completed" in md or "correctly completed" in md
    assert "False completions" in md or "false completions" in md
    assert "Cascade failures" in md or "cascade" in md
    assert "interventions" in md.lower()
    assert "Per-task breakdown" in md
    assert "Glossary" in md


def test_comparison_to_markdown_shows_cascade_fail() -> None:
    cmp = run_continuity(BUILTIN_TASKS)
    md = cmp.to_markdown()
    assert "cascade-fail" in md, "cascade-fail label must appear for naive cascade victims"


def test_comparison_to_markdown_shows_false_complete() -> None:
    cmp = run_continuity(BUILTIN_TASKS)
    md = cmp.to_markdown()
    assert "false-complete" in md, "false-complete label must appear for naive false acceptances"


# ---------------------------------------------------------------------------
# CLI: onmc eval continuity
# ---------------------------------------------------------------------------


def test_cli_eval_continuity_exits_zero() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "continuity"])
    assert result.exit_code == 0, f"CLI exited non-zero:\n{result.output}"


def test_cli_eval_continuity_prints_table() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "continuity"])
    assert "Continuity Eval" in result.output or "continuity" in result.output.lower()
    assert result.exit_code == 0


def test_cli_eval_continuity_json_is_valid() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "continuity", "--json"])
    assert result.exit_code == 0, f"CLI exited non-zero:\n{result.output}"
    # Extract JSON from output (may have rich markup stripped by CliRunner)
    data = json.loads(result.output)
    assert "naive" in data
    assert "onmc" in data
    assert "deltas" in data
