"""CLI-level tests for `onmc eval ab`.

All tests run in fixture mode — no LLM calls, no network, no claude CLI needed.
Exercises the Typer command via CliRunner to verify exit codes, markdown output,
and JSON serialisability.

Coverage
--------
- Fixture mode exits 0 and emits the A/B report header in markdown output
- A known task id appears in the markdown output
- --json flag emits valid JSON with expected top-level keys
- --json reports the correct task count matching BUILTIN_TASKS
- --task filter runs a single task in fixture mode
- --task with an unknown id exits non-zero (ValueError path)
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.evals.ab.tasks import BUILTIN_TASKS

_runner = CliRunner()


def test_eval_ab_fixture_exits_zero() -> None:
    result = _runner.invoke(app, ["eval", "ab", "--fixture"])
    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\n{result.output}"


def test_eval_ab_fixture_markdown_contains_report_header() -> None:
    result = _runner.invoke(app, ["eval", "ab", "--fixture"])
    assert result.exit_code == 0
    assert "A/B Eval Report" in result.output


def test_eval_ab_fixture_markdown_contains_task_ids() -> None:
    result = _runner.invoke(app, ["eval", "ab", "--fixture"])
    assert result.exit_code == 0
    # Every task id must appear in the rendered table
    for task in BUILTIN_TASKS:
        assert task.id in result.output, (
            f"Task id {task.id!r} missing from markdown output"
        )


def test_eval_ab_fixture_markdown_contains_mode_label() -> None:
    result = _runner.invoke(app, ["eval", "ab", "--fixture"])
    assert result.exit_code == 0
    assert "FIXTURE" in result.output


def test_eval_ab_fixture_json_exits_zero() -> None:
    result = _runner.invoke(app, ["eval", "ab", "--fixture", "--json"])
    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\n{result.output}"


def test_eval_ab_fixture_json_is_parseable() -> None:
    result = _runner.invoke(app, ["eval", "ab", "--fixture", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert isinstance(payload, dict)


def test_eval_ab_fixture_json_top_level_keys() -> None:
    result = _runner.invoke(app, ["eval", "ab", "--fixture", "--json"])
    payload = json.loads(result.output)
    for key in ("fixture", "total_tasks", "onmc_wins", "alone_wins", "comparisons"):
        assert key in payload, f"Missing top-level key: {key!r}"


def test_eval_ab_fixture_json_task_count_matches_builtin() -> None:
    result = _runner.invoke(app, ["eval", "ab", "--fixture", "--json"])
    payload = json.loads(result.output)
    assert payload["total_tasks"] == len(BUILTIN_TASKS)
    assert len(payload["comparisons"]) == len(BUILTIN_TASKS)


def test_eval_ab_fixture_json_fixture_flag_true() -> None:
    result = _runner.invoke(app, ["eval", "ab", "--fixture", "--json"])
    payload = json.loads(result.output)
    assert payload["fixture"] is True


def test_eval_ab_fixture_json_has_onmc_wins() -> None:
    result = _runner.invoke(app, ["eval", "ab", "--fixture", "--json"])
    payload = json.loads(result.output)
    # Fixture data has at least 1 ONMC win
    assert payload["onmc_wins"] >= 1


def test_eval_ab_fixture_json_no_regressions() -> None:
    result = _runner.invoke(app, ["eval", "ab", "--fixture", "--json"])
    payload = json.loads(result.output)
    assert payload["alone_wins"] == 0, "Fixture should contain no ONMC regressions"


def test_eval_ab_fixture_task_filter_single() -> None:
    result = _runner.invoke(
        app, ["eval", "ab", "--fixture", "--task", "list_slice_fix"]
    )
    assert result.exit_code == 0
    assert "list_slice_fix" in result.output


def test_eval_ab_fixture_task_filter_json_single() -> None:
    result = _runner.invoke(
        app, ["eval", "ab", "--fixture", "--task", "null_coalesce_zero", "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total_tasks"] == 1
    assert payload["comparisons"][0]["task_id"] == "null_coalesce_zero"


def test_eval_ab_fixture_unknown_task_exits_nonzero() -> None:
    result = _runner.invoke(
        app, ["eval", "ab", "--fixture", "--task", "does_not_exist"]
    )
    assert result.exit_code != 0
