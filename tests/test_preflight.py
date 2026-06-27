"""Tests for ``onmc preflight`` — the local CI gate.

Coverage
--------
- Deterministic core (:func:`run_preflight`) with an INJECTED fake executor:
  all-pass, one-fail (named), ``steps=`` subset, canonical ordering.
- Empty selection is reported as a failure, never a silent pass.
- Step summaries quote the tail of failing output.
- CLI ``onmc preflight``: all-pass exits 0; a failure exits 1; ``--only``
  subset; ``--only`` validation rejects unknown ids (nonzero); ``--json`` shape.

The CLI tests inject a fake executor by monkeypatching the runner's default
executor factory, so no real subprocess (ruff/mypy/pytest) ever runs — the
tests are fully offline and deterministic.  We never assert Rich ``--help``
text; we only exercise flags and assert exit codes / JSON.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.preflight import PreflightReport, StepResult, run_preflight
from oh_no_my_claudecode.preflight import runner as runner_mod
from oh_no_my_claudecode.preflight.runner import STEP_IDS

# ---------------------------------------------------------------------------
# Fake executors
# ---------------------------------------------------------------------------


def _all_pass_executor() -> runner_mod.Executor:
    def _run(cmd: Sequence[str]) -> tuple[int, str]:
        return 0, "ok\n"

    return _run


def _failing_executor(fail_first_token: str) -> runner_mod.Executor:
    """Fail only when the command's first token matches ``fail_first_token``."""

    def _run(cmd: Sequence[str]) -> tuple[int, str]:
        # Match on the tool name regardless of argv shape (e.g. python -m pytest).
        joined = " ".join(cmd)
        if fail_first_token in joined:
            return 1, "some output\nE   AssertionError: boom\n"
        return 0, "ok\n"

    return _run


@pytest.fixture
def cli() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Deterministic core
# ---------------------------------------------------------------------------


def test_all_pass_returns_ok() -> None:
    report = run_preflight(Path("/repo"), executor=_all_pass_executor())
    assert isinstance(report, PreflightReport)
    assert report.ok is True
    assert [s.name for s in report.steps] == list(STEP_IDS)
    assert all(s.ok for s in report.steps)
    assert report.failed == []


def test_one_failure_names_the_step() -> None:
    report = run_preflight(Path("/repo"), executor=_failing_executor("mypy"))
    assert report.ok is False
    failed = report.failed
    assert len(failed) == 1
    assert failed[0].name == "mypy"
    # Summary quotes the tail of the failing output.
    assert "boom" in failed[0].summary
    # Other steps still ran and passed.
    assert {s.name for s in report.steps if s.ok} == {"ruff", "cliref", "pytest"}


def test_steps_subset_runs_only_requested() -> None:
    report = run_preflight(
        Path("/repo"),
        steps=["pytest", "ruff"],
        executor=_all_pass_executor(),
    )
    # Canonical CI order, not the order passed in.
    assert [s.name for s in report.steps] == ["ruff", "pytest"]
    assert report.ok is True


def test_unknown_steps_are_ignored_but_valid_ones_run() -> None:
    report = run_preflight(
        Path("/repo"),
        steps=["ruff", "bogus"],
        executor=_all_pass_executor(),
    )
    assert [s.name for s in report.steps] == ["ruff"]
    assert report.ok is True


def test_empty_selection_is_a_failure_not_a_pass() -> None:
    report = run_preflight(
        Path("/repo"),
        steps=["bogus"],
        executor=_all_pass_executor(),
    )
    assert report.ok is False
    assert len(report.steps) == 1
    assert report.steps[0].ok is False


def test_step_result_label_is_human_readable() -> None:
    result = StepResult(name="ruff", ok=True, summary="passed")
    assert result.label == "ruff check"


def test_passing_summary_is_passed() -> None:
    report = run_preflight(Path("/repo"), steps=["ruff"], executor=_all_pass_executor())
    assert report.steps[0].summary == "passed"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_all_pass_exits_zero(cli: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runner_mod, "_default_executor", lambda _root: _all_pass_executor()
    )
    result = cli.invoke(app, ["preflight"])
    assert result.exit_code == 0


def test_cli_failure_exits_one(cli: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runner_mod, "_default_executor", lambda _root: _failing_executor("ruff")
    )
    result = cli.invoke(app, ["preflight"])
    assert result.exit_code == 1


def test_cli_only_subset_runs(cli: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def _spy_factory(_root: Path) -> runner_mod.Executor:
        def _run(cmd: Sequence[str]) -> tuple[int, str]:
            seen.append(" ".join(cmd))
            return 0, "ok\n"

        return _run

    monkeypatch.setattr(runner_mod, "_default_executor", _spy_factory)
    result = cli.invoke(app, ["preflight", "--only", "ruff"])
    assert result.exit_code == 0
    assert len(seen) == 1
    assert "ruff" in seen[0]


def test_cli_only_rejects_unknown_step(cli: CliRunner) -> None:
    result = cli.invoke(app, ["preflight", "--only", "nope"])
    # _fatal() drives a non-zero exit; the run never proceeds to the gate.
    assert result.exit_code != 0


def test_cli_json_shape(cli: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runner_mod, "_default_executor", lambda _root: _failing_executor("mypy")
    )
    result = cli.invoke(app, ["preflight", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    names = [step["name"] for step in payload["steps"]]
    assert names == list(STEP_IDS)
    failing = [step for step in payload["steps"] if not step["ok"]]
    assert len(failing) == 1
    assert failing[0]["name"] == "mypy"


def test_cli_json_all_pass(cli: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runner_mod, "_default_executor", lambda _root: _all_pass_executor()
    )
    result = cli.invoke(app, ["preflight", "--only", "ruff", "--only", "pytest", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert [s["name"] for s in payload["steps"]] == ["ruff", "pytest"]
