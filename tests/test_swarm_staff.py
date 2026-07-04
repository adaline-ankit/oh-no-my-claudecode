"""Tests for swarm staff-engineer mode — the HONEST per-unit quality gate.

ALL tests inject executors / runners / diff text.  NO real subprocess, git, gh,
or network is ever touched.  Coverage:

- verify_unit ok ONLY when BOTH preflight + diff pass.
- empty diff -> not ok (the headline false-converge gate).
- failing preflight -> not ok even with a real diff.
- record --auto-verify sets verified from the gate, IGNORING the caller's
  --verified (a failing gate -> verified:false even if caller passed verified).
- swarm verify exit codes + --json.
- swarm pr refuses an unverified unit, opens a PR (mocked gh) for a verified one.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.swarm.inline import plan_inline_swarm, record_inline_unit
from oh_no_my_claudecode.swarm.orchestrator import swarm_state
from oh_no_my_claudecode.swarm.staff import open_unit_pr, verify_unit

_FIXED_NOW = datetime(2024, 8, 1, 10, 0, 0, tzinfo=UTC)

# A diff that adds a real, lawful line.
_REAL_DIFF = (
    "diff --git a/src/a.py b/src/a.py\n"
    "--- a/src/a.py\n"
    "+++ b/src/a.py\n"
    "@@ -0,0 +1,1 @@\n"
    "+value = 1\n"
)


def _fake_git_runner(cmd: list[str], cwd: str, timeout: int) -> tuple[int, str]:
    """Deterministic receipt git runner (matches test_swarm)."""
    del cwd, timeout
    if "rev-parse" in cmd or "tree" in " ".join(cmd):
        return (0, "treesha123")
    return (0, "diff body")


def _pass_executor(cmd: Sequence[str]) -> tuple[int, str]:
    """Preflight executor where every step passes."""
    del cmd
    return (0, "ok")


def _fail_executor(cmd: Sequence[str]) -> tuple[int, str]:
    """Preflight executor where every step fails."""
    del cmd
    return (1, "boom")


# ---------------------------------------------------------------------------
# verify_unit
# ---------------------------------------------------------------------------


class TestVerifyUnit:
    def test_ok_only_when_both_pass(self, tmp_path: Path) -> None:
        v = verify_unit(
            tmp_path,
            tmp_path,
            "main",
            unit_id="unit-0000",
            preflight_executor=_pass_executor,
            diff_text=_REAL_DIFF,
        )
        assert v.preflight_ok is True
        assert v.diff_ok is True
        assert v.ok is True

    def test_empty_diff_not_ok(self, tmp_path: Path) -> None:
        """The headline: a passing preflight over an EMPTY diff is NOT ok."""
        v = verify_unit(
            tmp_path,
            tmp_path,
            "main",
            preflight_executor=_pass_executor,
            diff_text="",
        )
        assert v.preflight_ok is True
        assert v.diff_ok is False
        assert v.ok is False

    def test_failing_preflight_not_ok(self, tmp_path: Path) -> None:
        v = verify_unit(
            tmp_path,
            tmp_path,
            "main",
            preflight_executor=_fail_executor,
            diff_text=_REAL_DIFF,
        )
        assert v.preflight_ok is False
        assert v.diff_ok is True
        assert v.ok is False

    def test_both_fail_not_ok(self, tmp_path: Path) -> None:
        v = verify_unit(
            tmp_path,
            tmp_path,
            "main",
            preflight_executor=_fail_executor,
            diff_text="",
        )
        assert v.ok is False
        assert any("FAIL" in line for line in v.details)


# ---------------------------------------------------------------------------
# record --auto-verify (the verifier override)
# ---------------------------------------------------------------------------


class TestAutoVerifyRecord:
    def test_auto_verify_overrides_caller_attestation_to_false(self, tmp_path: Path) -> None:
        """Caller passes verified=True but the gate fails -> verified:false."""
        plan_inline_swarm(tmp_path, ["do A"], concurrency=1, swarm_id="aa11", now=_FIXED_NOW)
        res = record_inline_unit(
            tmp_path,
            "aa11",
            "unit-0000",
            goal="do A",
            summary="claims success",
            verified=True,  # caller LIES
            now=_FIXED_NOW,
            git_runner=_fake_git_runner,
            verifier=lambda: False,  # the REAL gate disagrees
        )
        assert res["verified"] is False
        assert res["status"] == "failed"
        state = swarm_state(tmp_path, "aa11")
        assert state["units"]["unit-0000"]["verified"] is False

    def test_auto_verify_passes_when_gate_passes(self, tmp_path: Path) -> None:
        plan_inline_swarm(tmp_path, ["do B"], concurrency=1, swarm_id="bb22", now=_FIXED_NOW)
        res = record_inline_unit(
            tmp_path,
            "bb22",
            "unit-0000",
            goal="do B",
            summary="real work",
            verified=False,  # caller is conservative
            now=_FIXED_NOW,
            git_runner=_fake_git_runner,
            verifier=lambda: True,  # gate confirms
        )
        assert res["verified"] is True
        assert res["status"] == "done"

    def test_no_verifier_keeps_caller_attestation(self, tmp_path: Path) -> None:
        """Back-compat: without a verifier, caller's --verified is used."""
        plan_inline_swarm(tmp_path, ["do C"], concurrency=1, swarm_id="cc33", now=_FIXED_NOW)
        res = record_inline_unit(
            tmp_path,
            "cc33",
            "unit-0000",
            goal="do C",
            summary="ok",
            verified=True,
            now=_FIXED_NOW,
            git_runner=_fake_git_runner,
        )
        assert res["verified"] is True
        assert res["status"] == "done"

    def test_aborted_skips_verifier(self, tmp_path: Path) -> None:
        plan_inline_swarm(tmp_path, ["do D"], concurrency=1, swarm_id="dd44", now=_FIXED_NOW)
        called: list[bool] = []

        def _verifier() -> bool:
            called.append(True)
            return True

        res = record_inline_unit(
            tmp_path,
            "dd44",
            "unit-0000",
            goal="do D",
            summary="cut short",
            verified=False,
            aborted=True,
            now=_FIXED_NOW,
            git_runner=_fake_git_runner,
            verifier=_verifier,
        )
        assert res["status"] == "aborted"
        assert called == []  # verifier not consulted for aborts


