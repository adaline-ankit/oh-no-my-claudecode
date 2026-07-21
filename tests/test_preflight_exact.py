"""Tests for ``onmc preflight --exact`` and ``onmc preflight --fix``.

Coverage
--------
- :func:`run_preflight_exact` with an injected fake executor:
  all-pass, one-fail, per-gate verdict aggregation, canonical step order.
- :func:`run_preflight_fix` with a recording executor:
  ``ruff check --fix .`` invoked first, cli-reference regen invoked second
  (without ``--check``), exact gate re-run third.
- ``--fix`` failure in a fix action propagates to ``ExactReport.ok``.
- Existing :func:`run_preflight` behaviour is unchanged (regression guard).
- Deterministic: same inputs produce same order and same verdicts across calls.
- A single guarded real smoke test that runs the actual gate via ``uv``
  (skipped when ``uv`` is absent so it never blocks offline/CI runs).

The tests NEVER invoke Rich ``--help``; all CLI tests assert exit codes and
JSON shapes only, using a fake executor injected via monkeypatch.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.preflight import (
    ExactReport,
    PreflightReport,
    run_preflight,
    run_preflight_exact,
    run_preflight_fix,
)
from oh_no_my_claudecode.preflight import runner as runner_mod
from oh_no_my_claudecode.preflight.runner import (
    FIX_STEP_IDS,
    STEP_IDS,
    _exact_command_for,
    _fix_command_for,
    _provisioned_exact_command_for,
)

# ---------------------------------------------------------------------------
# Shared fake executors
# ---------------------------------------------------------------------------


def _all_pass() -> runner_mod.Executor:
    """Executor that always returns success."""

    def _run(cmd: Sequence[str]) -> tuple[int, str]:
        return 0, "ok\n"

    return _run


def _fail_step(fail_token: str) -> runner_mod.Executor:
    """Fail when ``fail_token`` appears in the joined command string."""

    def _run(cmd: Sequence[str]) -> tuple[int, str]:
        if fail_token in " ".join(cmd):
            return 1, "error output\nE  AssertionError: boom\n"
        return 0, "ok\n"

    return _run


def _recording() -> tuple[list[str], runner_mod.Executor]:
    """Return a (log, executor) pair.  Each invocation appends its joined cmd."""
    log: list[str] = []

    def _run(cmd: Sequence[str]) -> tuple[int, str]:
        log.append(" ".join(cmd))
        return 0, "ok\n"

    return log, _run


# ---------------------------------------------------------------------------
# 1. run_preflight_exact — per-gate verdict aggregation
# ---------------------------------------------------------------------------


def test_exact_all_pass_aggregates_verdicts() -> None:
    """All gates pass → PreflightReport.ok=True, all 4 steps present."""
    report = run_preflight_exact(Path("/repo"), executor=_all_pass())
    assert isinstance(report, PreflightReport)
    assert report.ok is True
    assert [s.name for s in report.steps] == list(STEP_IDS)
    assert all(s.ok for s in report.steps)
    assert report.failed == []


def test_exact_one_failing_gate_sets_overall_fail() -> None:
    """One failing gate → overall fail, correct step name flagged."""
    report = run_preflight_exact(Path("/repo"), executor=_fail_step("pytest"))
    assert report.ok is False
    failed = report.failed
    assert len(failed) == 1
    assert failed[0].name == "pytest"
    assert "boom" in failed[0].summary
    # Other steps still ran.
    assert {s.name for s in report.steps if s.ok} == {"ruff", "mypy", "cliref"}


def test_exact_steps_subset_canonical_order() -> None:
    """``steps=`` subset respects canonical CI order."""
    report = run_preflight_exact(
        Path("/repo"),
        steps=["pytest", "ruff"],
        executor=_all_pass(),
    )
    assert [s.name for s in report.steps] == ["ruff", "pytest"]
    assert report.ok is True


def test_exact_empty_selection_is_failure() -> None:
    report = run_preflight_exact(
        Path("/repo"),
        steps=["bogus"],
        executor=_all_pass(),
    )
    assert report.ok is False


# ---------------------------------------------------------------------------
# 2. Exact commands differ from the base commands (coverage gate)
# ---------------------------------------------------------------------------


def test_exact_pytest_command_includes_coverage_flags() -> None:
    cmd = _exact_command_for("pytest")
    joined = " ".join(cmd)
    assert "--cov=oh_no_my_claudecode" in joined
    assert "--cov-fail-under=80" in joined
    assert "--cov-report=term-missing" in joined


def test_exact_cliref_command_has_check_flag() -> None:
    cmd = _exact_command_for("cliref")
    assert "--check" in cmd


def test_provisioned_exact_cliref_pins_typer() -> None:
    cmd = _provisioned_exact_command_for("cliref")
    joined = " ".join(cmd)
    assert "uv run" in joined
    assert "typer==0.26.8" in joined
    assert "--upgrade-package typer" in joined
    assert "--check" in joined


def test_provisioned_exact_pytest_includes_pytest_cov() -> None:
    cmd = _provisioned_exact_command_for("pytest")
    joined = " ".join(cmd)
    assert "uv run" in joined
    assert "pytest-cov" in joined
    assert "--cov-fail-under=80" in joined


# ---------------------------------------------------------------------------
# 3. run_preflight_fix — command recording (no real subprocess)
# ---------------------------------------------------------------------------


def test_fix_invokes_ruff_fix_before_cliref_regen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--fix`` must call ruff --fix first, then cli-ref regen (no --check)."""
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: False)
    log, exe = _recording()
    result = run_preflight_fix(Path("/repo"), executor=exe)
    # At least the two fix commands + four exact gate commands ran.
    assert len(log) >= 2 + len(STEP_IDS)
    # Fix commands in order.
    assert "ruff check --fix ." in log[0]
    assert "generate-cli-reference.py" in log[1]
    assert "--check" not in log[1], "--fix must NOT pass --check to the regen step"
    assert isinstance(result, ExactReport)
    assert isinstance(result.gate, PreflightReport)


