"""Tests for ``onmc quickstart`` — zero-config Claude Code onboarding.

Coverage (≥6 tests as required)
--------------------------------
1. plan_quickstart() lists steps init→plug→wrap in that order.
2. run_quickstart() calls injected runners in declaration order.
3. Idempotent skip: runners returning "skipped" propagate through result.
4. QuickstartResult.day1_commands includes /onmc, autopilot, brief, and ui.
5. --json CLI flag emits a {"kind": "quickstart", "steps", "day1_commands"} envelope.
6. A runner that raises is recorded as "error" and subsequent steps still run.
7. QuickstartResult.success is True iff no step has status "error".
8. CLI exits 0 on success and 1 when any step errors.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.quickstart.flow import (
    DAY1_COMMANDS,
    QuickstartResult,
    StepResult,
    StepSpec,
    plan_quickstart,
    run_quickstart,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(name: str) -> StepResult:
    return StepResult(name=name, status="done", detail=f"{name} completed")


def _skip(name: str) -> StepResult:
    return StepResult(name=name, status="skipped", detail="already configured")


def _fake_runners(statuses: dict[str, str]) -> dict[str, Any]:
    """Build injectable runners that return pre-canned StepResults."""

    def make_runner(name: str, status: str) -> Any:
        def _runner(repo_root: Path) -> StepResult:  # noqa: ARG001
            return StepResult(name=name, status=status, detail=f"{name} {status}")  # type: ignore[arg-type]

        return _runner

    return {name: make_runner(name, status) for name, status in statuses.items()}


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


# ---------------------------------------------------------------------------
# Test 1: plan_quickstart() order
# ---------------------------------------------------------------------------


def test_plan_quickstart_lists_steps_in_order() -> None:
    """plan_quickstart() must return init, plug, wrap in that exact order."""
    specs = plan_quickstart()

    assert isinstance(specs, list)
    assert len(specs) == 3  # noqa: PLR2004
    names = [s.name for s in specs]
    assert names == ["init", "plug", "wrap"], f"unexpected order: {names}"
    for spec in specs:
        assert isinstance(spec, StepSpec)
        assert spec.label  # non-empty label


# ---------------------------------------------------------------------------
# Test 2: runners called in declaration order
# ---------------------------------------------------------------------------


def test_run_quickstart_calls_runners_in_order(tmp_path: Path) -> None:
    """run_quickstart() must invoke each runner exactly once, in plan order."""
    call_log: list[str] = []

    def make_logger(name: str) -> Any:
        def _runner(repo_root: Path) -> StepResult:  # noqa: ARG001
            call_log.append(name)
            return _ok(name)

        return _runner

    runners = {
        "init": make_logger("init"),
        "plug": make_logger("plug"),
        "wrap": make_logger("wrap"),
    }
    result = run_quickstart(tmp_path, runners=runners)

    assert call_log == ["init", "plug", "wrap"], f"call order: {call_log}"
    assert len(result.steps) == 3  # noqa: PLR2004
    assert all(s.status == "done" for s in result.steps)


# ---------------------------------------------------------------------------
# Test 3: idempotent skip propagation
# ---------------------------------------------------------------------------


def test_run_quickstart_propagates_skipped_status(tmp_path: Path) -> None:
    """Runners returning 'skipped' must appear as skipped in the result."""
    runners = _fake_runners({"init": "skipped", "plug": "skipped", "wrap": "skipped"})
    result = run_quickstart(tmp_path, runners=runners)

    assert all(s.status == "skipped" for s in result.steps)
    assert result.success  # skipped is not an error
    names = [s.name for s in result.steps]
    assert names == ["init", "plug", "wrap"]


# ---------------------------------------------------------------------------
# Test 4: day-1 commands card content
# ---------------------------------------------------------------------------


def test_day1_commands_include_required_entries(tmp_path: Path) -> None:
    """QuickstartResult.day1_commands must include /onmc, autopilot, brief, and ui."""
    runners = _fake_runners({"init": "done", "plug": "done", "wrap": "done"})
    result = run_quickstart(tmp_path, runners=runners)

    cmds = result.day1_commands
    # Module-level constant also has the same entries.
    assert "/onmc" in DAY1_COMMANDS
    assert any("autopilot" in c for c in DAY1_COMMANDS)
    assert any("brief" in c for c in DAY1_COMMANDS)
    assert any("ui" in c for c in DAY1_COMMANDS)

    # The result carries the same list.
    assert "/onmc" in cmds
    assert any("autopilot" in c for c in cmds)
    assert any("brief" in c for c in cmds)
    assert any("ui" in c for c in cmds)


# ---------------------------------------------------------------------------
# Test 5: --json envelope
# ---------------------------------------------------------------------------


def test_json_envelope_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``onmc quickstart --json`` must emit {kind, steps, day1_commands}."""
    canned = QuickstartResult(
        steps=[
            StepResult(name="init", status="done", detail="memory store created"),
            StepResult(name="plug", status="done", detail="hooks + MCP installed"),
            StepResult(name="wrap", status="done", detail="/onmc installed"),
        ],
    )
    monkeypatch.chdir(tmp_path)
    # Patch discover_repo_root to avoid needing a real git repo.
    with (
        patch(
            "oh_no_my_claudecode.quickstart.commands.discover_repo_root",
            return_value=tmp_path,
        ),
        patch(
            "oh_no_my_claudecode.quickstart.commands.run_quickstart",
            return_value=canned,
        ),
    ):
        runner = _cli_runner()
        invoke_result = runner.invoke(app, ["quickstart", "--json"])

    assert invoke_result.exit_code == 0, invoke_result.output
    payload = json.loads(invoke_result.output)
    assert payload["kind"] == "quickstart"
    assert isinstance(payload["steps"], list)
    assert len(payload["steps"]) == 3  # noqa: PLR2004
    assert isinstance(payload["day1_commands"], list)
    assert len(payload["day1_commands"]) > 0
    # Each step has the right shape.
    for step in payload["steps"]:
        assert {"name", "status", "detail"} <= step.keys()


