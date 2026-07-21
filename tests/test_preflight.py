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


@pytest.fixture
def tools_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend every tool is importable.

    The CLI path calls ``run_preflight`` with ``executor=None``, so the runner
    builds the (monkeypatched) default executor — but it now also runs tool
    availability detection first.  In the test venv ruff/mypy aren't installed,
    which would short-circuit before the fake executor runs.  These CLI tests
    are about flag/exit-code/JSON wiring, so we mark all tools available and let
    the injected fake decide pass/fail.
    """
    monkeypatch.setattr(runner_mod, "_tool_importable", lambda _step_id: True)


def test_cli_all_pass_exits_zero(
    cli: CliRunner, monkeypatch: pytest.MonkeyPatch, tools_available: None
) -> None:
    monkeypatch.setattr(
        runner_mod, "_default_executor", lambda _root: _all_pass_executor()
    )
    result = cli.invoke(app, ["preflight"])
    assert result.exit_code == 0


def test_cli_failure_exits_one(
    cli: CliRunner, monkeypatch: pytest.MonkeyPatch, tools_available: None
) -> None:
    monkeypatch.setattr(
        runner_mod, "_default_executor", lambda _root: _failing_executor("ruff")
    )
    result = cli.invoke(app, ["preflight"])
    assert result.exit_code == 1


def test_cli_only_subset_runs(
    cli: CliRunner, monkeypatch: pytest.MonkeyPatch, tools_available: None
) -> None:
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


def test_cli_json_shape(
    cli: CliRunner, monkeypatch: pytest.MonkeyPatch, tools_available: None
) -> None:
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


def test_cli_json_all_pass(
    cli: CliRunner, monkeypatch: pytest.MonkeyPatch, tools_available: None
) -> None:
    monkeypatch.setattr(
        runner_mod, "_default_executor", lambda _root: _all_pass_executor()
    )
    result = cli.invoke(app, ["preflight", "--only", "ruff", "--only", "pytest", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert [s["name"] for s in payload["steps"]] == ["ruff", "pytest"]


# ---------------------------------------------------------------------------
# Fresh-worktree robustness: missing tools & provisioning
# ---------------------------------------------------------------------------


def _recording_executor(seen: list[str]) -> runner_mod.Executor:
    """An executor that records each command (joined) and always passes."""

    def _run(cmd: Sequence[str]) -> tuple[int, str]:
        seen.append(" ".join(cmd))
        return 0, "ok\n"

    return _run


def test_missing_tool_is_reported_clearly_not_crashed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean (unprovisioned) env without ruff yields a handled result.

    Availability detection only applies to the DEFAULT subprocess executor, so
    we install a default factory whose runner explodes if ever asked to run a
    missing tool — proving the gate short-circuits before reaching it.
    """
    monkeypatch.setattr(
        runner_mod,
        "_tool_importable",
        lambda step_id: step_id != "ruff",
    )

    def _explode_factory(_root: Path) -> runner_mod.Executor:
        def _run(cmd: Sequence[str]) -> tuple[int, str]:  # pragma: no cover
            raise AssertionError("executor should not run a missing tool")

        return _run

    monkeypatch.setattr(runner_mod, "_default_executor", _explode_factory)

    report = run_preflight(Path("/repo"), steps=["ruff"])
    assert report.ok is False
    assert len(report.steps) == 1
    step = report.steps[0]
    assert step.name == "ruff"
    assert step.ok is False
    # Honest, actionable message — not a raw "No module named ruff" crash.
    assert "not installed" in step.summary
    assert "--provision" in step.summary


def test_provision_uses_uv_run_with_for_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``provision=True`` (and uv present) tools run via ``uv run --with``."""
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: True)
    seen: list[str] = []
    report = run_preflight(
        Path("/repo"),
        steps=["ruff", "mypy", "pytest"],
        executor=_recording_executor(seen),
        provision=True,
    )
    assert report.ok is True
    assert seen == [
        "uv run --with ruff ruff check .",
        "uv run --with mypy mypy --strict src/oh_no_my_claudecode",
        "uv run --with pytest python -m pytest tests/",
    ]


def test_provision_cliref_pins_typer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The provisioned cli-reference step pins typer==0.26.8 to match CI."""
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: True)
    seen: list[str] = []
    report = run_preflight(
        Path("/repo"),
        steps=["cliref"],
        executor=_recording_executor(seen),
        provision=True,
    )
    assert report.ok is True
    assert len(seen) == 1
    cmd = seen[0]
    assert "uv run" in cmd
    assert "--with typer==0.26.8" in cmd
    assert "--upgrade-package typer" in cmd
    assert "scripts/generate-cli-reference.py --check" in cmd


def test_provision_falls_back_when_uv_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asking to provision without uv installed degrades to a clear message.

    Uses the default-executor path (no injected executor) so availability
    detection runs; the factory explodes to prove no command is dispatched.
    """
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: False)
    # ruff also not importable in this simulated fresh env.
    monkeypatch.setattr(runner_mod, "_tool_importable", lambda step_id: False)

    def _explode_factory(_root: Path) -> runner_mod.Executor:
        def _run(cmd: Sequence[str]) -> tuple[int, str]:  # pragma: no cover
            raise AssertionError("no command should run when uv+tool absent")

        return _run

    monkeypatch.setattr(runner_mod, "_default_executor", _explode_factory)

    report = run_preflight(Path("/repo"), steps=["ruff"], provision=True)
    # No command ran (tool missing, no uv to provision it) — honest fail.
    assert report.ok is False
    summary = report.steps[0].summary
    assert "not installed" in summary
    assert "uv" in summary


def test_not_provisioned_runs_plain_command_when_tool_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Back-compat: an already-provisioned env runs the bare CI command."""
    monkeypatch.setattr(runner_mod, "_tool_importable", lambda step_id: True)
    seen: list[str] = []
    report = run_preflight(
        Path("/repo"),
        steps=["ruff"],
        executor=_recording_executor(seen),
    )
    assert report.ok is True
    assert seen == ["ruff check ."]


def test_cli_provision_flag_passes_through(
    cli: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``onmc preflight --provision`` reaches the runner with provisioning on."""
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: True)
    seen: list[str] = []
    monkeypatch.setattr(
        runner_mod, "_default_executor", lambda _root: _recording_executor(seen)
    )
    result = cli.invoke(app, ["preflight", "--only", "ruff", "--provision"])
    assert result.exit_code == 0
    assert len(seen) == 1
    assert seen[0] == "uv run --with ruff ruff check ."