def test_fix_ruff_cmd_is_not_ruff_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ruff fix command must use ``ruff check --fix``, never ``ruff format``."""
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: False)
    cmd = _fix_command_for("ruff-fix", use_uv=False)
    joined = " ".join(cmd)
    assert "ruff check --fix" in joined
    assert "format" not in joined


def test_fix_cliref_regen_cmd_has_no_check_flag() -> None:
    cmd = _fix_command_for("cliref-regen", use_uv=False)
    assert "--check" not in cmd


def test_fix_provisioned_cliref_regen_pins_typer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: True)
    cmd = _fix_command_for("cliref-regen", use_uv=True)
    joined = " ".join(cmd)
    assert "typer==0.26.8" in joined
    assert "--upgrade-package typer" in joined
    assert "--check" not in joined


def test_fix_failure_propagates_to_exact_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing fix action → ExactReport.ok is False."""
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: False)
    # Make ruff --fix fail; gate passes.
    failed_log: list[str] = []

    def _fail_ruff_fix(cmd: Sequence[str]) -> tuple[int, str]:
        failed_log.append(" ".join(cmd))
        if "ruff check --fix" in " ".join(cmd):
            return 2, "ruff: fatal error\n"
        return 0, "ok\n"

    result = run_preflight_fix(Path("/repo"), executor=_fail_ruff_fix)
    assert result.ok is False
    ruff_fix_step = next(fs for fs in result.fix_steps if fs.name == "ruff-fix")
    assert ruff_fix_step.ok is False
    assert "ruff: fatal error" in ruff_fix_step.summary