# ---------------------------------------------------------------------------
# Test 6: failure of one step reported, others still run
# ---------------------------------------------------------------------------


def test_failing_runner_records_error_and_continues(tmp_path: Path) -> None:
    """A runner that raises must be recorded as 'error'; subsequent steps still run."""

    def _boom(repo_root: Path) -> StepResult:  # noqa: ARG001
        msg = "simulated failure"
        raise RuntimeError(msg)

    runners: dict[str, Any] = {
        "init": _boom,
        "plug": lambda root: _ok("plug"),  # noqa: ARG005
        "wrap": lambda root: _ok("wrap"),  # noqa: ARG005
    }
    result = run_quickstart(tmp_path, runners=runners)

    assert len(result.steps) == 3  # noqa: PLR2004
    assert result.steps[0].status == "error"
    assert "simulated failure" in result.steps[0].detail
    # Remaining steps ran normally.
    assert result.steps[1].status == "done"
    assert result.steps[2].status == "done"
    # Overall result is not a success when any step errored.
    assert not result.success


# ---------------------------------------------------------------------------
# Test 7: QuickstartResult.success semantics
# ---------------------------------------------------------------------------


def test_quickstart_result_success_property(tmp_path: Path) -> None:
    """success must be True iff no step has status 'error'."""
    all_done = QuickstartResult(steps=[_ok("init"), _ok("plug"), _ok("wrap")])
    assert all_done.success is True

    with_skip = QuickstartResult(
        steps=[_skip("init"), _ok("plug"), _skip("wrap")]
    )
    assert with_skip.success is True

    with_error = QuickstartResult(
        steps=[_ok("init"), StepResult(name="plug", status="error", detail="boom"), _ok("wrap")]
    )
    assert with_error.success is False


# ---------------------------------------------------------------------------
# Test 8: CLI exit codes
# ---------------------------------------------------------------------------


def test_cli_exits_1_when_step_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI must exit 1 when any step has status 'error'."""
    canned_error = QuickstartResult(
        steps=[
            StepResult(name="init", status="error", detail="git gone"),
            StepResult(name="plug", status="done", detail="ok"),
            StepResult(name="wrap", status="done", detail="ok"),
        ],
    )
    monkeypatch.chdir(tmp_path)
    with (
        patch(
            "oh_no_my_claudecode.quickstart.commands.discover_repo_root",
            return_value=tmp_path,
        ),
        patch(
            "oh_no_my_claudecode.quickstart.commands.run_quickstart",
            return_value=canned_error,
        ),
    ):
        runner = _cli_runner()
        invoke_result = runner.invoke(app, ["quickstart"])

    assert invoke_result.exit_code == 1


def test_cli_exits_0_on_all_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI must exit 0 when all steps succeed or skip."""
    canned_ok = QuickstartResult(
        steps=[
            StepResult(name="init", status="done", detail="created"),
            StepResult(name="plug", status="skipped", detail="already there"),
            StepResult(name="wrap", status="done", detail="active"),
        ],
    )
    monkeypatch.chdir(tmp_path)
    with (
        patch(
            "oh_no_my_claudecode.quickstart.commands.discover_repo_root",
            return_value=tmp_path,
        ),
        patch(
            "oh_no_my_claudecode.quickstart.commands.run_quickstart",
            return_value=canned_ok,
        ),
    ):
        runner = _cli_runner()
        invoke_result = runner.invoke(app, ["quickstart"])

    assert invoke_result.exit_code == 0
