"""Tests for the A/B outcome-level eval harness.

All tests run in fixture/offline mode — no LLM calls, no network,
no claude CLI required.  Fixture results from fixtures.py are replayed.

Coverage
--------
- ABTask dataclass construction and field access
- ABTaskResult serialisation round-trip (to_dict / from_dict)
- ABReport aggregate properties (onmc_wins, both_pass, etc.)
- ABReport.to_markdown produces the expected table structure
- ABReport.to_dict produces expected JSON shape
- run_suite(fixture=True) returns an ABReport with correct comparisons
- run_suite(fixture=True, task_filter=...) filters to one task
- run_suite(fixture=True, task_filter='missing') raises ValueError
- fixture loader returns correct pre-recorded results for all built-in tasks
- ABTaskComparison.onmc_wins / both_pass / both_fail / alone_wins logic
- _run_setup correctly plants files in the temp repo
- Gate command accurately detects pass/fail in a real temp repo (no agent needed)
- Built-in BUILTIN_TASKS has at least 3 tasks with non-empty fields
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from oh_no_my_claudecode.evals.ab.fixtures import load_fixture_results
from oh_no_my_claudecode.evals.ab.models import (
    ABReport,
    ABTask,
    ABTaskComparison,
    ABTaskResult,
)
from oh_no_my_claudecode.evals.ab.runner import _run_gate, _run_setup, run_suite
from oh_no_my_claudecode.evals.ab.tasks import (
    BUILTIN_TASKS,
    TASK_ACCUMULATOR_INIT,
    TASK_LIST_SLICE_FIX,
    TASK_WORD_REVERSE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    task_id: str = "t1",
    condition: str = "cc_alone",
    *,
    passed: bool = False,
    tokens: int | None = 100,
    fixture: bool = True,
) -> ABTaskResult:
    return ABTaskResult(
        task_id=task_id,
        condition=condition,  # type: ignore[arg-type]
        passed=passed,
        tokens=tokens,
        duration_s=1.0,
        agent_output="test output",
        fixture=fixture,
    )


def _make_task(task_id: str = "t1") -> ABTask:
    return ABTask(
        id=task_id,
        description="Fix the bug",
        setup_script="import pathlib; pathlib.Path('x.py').write_text('x=1')",
        gate_command="python -c 'import x'",
        onmc_hint="[ONMC] hint",
        note="test task",
    )


# ---------------------------------------------------------------------------
# ABTask construction
# ---------------------------------------------------------------------------


def test_abtask_fields() -> None:
    task = TASK_LIST_SLICE_FIX
    assert task.id == "list_slice_fix"
    assert "top_n" in task.description
    assert "setup_script" in dir(task)
    assert "pytest" in task.gate_command
    assert "ONMC" in task.onmc_hint
    assert task.note


def test_builtin_tasks_count() -> None:
    assert len(BUILTIN_TASKS) >= 3


def test_builtin_tasks_ids_unique() -> None:
    ids = [t.id for t in BUILTIN_TASKS]
    assert len(ids) == len(set(ids)), "Task IDs must be unique"


def test_builtin_tasks_all_fields_non_empty() -> None:
    for task in BUILTIN_TASKS:
        assert task.id, f"Task missing id: {task}"
        assert task.description, f"Task {task.id} missing description"
        assert task.setup_script, f"Task {task.id} missing setup_script"
        assert task.gate_command, f"Task {task.id} missing gate_command"
        assert task.onmc_hint, f"Task {task.id} missing onmc_hint"


# ---------------------------------------------------------------------------
# ABTaskResult serialisation
# ---------------------------------------------------------------------------


def test_abtaskresult_round_trip() -> None:
    result = _make_result("task-1", "cc_onmc", passed=True, tokens=512)
    d = result.to_dict()
    loaded = ABTaskResult.from_dict(d)
    assert loaded.task_id == "task-1"
    assert loaded.condition == "cc_onmc"
    assert loaded.passed is True
    assert loaded.tokens == 512
    assert loaded.fixture is True


def test_abtaskresult_round_trip_none_tokens() -> None:
    result = _make_result("task-2", "cc_alone", passed=False, tokens=None)
    d = result.to_dict()
    loaded = ABTaskResult.from_dict(d)
    assert loaded.tokens is None
    assert loaded.passed is False


def test_abtaskresult_to_dict_shape() -> None:
    result = _make_result()
    d = result.to_dict()
    for key in ("task_id", "condition", "passed", "tokens", "duration_s", "agent_output", "fixture"):
        assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# ABTaskComparison logic
# ---------------------------------------------------------------------------


def test_comparison_onmc_wins() -> None:
    task = _make_task()
    alone = _make_result(passed=False)
    onmc = _make_result(condition="cc_onmc", passed=True)
    cmp = ABTaskComparison(task=task, alone=alone, onmc=onmc)
    assert cmp.onmc_wins is True
    assert cmp.both_pass is False
    assert cmp.both_fail is False
    assert cmp.alone_wins is False


def test_comparison_both_pass() -> None:
    task = _make_task()
    alone = _make_result(passed=True)
    onmc = _make_result(condition="cc_onmc", passed=True)
    cmp = ABTaskComparison(task=task, alone=alone, onmc=onmc)
    assert cmp.both_pass is True
    assert cmp.onmc_wins is False


def test_comparison_both_fail() -> None:
    task = _make_task()
    alone = _make_result(passed=False)
    onmc = _make_result(condition="cc_onmc", passed=False)
    cmp = ABTaskComparison(task=task, alone=alone, onmc=onmc)
    assert cmp.both_fail is True
    assert cmp.onmc_wins is False


def test_comparison_alone_wins_regression() -> None:
    task = _make_task()
    alone = _make_result(passed=True)
    onmc = _make_result(condition="cc_onmc", passed=False)
    cmp = ABTaskComparison(task=task, alone=alone, onmc=onmc)
    assert cmp.alone_wins is True
    assert cmp.onmc_wins is False


def test_comparison_token_delta() -> None:
    task = _make_task()
    alone = _make_result(tokens=400)
    onmc = _make_result(condition="cc_onmc", tokens=500)
    cmp = ABTaskComparison(task=task, alone=alone, onmc=onmc)
    assert cmp.token_delta == 100  # onmc - alone


def test_comparison_token_delta_none() -> None:
    task = _make_task()
    alone = _make_result(tokens=None)
    onmc = _make_result(condition="cc_onmc", tokens=None)
    cmp = ABTaskComparison(task=task, alone=alone, onmc=onmc)
    assert cmp.token_delta is None


# ---------------------------------------------------------------------------
# ABReport aggregate properties
# ---------------------------------------------------------------------------


def _make_report(outcomes: list[tuple[bool, bool]]) -> ABReport:
    """Build a report from (alone_passed, onmc_passed) tuples."""
    comparisons = []
    for i, (alone_passed, onmc_passed) in enumerate(outcomes):
        task = _make_task(f"task-{i}")
        alone = _make_result(f"task-{i}", "cc_alone", passed=alone_passed)
        onmc = _make_result(f"task-{i}", "cc_onmc", passed=onmc_passed)
        comparisons.append(ABTaskComparison(task=task, alone=alone, onmc=onmc))
    return ABReport(comparisons=comparisons, fixture=True)


def test_report_onmc_wins_count() -> None:
    # 2 tasks: ONMC wins, 1 task: both pass
    report = _make_report([(False, True), (False, True), (True, True)])
    assert report.onmc_wins == 2
    assert report.both_pass == 1
    assert report.total_tasks == 3


def test_report_alone_wins_count() -> None:
    report = _make_report([(True, False)])
    assert report.alone_wins == 1
    assert report.onmc_wins == 0


def test_report_pass_rates() -> None:
    # 3 tasks: onmc passes 2/3, alone passes 1/3
    report = _make_report([(False, True), (False, True), (True, False)])
    assert report.onmc_pass_rate == pytest.approx(2 / 3)
    assert report.alone_pass_rate == pytest.approx(1 / 3)


def test_report_empty() -> None:
    report = ABReport(comparisons=[], fixture=True)
    assert report.total_tasks == 0
    assert report.onmc_wins == 0
    assert report.onmc_pass_rate == 0.0


# ---------------------------------------------------------------------------
# ABReport rendering
# ---------------------------------------------------------------------------


def test_report_to_markdown_contains_expected() -> None:
    report = _make_report([(False, True)])
    md = report.to_markdown()
    assert "A/B Eval Report" in md
    assert "FIXTURE" in md
    assert "cc_alone" in md
    assert "cc_onmc" in md
    assert "ONMC wins" in md
    assert "Honesty note" in md


def test_report_to_markdown_both_pass() -> None:
    report = _make_report([(True, True)])
    md = report.to_markdown()
    assert "tie-pass" in md


def test_report_to_dict_shape() -> None:
    report = _make_report([(False, True), (True, True)])
    d = report.to_dict()
    assert d["total_tasks"] == 2
    assert d["onmc_wins"] == 1
    assert d["both_pass"] == 1
    assert "comparisons" in d
    assert len(d["comparisons"]) == 2  # type: ignore[arg-type]
    assert "task_id" in d["comparisons"][0]
    assert "alone" in d["comparisons"][0]
    assert "onmc" in d["comparisons"][0]


def test_report_to_dict_json_serialisable() -> None:
    report = _make_report([(False, True)])
    d = report.to_dict()
    # Must be JSON-serialisable (no non-primitive types)
    json_str = json.dumps(d)
    loaded = json.loads(json_str)
    assert loaded["total_tasks"] == 1


# ---------------------------------------------------------------------------
# Fixture loader
# ---------------------------------------------------------------------------


def test_fixture_loader_has_all_builtin_tasks() -> None:
    fixtures = load_fixture_results()
    for task in BUILTIN_TASKS:
        assert (task.id, "cc_alone") in fixtures, (
            f"Missing fixture for ({task.id}, cc_alone)"
        )
        assert (task.id, "cc_onmc") in fixtures, (
            f"Missing fixture for ({task.id}, cc_onmc)"
        )


def test_fixture_loader_results_are_abtaskresult() -> None:
    fixtures = load_fixture_results()
    for result in fixtures.values():
        assert isinstance(result, ABTaskResult)
        assert result.fixture is True


def test_fixture_list_slice_shows_onmc_win() -> None:
    fixtures = load_fixture_results()
    alone = fixtures[("list_slice_fix", "cc_alone")]
    onmc = fixtures[("list_slice_fix", "cc_onmc")]
    assert alone.passed is False, "Fixture: cc_alone should fail on list_slice_fix"
    assert onmc.passed is True, "Fixture: cc_onmc should pass on list_slice_fix"


def test_fixture_accumulator_shows_both_pass() -> None:
    fixtures = load_fixture_results()
    alone = fixtures[("accumulator_init", "cc_alone")]
    onmc = fixtures[("accumulator_init", "cc_onmc")]
    # This task is easy — both pass
    assert alone.passed is True
    assert onmc.passed is True


def test_fixture_word_reverse_shows_onmc_win() -> None:
    fixtures = load_fixture_results()
    alone = fixtures[("word_reverse", "cc_alone")]
    onmc = fixtures[("word_reverse", "cc_onmc")]
    assert alone.passed is False
    assert onmc.passed is True


# ---------------------------------------------------------------------------
# run_suite fixture mode
# ---------------------------------------------------------------------------


def test_run_suite_fixture_returns_report() -> None:
    report = run_suite(BUILTIN_TASKS, fixture=True)
    assert isinstance(report, ABReport)
    assert report.fixture is True
    assert report.total_tasks == len(BUILTIN_TASKS)


def test_run_suite_fixture_comparisons_match_tasks() -> None:
    report = run_suite(BUILTIN_TASKS, fixture=True)
    task_ids = {c.task.id for c in report.comparisons}
    expected_ids = {t.id for t in BUILTIN_TASKS}
    assert task_ids == expected_ids


def test_run_suite_fixture_onmc_wins_at_least_one() -> None:
    report = run_suite(BUILTIN_TASKS, fixture=True)
    # Based on our fixture data: list_slice_fix and word_reverse should be ONMC wins
    assert report.onmc_wins >= 1, (
        f"Expected at least 1 ONMC win in fixture mode but got {report.onmc_wins}. "
        f"Comparisons: {[(c.task.id, c.alone.passed, c.onmc.passed) for c in report.comparisons]}"
    )


def test_run_suite_fixture_task_filter() -> None:
    report = run_suite(BUILTIN_TASKS, fixture=True, task_filter="list_slice_fix")
    assert report.total_tasks == 1
    assert report.comparisons[0].task.id == "list_slice_fix"


def test_run_suite_fixture_task_filter_missing_raises() -> None:
    with pytest.raises(ValueError, match="No task with id"):
        run_suite(BUILTIN_TASKS, fixture=True, task_filter="does_not_exist")


def test_run_suite_single_task_fixture() -> None:
    report = run_suite([TASK_ACCUMULATOR_INIT], fixture=True)
    assert report.total_tasks == 1
    assert report.both_pass == 1  # accumulator_init: both pass


# ---------------------------------------------------------------------------
# Setup script and gate (no agent needed — tests infra, not LLM)
# ---------------------------------------------------------------------------


def test_run_setup_plants_files(tmp_path: Path) -> None:
    """_run_setup correctly creates files in the temp dir."""
    _run_setup(TASK_LIST_SLICE_FIX, tmp_path)
    assert (tmp_path / "utils.py").exists()
    assert (tmp_path / "test_utils.py").exists()
    content = (tmp_path / "utils.py").read_text()
    assert "top_n" in content
    assert "n + 1" in content  # bug is present


def test_run_setup_accumulator(tmp_path: Path) -> None:
    _run_setup(TASK_ACCUMULATOR_INIT, tmp_path)
    assert (tmp_path / "stats.py").exists()
    content = (tmp_path / "stats.py").read_text()
    assert "total = 1" in content  # bug present


def test_run_setup_word_reverse(tmp_path: Path) -> None:
    _run_setup(TASK_WORD_REVERSE, tmp_path)
    assert (tmp_path / "text_utils.py").exists()
    content = (tmp_path / "text_utils.py").read_text()
    assert "[::-1][1:]" in content  # bug present


def test_gate_fails_on_buggy_code(tmp_path: Path) -> None:
    """Gate command fails when the bug is present (pre-fix state)."""
    _run_setup(TASK_LIST_SLICE_FIX, tmp_path)
    passed, output = _run_gate(TASK_LIST_SLICE_FIX, tmp_path)
    assert passed is False, (
        f"Gate should FAIL on buggy code but passed. Output:\n{output}"
    )


def test_gate_passes_after_manual_fix(tmp_path: Path) -> None:
    """Gate command passes after the bug is manually corrected."""
    _run_setup(TASK_LIST_SLICE_FIX, tmp_path)

    # Apply the correct fix: change n+1 to n
    utils_path = tmp_path / "utils.py"
    fixed = utils_path.read_text().replace("[:n + 1]", "[:n]")
    utils_path.write_text(fixed)

    passed, output = _run_gate(TASK_LIST_SLICE_FIX, tmp_path)
    assert passed is True, (
        f"Gate should PASS after correct fix but failed. Output:\n{output}"
    )


def test_gate_fails_with_wrong_fix(tmp_path: Path) -> None:
    """The dead-end fix (n-1) still fails the gate."""
    _run_setup(TASK_LIST_SLICE_FIX, tmp_path)

    utils_path = tmp_path / "utils.py"
    wrong = utils_path.read_text().replace("[:n + 1]", "[:n - 1]")
    utils_path.write_text(wrong)

    passed, output = _run_gate(TASK_LIST_SLICE_FIX, tmp_path)
    assert passed is False, (
        f"Gate should FAIL with wrong fix (n-1) but passed. Output:\n{output}"
    )


def test_gate_accumulator_fails_buggy(tmp_path: Path) -> None:
    _run_setup(TASK_ACCUMULATOR_INIT, tmp_path)
    passed, _ = _run_gate(TASK_ACCUMULATOR_INIT, tmp_path)
    assert passed is False


def test_gate_accumulator_passes_after_fix(tmp_path: Path) -> None:
    _run_setup(TASK_ACCUMULATOR_INIT, tmp_path)
    stats_path = tmp_path / "stats.py"
    fixed = stats_path.read_text().replace("total = 1", "total = 0")
    stats_path.write_text(fixed)
    passed, output = _run_gate(TASK_ACCUMULATOR_INIT, tmp_path)
    assert passed is True, f"Gate failed after fix. Output:\n{output}"


def test_gate_word_reverse_fails_buggy(tmp_path: Path) -> None:
    _run_setup(TASK_WORD_REVERSE, tmp_path)
    passed, _ = _run_gate(TASK_WORD_REVERSE, tmp_path)
    assert passed is False


def test_gate_word_reverse_passes_after_fix(tmp_path: Path) -> None:
    _run_setup(TASK_WORD_REVERSE, tmp_path)
    tu_path = tmp_path / "text_utils.py"
    fixed = tu_path.read_text().replace("[::-1][1:]", "[::-1]")
    tu_path.write_text(fixed)
    passed, output = _run_gate(TASK_WORD_REVERSE, tmp_path)
    assert passed is True, f"Gate failed after fix. Output:\n{output}"


# ---------------------------------------------------------------------------
# Honesty: confirm the baseline is not auto-fail
# ---------------------------------------------------------------------------


def test_fixture_has_at_least_one_non_auto_fail_baseline() -> None:
    """At least one cc_alone result passes — baseline is not universally rigged."""
    fixtures = load_fixture_results()
    alone_passes = [r for (_, cond), r in fixtures.items() if cond == "cc_alone" and r.passed]
    assert alone_passes, (
        "All cc_alone fixture results fail — this would be an auto-fail rigged baseline. "
        "At least one task should have cc_alone=pass to prove the baseline is real."
    )
