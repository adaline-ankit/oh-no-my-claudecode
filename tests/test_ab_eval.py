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
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.evals.ab.fixtures import load_fixture_results
from oh_no_my_claudecode.evals.ab.models import (
    ABReport,
    ABTask,
    ABTaskComparison,
    ABTaskResult,
)
from oh_no_my_claudecode.evals.ab.runner import (
    _AgentOutcome,
    _build_prompt,
    _run_claude_agent,
    _run_command,
    _run_gate,
    _run_setup,
    run_ab,
    run_suite,
)
from oh_no_my_claudecode.evals.ab.tasks import (
    BUILTIN_TASKS,
    PUBLIC_REPO_TASKS,
    TASK_ACCUMULATOR_INIT,
    TASK_HTTPX_DIRECT_REQUEST_TIMEOUT,
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


def test_public_repo_task_is_pinned_and_not_a_fixture() -> None:
    task = TASK_HTTPX_DIRECT_REQUEST_TIMEOUT
    assert task in PUBLIC_REPO_TASKS
    assert task.repo_url == "https://github.com/encode/httpx.git"
    assert task.repo_commit == "df5345140e09ac6c2de0d9589bcd6f3e31c6aa3f"
    assert "test_async_client_new_request_send_timeout" in task.setup_patch
    preservation_gate = " ".join(task.pass_to_pass_commands[0])
    assert "test_read_timeout" in preservation_gate
    assert "test_connect_timeout" in preservation_gate
    assert "test_pool_timeout" in preservation_gate
    assert "test_write_timeout" not in preservation_gate
    assert task.protected_paths == ("tests/test_timeouts.py",)
    assert task not in BUILTIN_TASKS


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
    result.changed_files = ["httpx/_client.py"]
    result.additions = 11
    result.turns = 4
    result.prompt_sha256 = "a" * 64
    d = result.to_dict()
    loaded = ABTaskResult.from_dict(d)
    assert loaded.task_id == "task-1"
    assert loaded.condition == "cc_onmc"
    assert loaded.passed is True
    assert loaded.tokens == 512
    assert loaded.fixture is True
    assert loaded.changed_files == ["httpx/_client.py"]
    assert loaded.additions == 11
    assert loaded.turns == 4
    assert loaded.prompt_sha256 == "a" * 64


def test_abtaskresult_round_trip_none_tokens() -> None:
    result = _make_result("task-2", "cc_alone", passed=False, tokens=None)
    d = result.to_dict()
    loaded = ABTaskResult.from_dict(d)
    assert loaded.tokens is None
    assert loaded.passed is False


def test_abtaskresult_to_dict_shape() -> None:
    result = _make_result()
    d = result.to_dict()
    required = (
        "task_id",
        "condition",
        "passed",
        "tokens",
        "duration_s",
        "agent_output",
        "fixture",
    )
    for key in required:
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


def test_comparison_efficiency_reductions() -> None:
    task = _make_task()
    alone = _make_result(passed=True, tokens=1000)
    alone.turns = 20
    alone.cost_usd = 0.50
    alone.duration_s = 100.0
    onmc = _make_result(condition="cc_onmc", passed=True, tokens=600)
    onmc.turns = 12
    onmc.cost_usd = 0.20
    onmc.duration_s = 70.0
    cmp = ABTaskComparison(task=task, alone=alone, onmc=onmc)

    assert cmp.token_reduction_pct == pytest.approx(40.0)
    assert cmp.turn_reduction_pct == pytest.approx(40.0)
    assert cmp.cost_reduction_pct == pytest.approx(60.0)
    assert cmp.duration_reduction_pct == pytest.approx(30.0)
    assert cmp.efficiency_win is True


def test_comparison_efficiency_win_requires_both_conditions_to_pass() -> None:
    task = _make_task()
    alone = _make_result(passed=True, tokens=1000)
    onmc = _make_result(condition="cc_onmc", passed=False, tokens=100)
    cmp = ABTaskComparison(task=task, alone=alone, onmc=onmc)

    assert cmp.efficiency_win is False


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
    assert "token_reduction_pct" in d["comparisons"][0]
    assert "cost_reduction_pct" in d["comparisons"][0]


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
        assert (task.id, "cc_alone") in fixtures, f"Missing fixture for ({task.id}, cc_alone)"
        assert (task.id, "cc_onmc") in fixtures, f"Missing fixture for ({task.id}, cc_onmc)"


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


def test_eval_ab_cli_json_is_machine_parseable() -> None:
    result = CliRunner().invoke(app, ["eval", "ab", "--fixture", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["fixture"] is True
    assert payload["total_tasks"] == len(BUILTIN_TASKS)


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
    assert passed is False, f"Gate should FAIL on buggy code but passed. Output:\n{output}"


def test_gate_passes_after_manual_fix(tmp_path: Path) -> None:
    """Gate command passes after the bug is manually corrected."""
    _run_setup(TASK_LIST_SLICE_FIX, tmp_path)

    # Apply the correct fix: change n+1 to n
    utils_path = tmp_path / "utils.py"
    fixed = utils_path.read_text().replace("[:n + 1]", "[:n]")
    utils_path.write_text(fixed)

    passed, output = _run_gate(TASK_LIST_SLICE_FIX, tmp_path)
    assert passed is True, f"Gate should PASS after correct fix but failed. Output:\n{output}"


def test_structured_command_does_not_require_a_shell(tmp_path: Path) -> None:
    result = _run_command(
        "python -c \"from pathlib import Path; Path('proof.txt').write_text('ok')\"",
        tmp_path,
    )
    assert result.returncode == 0
    assert (tmp_path / "proof.txt").read_text() == "ok"


def test_claude_result_reports_requested_model_not_helper_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "result": "done",
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "modelUsage": {
            "claude-haiku-helper": {"inputTokens": 1},
            "claude-sonnet-main": {"inputTokens": 10},
        },
    }
    completed = SimpleNamespace(stdout=json.dumps(payload), stderr="", returncode=0)
    monkeypatch.setattr(
        "oh_no_my_claudecode.evals.ab.runner.subprocess.run",
        lambda *args, **kwargs: completed,
    )

    outcome = _run_claude_agent("fix it", tmp_path, model="sonnet")

    assert outcome.model == "sonnet"


def test_run_ab_rejects_protected_test_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = ABTask(
        id="protected-test",
        description="Fix implementation.py without editing the test.",
        setup_script=(
            "from pathlib import Path\n"
            "Path('implementation.py').write_text('VALUE = 0\\n')\n"
            "Path('test_target.py').write_text('from implementation import VALUE\\n'"
            " 'def test_value():\\n    assert VALUE == 1\\n')\n"
        ),
        gate_command="python -m pytest test_target.py -q",
        onmc_hint="Prior lesson",
        protected_paths=("test_target.py",),
    )

    def tamper_with_test(*args: object, **kwargs: object) -> _AgentOutcome:
        repo_root = args[1]
        assert isinstance(repo_root, Path)
        (repo_root / "test_target.py").write_text("def test_value():\n    assert True\n")
        return _AgentOutcome("tampered", 10, None, 1, 0.01, "sonnet")

    monkeypatch.setattr(
        "oh_no_my_claudecode.evals.ab.runner._run_claude_agent",
        tamper_with_test,
    )

    result = run_ab(task, "cc_alone", repo_root=tmp_path)

    assert result.passed is False
    assert "protected benchmark file modified: test_target.py" in result.gate_output


def test_run_ab_rejects_new_untracked_protected_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A NEW (untracked) file the agent creates must appear in the diff scope and be
    caught by the protected-path guard — git diff alone never lists untracked files."""
    task = ABTask(
        id="protected-new-file",
        description="Fix implementation.py without adding a conftest.",
        setup_script=(
            "from pathlib import Path\n"
            "Path('implementation.py').write_text('VALUE = 0\\n')\n"
            "Path('test_target.py').write_text('from implementation import VALUE\\n'"
            " 'def test_value():\\n    assert VALUE == 1\\n')\n"
        ),
        gate_command="python -m pytest test_target.py -q",
        onmc_hint="Prior lesson",
        protected_paths=("conftest.py",),
    )

    def fix_and_plant_conftest(*args: object, **kwargs: object) -> _AgentOutcome:
        repo_root = args[1]
        assert isinstance(repo_root, Path)
        (repo_root / "implementation.py").write_text("VALUE = 1\n")
        # A brand-new untracked file matching a protected path.
        (repo_root / "conftest.py").write_text("collect_ignore = ['test_target.py']\n")
        return _AgentOutcome("done", 10, None, 1, 0.01, "sonnet")

    monkeypatch.setattr(
        "oh_no_my_claudecode.evals.ab.runner._run_claude_agent",
        fix_and_plant_conftest,
    )

    result = run_ab(task, "cc_alone", repo_root=tmp_path)

    assert "conftest.py" in result.changed_files, (
        "Untracked new files must be included in the reported diff scope"
    )
    assert result.passed is False
    assert "protected benchmark file modified: conftest.py" in result.gate_output


def test_onmc_prompt_uses_real_recall_pipeline() -> None:
    prompt = _build_prompt(TASK_HTTPX_DIRECT_REQUEST_TIMEOUT, "cc_onmc")
    assert "Relevant repo memory" in prompt
    assert "directly constructed Request" in prompt
    assert "## Task" in prompt


def test_alone_prompt_has_no_onmc_memory() -> None:
    prompt = _build_prompt(TASK_HTTPX_DIRECT_REQUEST_TIMEOUT, "cc_alone")
    assert prompt == TASK_HTTPX_DIRECT_REQUEST_TIMEOUT.description
    assert "Relevant repo memory" not in prompt


def test_gate_fails_with_wrong_fix(tmp_path: Path) -> None:
    """The dead-end fix (n-1) still fails the gate."""
    _run_setup(TASK_LIST_SLICE_FIX, tmp_path)

    utils_path = tmp_path / "utils.py"
    wrong = utils_path.read_text().replace("[:n + 1]", "[:n - 1]")
    utils_path.write_text(wrong)

    passed, output = _run_gate(TASK_LIST_SLICE_FIX, tmp_path)
    assert passed is False, f"Gate should FAIL with wrong fix (n-1) but passed. Output:\n{output}"


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


# ---------------------------------------------------------------------------
# Private-knowledge task suite
# ---------------------------------------------------------------------------


from oh_no_my_claudecode.evals.ab.private_tasks import (  # noqa: E402
    PRIVATE_KNOWLEDGE_TASKS,
    TASK_HOUSE_ERROR_CODE_PREFIX,
    TASK_IDEMPOTENCY_KEY_FORMAT,
    TASK_MONEY_MINOR_UNITS,
    TASK_RETRY_ONLY_503_INCIDENT,
    TASK_TENANT_HEADER,
)


def test_private_tasks_count() -> None:
    assert len(PRIVATE_KNOWLEDGE_TASKS) == 5


def test_private_tasks_ids_unique() -> None:
    ids = [t.id for t in PRIVATE_KNOWLEDGE_TASKS]
    assert len(ids) == len(set(ids)), "Private task IDs must be unique"


def test_private_tasks_no_overlap_with_builtin() -> None:
    builtin_ids = {t.id for t in BUILTIN_TASKS}
    private_ids = {t.id for t in PRIVATE_KNOWLEDGE_TASKS}
    overlap = builtin_ids & private_ids
    assert not overlap, f"Task IDs overlap between suites: {overlap}"


def test_private_tasks_all_fields_non_empty() -> None:
    for task in PRIVATE_KNOWLEDGE_TASKS:
        assert task.id, f"Private task missing id: {task}"
        assert task.setup_script, f"Private task {task.id} missing setup_script"
        assert task.gate_command, f"Private task {task.id} missing gate_command"
        assert task.onmc_hint, f"Private task {task.id} missing onmc_hint"
        assert task.description, f"Private task {task.id} missing description"


def test_private_task_house_error_code_prefix_fields() -> None:
    task = TASK_HOUSE_ERROR_CODE_PREFIX
    assert task.id == "house_error_code_prefix"
    assert "ACME" in task.onmc_hint
    assert "pytest" in task.gate_command
    assert task.setup_script


def test_private_task_tenant_header_fields() -> None:
    task = TASK_TENANT_HEADER
    assert task.id == "tenant_header"
    assert "X-Acme-Workspace" in task.onmc_hint
    assert task.setup_script
    assert task.gate_command


def test_private_task_retry_only_503_fields() -> None:
    task = TASK_RETRY_ONLY_503_INCIDENT
    assert task.id == "retry_only_503_incident"
    assert "503" in task.onmc_hint
    assert task.setup_script
    assert task.gate_command


def test_private_task_idempotency_key_fields() -> None:
    task = TASK_IDEMPOTENCY_KEY_FORMAT
    assert task.id == "idempotency_key_format"
    assert ":" in task.onmc_hint
    assert task.setup_script
    assert task.gate_command


def test_private_task_money_minor_units_fields() -> None:
    task = TASK_MONEY_MINOR_UNITS
    assert task.id == "money_minor_units"
    assert "Decimal" in task.onmc_hint
    assert task.setup_script
    assert task.gate_command


def test_private_fixture_has_all_tasks() -> None:
    fixtures = load_fixture_results()
    for task in PRIVATE_KNOWLEDGE_TASKS:
        assert (task.id, "cc_alone") in fixtures, (
            f"Missing private fixture for ({task.id}, cc_alone)"
        )
        assert (task.id, "cc_onmc") in fixtures, (
            f"Missing private fixture for ({task.id}, cc_onmc)"
        )


def test_private_fixture_all_onmc_wins() -> None:
    fixtures = load_fixture_results()
    for task in PRIVATE_KNOWLEDGE_TASKS:
        alone = fixtures[(task.id, "cc_alone")]
        onmc = fixtures[(task.id, "cc_onmc")]
        assert alone.passed is False, (
            f"Fixture: cc_alone should fail on {task.id} (private-knowledge task)"
        )
        assert onmc.passed is True, (
            f"Fixture: cc_onmc should pass on {task.id} (ONMC hint provides the private fact)"
        )


def test_run_suite_private_fixture_returns_report() -> None:
    report = run_suite(PRIVATE_KNOWLEDGE_TASKS, fixture=True)
    assert isinstance(report, ABReport)
    assert report.fixture is True
    assert report.total_tasks == len(PRIVATE_KNOWLEDGE_TASKS)


def test_run_suite_private_fixture_all_onmc_wins() -> None:
    report = run_suite(PRIVATE_KNOWLEDGE_TASKS, fixture=True)
    assert report.onmc_wins == len(PRIVATE_KNOWLEDGE_TASKS), (
        f"Expected all {len(PRIVATE_KNOWLEDGE_TASKS)} private tasks to be ONMC wins "
        f"in fixture mode but got {report.onmc_wins}.  "
        f"Comparisons: {[(c.task.id, c.alone.passed, c.onmc.passed) for c in report.comparisons]}"
    )
    assert report.alone_wins == 0, "No regressions expected in private fixture suite"


def test_run_suite_private_ids_in_report() -> None:
    report = run_suite(PRIVATE_KNOWLEDGE_TASKS, fixture=True)
    reported_ids = {c.task.id for c in report.comparisons}
    expected_ids = {t.id for t in PRIVATE_KNOWLEDGE_TASKS}
    assert reported_ids == expected_ids


def test_private_gate_fails_on_buggy_code_house_error(tmp_path: Path) -> None:
    """The buggy stub (kind.upper()) fails the gate."""
    _run_setup(TASK_HOUSE_ERROR_CODE_PREFIX, tmp_path)
    passed, output = _run_gate(TASK_HOUSE_ERROR_CODE_PREFIX, tmp_path)
    assert passed is False, f"Gate should FAIL on buggy code but passed.\n{output}"


def test_private_gate_passes_after_fix_house_error(tmp_path: Path) -> None:
    """A correct ACME-code dict passes the gate."""
    _run_setup(TASK_HOUSE_ERROR_CODE_PREFIX, tmp_path)
    errors_path = tmp_path / "errors.py"
    fixed = (
        "def format_error(kind: str) -> str:\n"
        "    _codes = {\n"
        "        'not_found': 'ACME-4004',\n"
        "        'unauthorized': 'ACME-4001',\n"
        "        'rate_limited': 'ACME-4029',\n"
        "    }\n"
        "    return _codes[kind]\n"
    )
    errors_path.write_text(fixed)
    passed, output = _run_gate(TASK_HOUSE_ERROR_CODE_PREFIX, tmp_path)
    assert passed is True, f"Gate should PASS after fix.\n{output}"


def test_private_gate_fails_on_buggy_code_retry(tmp_path: Path) -> None:
    """The buggy stub (retries all 5xx) fails the gate."""
    _run_setup(TASK_RETRY_ONLY_503_INCIDENT, tmp_path)
    passed, output = _run_gate(TASK_RETRY_ONLY_503_INCIDENT, tmp_path)
    assert passed is False, f"Gate should FAIL on buggy code but passed.\n{output}"


def test_private_gate_passes_after_fix_retry(tmp_path: Path) -> None:
    """should_retry returning only True for 503 passes the gate."""
    _run_setup(TASK_RETRY_ONLY_503_INCIDENT, tmp_path)
    payment_path = tmp_path / "payment.py"
    fixed = "def should_retry(status: int) -> bool:\n    return status == 503\n"
    payment_path.write_text(fixed)
    passed, output = _run_gate(TASK_RETRY_ONLY_503_INCIDENT, tmp_path)
    assert passed is True, f"Gate should PASS after fix.\n{output}"


def test_private_gate_fails_on_buggy_code_money(tmp_path: Path) -> None:
    """The buggy stub (float conversion) fails the gate on 2.30 -> 229 truncation."""
    _run_setup(TASK_MONEY_MINOR_UNITS, tmp_path)
    # Verify bug is present: int(float("2.30") * 100) must NOT equal 230
    import subprocess  # noqa: E401
    import sys
    result = subprocess.run(
        [sys.executable, "-c", "print(int(float('2.30') * 100))"],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip() == "230":
        pytest.skip("float('2.30')*100 rounds to 230 on this platform — bug not reproducible")
    passed, output = _run_gate(TASK_MONEY_MINOR_UNITS, tmp_path)
    assert passed is False, f"Gate should FAIL on buggy float conversion.\n{output}"


def test_private_gate_passes_after_fix_money(tmp_path: Path) -> None:
    """Decimal-based conversion passes the gate."""
    _run_setup(TASK_MONEY_MINOR_UNITS, tmp_path)
    money_path = tmp_path / "money.py"
    fixed = (
        "from decimal import Decimal\n\n"
        "def to_paise(rupees: str) -> int:\n"
        "    return int(Decimal(rupees) * 100)\n"
    )
    money_path.write_text(fixed)
    passed, output = _run_gate(TASK_MONEY_MINOR_UNITS, tmp_path)
    assert passed is True, f"Gate should PASS after Decimal fix.\n{output}"