# ---------------------------------------------------------------------------
# open_unit_pr (mocked git/gh runner)
# ---------------------------------------------------------------------------


class TestOpenUnitPr:
    def test_opens_pr_with_mocked_gh(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []

        def _runner(cmd: Sequence[str], cwd: Path) -> tuple[int, str]:
            del cwd
            calls.append(list(cmd))
            if cmd[:2] == ["git", "rev-parse"]:
                return (0, "onmc-swarm-unit-0000\n")
            if cmd[:2] == ["git", "push"]:
                return (0, "pushed")
            if cmd[:2] == ["gh", "pr"]:
                return (0, "https://github.com/x/y/pull/7\n")
            return (1, "unexpected")

        res = open_unit_pr(
            tmp_path,
            tmp_path,
            "main",
            unit_id="unit-0000",
            runner=_runner,
        )
        assert res.ok is True
        assert res.pr_url == "https://github.com/x/y/pull/7"
        assert res.branch == "onmc-swarm-unit-0000"
        assert any(c[:2] == ["gh", "pr"] for c in calls)

    def test_push_failure_no_pr(self, tmp_path: Path) -> None:
        def _runner(cmd: Sequence[str], cwd: Path) -> tuple[int, str]:
            del cwd
            if cmd[:2] == ["git", "rev-parse"]:
                return (0, "branch-x\n")
            if cmd[:2] == ["git", "push"]:
                return (1, "permission denied")
            raise AssertionError("gh must not run after a failed push")

        res = open_unit_pr(tmp_path, tmp_path, "main", unit_id="u", runner=_runner)
        assert res.ok is False
        assert res.pr_url == ""


# ---------------------------------------------------------------------------
# CLI: swarm verify / swarm pr
# ---------------------------------------------------------------------------


class _FakeService:
    """Stand-in OnmcService whose _load_context returns a fixed repo root.

    Lets CLI tests run offline without a real git repo / onmc setup.
    """

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def _load_context(self) -> tuple[Path, None, None]:
        return self._repo_root, None, None


def _patch_context(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """Patch the CLI's _service() so commands resolve repo_root to tmp_path."""
    (tmp_path / ".onmc").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "oh_no_my_claudecode.cli._service",
        lambda: _FakeService(tmp_path),
    )


class TestSwarmVerifyCli:
    def test_verify_json_ok_exit_zero(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        _patch_context(monkeypatch, tmp_path)
        plan_inline_swarm(tmp_path, ["x"], concurrency=1, swarm_id="ee55", now=_FIXED_NOW)

        monkeypatch.setattr(
            "oh_no_my_claudecode.swarm.staff.run_preflight",
            lambda root, executor=None, provision=False: _PassReport(),
        )
        monkeypatch.setattr(
            "oh_no_my_claudecode.swarm.staff.collect_diff",
            lambda root, base: _REAL_DIFF,
        )

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["swarm", "verify", "ee55", "unit-0000", "--worktree", str(tmp_path), "--json"],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True

    def test_verify_empty_diff_exit_nonzero(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        _patch_context(monkeypatch, tmp_path)
        plan_inline_swarm(tmp_path, ["x"], concurrency=1, swarm_id="ff66", now=_FIXED_NOW)

        monkeypatch.setattr(
            "oh_no_my_claudecode.swarm.staff.run_preflight",
            lambda root, executor=None, provision=False: _PassReport(),
        )
        monkeypatch.setattr(
            "oh_no_my_claudecode.swarm.staff.collect_diff",
            lambda root, base: "",
        )

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["swarm", "verify", "ff66", "unit-0000", "--worktree", str(tmp_path), "--json"],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["diff_ok"] is False


class TestSwarmPrCli:
    def test_pr_refuses_unverified_unit(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        _patch_context(monkeypatch, tmp_path)
        plan_inline_swarm(tmp_path, ["x"], concurrency=1, swarm_id="gg77", now=_FIXED_NOW)
        # Unit stays pending/unverified.

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["swarm", "pr", "gg77", "unit-0000", "--worktree", str(tmp_path)],
        )
        assert result.exit_code == 1
        assert "not verified" in result.stdout.lower()

    def test_pr_opens_for_verified_unit(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        _patch_context(monkeypatch, tmp_path)
        plan_inline_swarm(tmp_path, ["x"], concurrency=1, swarm_id="hh88", now=_FIXED_NOW)
        record_inline_unit(
            tmp_path,
            "hh88",
            "unit-0000",
            goal="x",
            summary="done",
            verified=True,
            now=_FIXED_NOW,
            git_runner=_fake_git_runner,
        )

        def _fake_open(repo_root, worktree, base, *, unit_id="", title=None):  # type: ignore[no-untyped-def]
            from oh_no_my_claudecode.swarm.staff import UnitPrResult

            return UnitPrResult(
                unit_id=unit_id,
                ok=True,
                branch="b",
                pr_url="https://example/pr/1",
                details=["pr: ok"],
            )

        monkeypatch.setattr("oh_no_my_claudecode.cli.open_unit_pr", _fake_open, raising=False)
        # open_unit_pr is imported inside the command; patch the source instead.
        monkeypatch.setattr(
            "oh_no_my_claudecode.swarm.staff.open_unit_pr", _fake_open, raising=False
        )

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["swarm", "pr", "hh88", "unit-0000", "--worktree", str(tmp_path), "--json"],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["pr_url"] == "https://example/pr/1"


class _PassReport:
    """Minimal stand-in for PreflightReport (ok=True, empty steps)."""

    ok = True
    steps: list[object] = []