def test_fix_step_cmd_field_records_exact_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FixStep.cmd records the exact argv that was run."""
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: False)
    _, exe = _recording()
    result = run_preflight_fix(Path("/repo"), executor=exe)
    ruff_fix = next(fs for fs in result.fix_steps if fs.name == "ruff-fix")
    assert ruff_fix.cmd == ["ruff", "check", "--fix", "."]


def test_fix_step_ids_constant_matches_expected() -> None:
    assert FIX_STEP_IDS == ("ruff-fix", "cliref-regen")


# ---------------------------------------------------------------------------
# 4. Existing run_preflight behaviour is unchanged (regression guard)
# ---------------------------------------------------------------------------


def test_existing_preflight_all_pass_unchanged() -> None:
    """Original run_preflight still works and is unaffected by the new code."""
    report = run_preflight(Path("/repo"), executor=_all_pass())
    assert report.ok is True
    assert [s.name for s in report.steps] == list(STEP_IDS)


def test_existing_preflight_failure_unchanged() -> None:
    report = run_preflight(Path("/repo"), executor=_fail_step("mypy"))
    assert report.ok is False
    assert report.failed[0].name == "mypy"


def test_existing_preflight_provision_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: True)
    log, exe = _recording()
    report = run_preflight(Path("/repo"), steps=["ruff"], executor=exe, provision=True)
    assert report.ok is True
    assert log == ["uv run --with ruff ruff check ."]


# ---------------------------------------------------------------------------
# 5. Determinism
# ---------------------------------------------------------------------------


def test_exact_deterministic_step_order() -> None:
    """Two calls with the same executor return steps in the same order."""
    r1 = run_preflight_exact(Path("/repo"), executor=_all_pass())
    r2 = run_preflight_exact(Path("/repo"), executor=_all_pass())
    assert [s.name for s in r1.steps] == [s.name for s in r2.steps]


def test_exact_deterministic_verdicts() -> None:
    r1 = run_preflight_exact(Path("/repo"), executor=_fail_step("mypy"))
    r2 = run_preflight_exact(Path("/repo"), executor=_fail_step("mypy"))
    assert r1.ok == r2.ok
    assert [s.ok for s in r1.steps] == [s.ok for s in r2.steps]


# ---------------------------------------------------------------------------
# 6. CLI wiring — --exact and --fix flags
# ---------------------------------------------------------------------------


@pytest.fixture
def cli() -> CliRunner:
    return CliRunner()


def test_cli_exact_all_pass_exits_zero(
    cli: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: False)
    monkeypatch.setattr(
        runner_mod, "_default_executor", lambda _root: _all_pass()
    )
    result = cli.invoke(app, ["preflight", "--exact"])
    assert result.exit_code == 0


def test_cli_exact_failure_exits_one(
    cli: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: False)
    monkeypatch.setattr(
        runner_mod, "_default_executor", lambda _root: _fail_step("pytest")
    )
    result = cli.invoke(app, ["preflight", "--exact"])
    assert result.exit_code == 1


def test_cli_exact_json_shape(
    cli: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: False)
    monkeypatch.setattr(
        runner_mod, "_default_executor", lambda _root: _fail_step("mypy")
    )
    result = cli.invoke(app, ["preflight", "--exact", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    names = [s["name"] for s in payload["steps"]]
    assert names == list(STEP_IDS)


def test_cli_fix_all_pass_exits_zero(
    cli: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: False)
    monkeypatch.setattr(
        runner_mod, "_default_executor", lambda _root: _all_pass()
    )
    result = cli.invoke(app, ["preflight", "--fix"])
    assert result.exit_code == 0


def test_cli_fix_failure_exits_one(
    cli: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: False)
    monkeypatch.setattr(
        runner_mod, "_default_executor", lambda _root: _fail_step("pytest")
    )
    result = cli.invoke(app, ["preflight", "--fix"])
    assert result.exit_code == 1


def test_cli_fix_json_has_fix_steps_and_gate(
    cli: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: False)
    monkeypatch.setattr(
        runner_mod, "_default_executor", lambda _root: _all_pass()
    )
    result = cli.invoke(app, ["preflight", "--fix", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert "fix_steps" in payload
    assert "gate" in payload
    fix_names = [fs["name"] for fs in payload["fix_steps"]]
    assert fix_names == list(FIX_STEP_IDS)


def test_cli_exact_without_fix_does_not_run_fix_commands(
    cli: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--exact`` (without ``--fix``) must NOT invoke ruff --fix."""
    monkeypatch.setattr(runner_mod, "_uv_available", lambda: False)
    log: list[str] = []

    def _spy(_root: Path) -> runner_mod.Executor:
        def _run(cmd: Sequence[str]) -> tuple[int, str]:
            log.append(" ".join(cmd))
            return 0, "ok\n"

        return _run

    monkeypatch.setattr(runner_mod, "_default_executor", _spy)
    result = cli.invoke(app, ["preflight", "--exact"])
    assert result.exit_code == 0
    assert not any("--fix" in c for c in log), "ruff --fix must NOT run in --exact mode"


# ---------------------------------------------------------------------------
# 7. Smoke test: real gate via uv (skipped when uv is absent)
# ---------------------------------------------------------------------------

_HAS_UV = shutil.which("uv") is not None


@pytest.mark.skipif(not _HAS_UV, reason="uv not installed — skipping real smoke")
def test_exact_smoke_real_run(tmp_path: Path) -> None:
    """Run the exact gate against the actual repo root.

    This smoke test verifies end-to-end wiring (uv provisioning, actual
    subprocess execution) without mocking.  It only runs when ``uv`` is
    installed; CI always has uv so it runs there.
    """
    # Discover actual repo root from the test file's location.
    repo_root = Path(__file__).resolve().parents[1]
    report = run_preflight_exact(
        repo_root,
        steps=["ruff"],  # Only ruff — cheap, fast, no network.
        executor=None,  # Real subprocess.
    )
    assert isinstance(report, PreflightReport)
    assert len(report.steps) == 1
    assert report.steps[0].name == "ruff"
    # ruff must pass on a clean checkout.
    assert report.steps[0].ok, f"ruff failed: {report.steps[0].summary}"
