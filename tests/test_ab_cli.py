"""CLI tests for the `onmc eval ab` command.

All tests run in fixture/offline mode — no LLM calls, no network, no claude
CLI required.  Exercises the CLI plumbing from typer invocation through report
rendering and JSON output.

Coverage
--------
- `onmc eval ab --fixture` exits 0 and produces markdown output
- `onmc eval ab --fixture --json` exits 0 and produces valid JSON
- JSON output has expected top-level keys (total_tasks, onmc_wins, comparisons)
- `onmc eval ab --fixture --task list_slice_fix` runs only the named task
- `onmc eval ab --fixture --task nonexistent` exits non-zero with error message
- Markdown output contains expected table and summary sections
- JSON comparisons array has task_id, alone, onmc keys per entry
- Report includes at least the built-in tasks
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app


def test_eval_ab_fixture_exits_zero() -> None:
    """eval ab --fixture must succeed (exit 0) with built-in tasks."""
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "ab", "--fixture"])
    assert result.exit_code == 0, (
        f"eval ab --fixture exited {result.exit_code}.\nOutput: {result.output}"
    )


def test_eval_ab_fixture_produces_markdown_table() -> None:
    """Markdown output must contain the A/B table header and summary lines."""
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "ab", "--fixture"])
    assert result.exit_code == 0
    output = result.output
    assert "A/B Eval Report" in output, "Missing report header in markdown output"
    assert "cc_alone" in output, "Missing cc_alone column label"
    assert "cc_onmc" in output, "Missing cc_onmc column label"


def test_eval_ab_fixture_json_exits_zero() -> None:
    """eval ab --fixture --json must exit 0."""
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "ab", "--fixture", "--json"])
    assert result.exit_code == 0, (
        f"eval ab --fixture --json exited {result.exit_code}.\nOutput: {result.output}"
    )


def test_eval_ab_fixture_json_is_valid() -> None:
    """JSON output must be parseable and have the correct top-level shape."""
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "ab", "--fixture", "--json"])
    assert result.exit_code == 0

    # Find the JSON block — output may have Rich markup, strip it
    output = result.output.strip()
    # CliRunner captures raw output; find the JSON object
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        # Try to extract the JSON from the output if there's surrounding text
        lines = [ln for ln in output.splitlines() if ln.strip().startswith("{")]
        if not lines:
            raise AssertionError(
                f"Could not parse JSON from eval ab output:\n{output}"
            ) from exc
        data = json.loads(lines[0])

    assert "total_tasks" in data, "JSON missing 'total_tasks'"
    assert "onmc_wins" in data, "JSON missing 'onmc_wins'"
    assert "comparisons" in data, "JSON missing 'comparisons'"
    assert "alone_wins" in data, "JSON missing 'alone_wins'"
    assert "both_pass" in data, "JSON missing 'both_pass'"
    assert "onmc_pass_rate" in data, "JSON missing 'onmc_pass_rate'"
    assert "alone_pass_rate" in data, "JSON missing 'alone_pass_rate'"


def test_eval_ab_fixture_json_total_tasks_matches_builtin() -> None:
    """JSON total_tasks must equal the number of built-in tasks."""
    from oh_no_my_claudecode.evals.ab.tasks import BUILTIN_TASKS

    runner = CliRunner()
    result = runner.invoke(app, ["eval", "ab", "--fixture", "--json"])
    assert result.exit_code == 0

    output = result.output.strip()
    data = json.loads(output)
    assert data["total_tasks"] == len(BUILTIN_TASKS), (
        f"Expected total_tasks={len(BUILTIN_TASKS)} but got {data['total_tasks']}"
    )


def test_eval_ab_fixture_json_comparisons_shape() -> None:
    """Each comparison entry in JSON must have task_id, alone, and onmc keys."""
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "ab", "--fixture", "--json"])
    assert result.exit_code == 0

    data = json.loads(result.output.strip())
    comparisons = data["comparisons"]
    assert len(comparisons) > 0, "comparisons array is empty"

    for entry in comparisons:
        assert "task_id" in entry, f"Comparison entry missing 'task_id': {entry}"
        assert "alone" in entry, f"Comparison entry missing 'alone': {entry}"
        assert "onmc" in entry, f"Comparison entry missing 'onmc': {entry}"
        assert "onmc_wins" in entry, f"Comparison entry missing 'onmc_wins': {entry}"

        alone = entry["alone"]
        assert "passed" in alone, f"alone result missing 'passed': {alone}"
        assert "tokens" in alone, f"alone result missing 'tokens': {alone}"

        onmc = entry["onmc"]
        assert "passed" in onmc, f"onmc result missing 'passed': {onmc}"


def test_eval_ab_fixture_task_filter() -> None:
    """--task <id> runs only the specified task."""
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "ab", "--fixture", "--task", "list_slice_fix"])
    assert result.exit_code == 0, (
        f"Filtered eval exited {result.exit_code}.\nOutput: {result.output}"
    )
    assert "list_slice_fix" in result.output


def test_eval_ab_fixture_task_filter_json() -> None:
    """--task filter with --json: total_tasks=1 for known task."""
    runner = CliRunner()
    result = runner.invoke(
        app, ["eval", "ab", "--fixture", "--task", "accumulator_init", "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output.strip())
    assert data["total_tasks"] == 1
    assert data["comparisons"][0]["task_id"] == "accumulator_init"


def test_eval_ab_fixture_task_filter_missing_exits_nonzero() -> None:
    """--task with a nonexistent ID must exit non-zero."""
    runner = CliRunner()
    result = runner.invoke(
        app, ["eval", "ab", "--fixture", "--task", "task_does_not_exist_xyz"]
    )
    assert result.exit_code != 0, (
        f"Expected non-zero exit for missing task but got 0.\nOutput: {result.output}"
    )


def test_eval_ab_fixture_markdown_contains_fixture_mode_label() -> None:
    """Markdown output must indicate FIXTURE mode (not live)."""
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "ab", "--fixture"])
    assert result.exit_code == 0
    assert "FIXTURE" in result.output, (
        "Expected 'FIXTURE' label in markdown output but not found."
    )


def test_eval_ab_fixture_json_fixture_flag_true() -> None:
    """JSON output must have fixture=True in fixture mode."""
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "ab", "--fixture", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output.strip())
    assert data["fixture"] is True, (
        f"Expected fixture=True in JSON but got fixture={data.get('fixture')}"
    )


def test_eval_ab_no_fixture_without_api_key_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live mode without ANTHROPIC_API_KEY must exit non-zero."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "ab"])
    assert result.exit_code != 0, (
        "Expected non-zero exit in live mode without ANTHROPIC_API_KEY."
    )
