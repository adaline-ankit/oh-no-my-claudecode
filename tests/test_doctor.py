"""Tests for ``onmc doctor`` — integration health check.

Coverage (≥6 tests as required)
---------------------------------
1.  check_initialized() → ok when .onmc/memory.db present.
2.  check_initialized() → fail when .onmc/memory.db absent.
3.  check_initialized() → fail when repo_root is None.
4.  check_version() → ok with injectable version function.
5.  check_version() → fail when PackageNotFoundError is raised.
6.  check_on_path() → ok when which_fn returns a path.
7.  check_on_path() → warn when which_fn returns None.
8.  check_hooks() → ok when settings.json has all hooks (via install + check).
9.  check_hooks() → fail when settings.json absent.
10. check_mcp() → ok when .mcp.json registers onmc MCP server.
11. check_mcp() → fail when .mcp.json absent.
12. check_wrap() → ok with installed slash command + active state detail.
13. check_wrap() → fail when .claude/commands/onmc.md absent.
14. run_all_checks() → returns exactly 6 results with expected names.
15. ``onmc doctor --json`` emits {"kind":"doctor","checks":[...],"summary":{}}.
16. Exit code 1 on any fail, exit code 0 on no fails (warn only is fine).
17. Exit code 0 on all-warn (no failures).
"""

from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.doctor.checks import (
    CheckResult,
    check_hooks,
    check_initialized,
    check_mcp,
    check_on_path,
    check_version,
    check_wrap,
    run_all_checks,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path) -> Path:
    """Return a minimal fake repo root with a .git sentinel directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


# ---------------------------------------------------------------------------
# check_initialized (tests 1–3)
# ---------------------------------------------------------------------------


def test_check_initialized_ok(tmp_path: Path) -> None:
    """check_initialized returns ok when .onmc/memory.db exists."""
    repo = _make_repo(tmp_path)
    db = repo / ".onmc" / "memory.db"
    db.parent.mkdir(parents=True)
    db.touch()

    result = check_initialized(repo)

    assert result.status == "ok"
    assert result.fix is None
    assert "memory.db" in result.detail


def test_check_initialized_fail_missing_db(tmp_path: Path) -> None:
    """check_initialized returns fail when .onmc/memory.db is absent."""
    repo = _make_repo(tmp_path)

    result = check_initialized(repo)

    assert result.status == "fail"
    assert result.fix is not None
    assert "onmc init" in result.fix


def test_check_initialized_fail_no_repo() -> None:
    """check_initialized returns fail when repo_root is None."""
    result = check_initialized(None)

    assert result.status == "fail"
    assert result.fix is not None


# ---------------------------------------------------------------------------
# check_version (tests 4–5)
# ---------------------------------------------------------------------------


def test_check_version_ok() -> None:
    """check_version returns ok with injectable version function."""
    result = check_version(version_fn=lambda: "1.2.3")

    assert result.status == "ok"
    assert "1.2.3" in result.detail
    assert result.fix is None


def test_check_version_fail_not_found() -> None:
    """check_version returns fail when PackageNotFoundError is raised."""

    def _missing() -> str:
        raise importlib.metadata.PackageNotFoundError("oh-no-my-claudecode")

    result = check_version(version_fn=_missing)

    assert result.status == "fail"
    assert result.fix is not None


# ---------------------------------------------------------------------------
# check_on_path (tests 6–7)
# ---------------------------------------------------------------------------


def test_check_on_path_ok() -> None:
    """check_on_path returns ok when which_fn finds the binary."""
    result = check_on_path(which_fn=lambda _: "/usr/local/bin/onmc")

    assert result.status == "ok"
    assert result.fix is None
    assert "/usr/local/bin/onmc" in result.detail


def test_check_on_path_warn() -> None:
    """check_on_path returns warn (not fail) when which_fn returns None."""
    result = check_on_path(which_fn=lambda _: None)

    assert result.status == "warn"
    assert result.fix is not None


# ---------------------------------------------------------------------------
# check_hooks (tests 8–9)
# ---------------------------------------------------------------------------


def test_check_hooks_ok(tmp_path: Path) -> None:
    """check_hooks returns ok after install_claude_hooks writes settings.json."""
    from oh_no_my_claudecode.hooks.installer import install_claude_hooks

    repo = _make_repo(tmp_path)
    mcp_path = repo / ".mcp.json"
    install_claude_hooks(repo_root=repo, mcp_path=mcp_path)

    result = check_hooks(repo)

    assert result.status == "ok"
    assert result.fix is None


def test_check_hooks_warn_absent(tmp_path: Path) -> None:
    """check_hooks returns warn (not fail) when .claude/settings.json does not exist."""
    repo = _make_repo(tmp_path)

    result = check_hooks(repo)

    assert result.status == "warn"
    assert result.fix is not None
    assert "quickstart" in result.fix


# ---------------------------------------------------------------------------
# check_mcp (tests 10–11)
# ---------------------------------------------------------------------------


def test_check_mcp_ok(tmp_path: Path) -> None:
    """check_mcp returns ok after install_claude_hooks registers MCP server."""
    from oh_no_my_claudecode.hooks.installer import install_claude_hooks

    repo = _make_repo(tmp_path)
    mcp_path = repo / ".mcp.json"
    install_claude_hooks(repo_root=repo, register_mcp=True, mcp_path=mcp_path)

    result = check_mcp(repo)

    assert result.status == "ok"
    assert result.fix is None


def test_check_mcp_warn_absent(tmp_path: Path) -> None:
    """check_mcp returns warn (not fail) when .mcp.json does not exist."""
    repo = _make_repo(tmp_path)

    result = check_mcp(repo)

    assert result.status == "warn"
    assert result.fix is not None
    assert "plug claude-code" in result.fix


# ---------------------------------------------------------------------------
# check_wrap (tests 12–13)
# ---------------------------------------------------------------------------


def test_check_wrap_ok(tmp_path: Path) -> None:
    """check_wrap returns ok when .claude/commands/onmc.md is present."""
    repo = _make_repo(tmp_path)
    cmd_file = repo / ".claude" / "commands" / "onmc.md"
    cmd_file.parent.mkdir(parents=True)
    cmd_file.write_text("<!-- onmc wrap -->\n", encoding="utf-8")

    result = check_wrap(repo)

    assert result.status == "ok"
    assert result.fix is None
    assert "deep-wrap" in result.detail


def test_check_wrap_warn_absent(tmp_path: Path) -> None:
    """check_wrap returns warn (not fail) when .claude/commands/onmc.md is absent."""
    repo = _make_repo(tmp_path)

    result = check_wrap(repo)

    assert result.status == "warn"
    assert result.fix is not None
    assert "onmc wrap" in result.fix


# ---------------------------------------------------------------------------
# run_all_checks (test 14)
# ---------------------------------------------------------------------------


def test_run_all_checks_returns_six_results(tmp_path: Path) -> None:
    """run_all_checks returns exactly 6 CheckResult objects with expected names."""
    repo = _make_repo(tmp_path)
    results = run_all_checks(
        repo,
        version_fn=lambda: "0.0.0",
        which_fn=lambda _: None,
    )

    assert len(results) == 6  # noqa: PLR2004
    names = [r.name for r in results]
    assert names == ["initialized", "version", "on_path", "hooks", "mcp", "wrap"]
    for r in results:
        assert isinstance(r, CheckResult)
        assert r.status in ("ok", "warn", "fail")


# ---------------------------------------------------------------------------
# CLI: --json flag (test 15)
# ---------------------------------------------------------------------------


def test_doctor_json_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``onmc doctor --json`` emits the expected JSON envelope shape."""
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)

    runner = _cli_runner()
    result = runner.invoke(app, ["doctor", "--json"])

    # Output must be valid JSON regardless of exit code.
    payload = json.loads(result.output)
    assert payload["kind"] == "doctor"
    assert isinstance(payload["checks"], list)
    assert len(payload["checks"]) == 6  # noqa: PLR2004
    assert set(payload["summary"].keys()) == {"ok", "warn", "fail"}
    for check in payload["checks"]:
        assert "name" in check
        assert "status" in check
        assert "detail" in check
        assert "fix" in check  # value may be None


# ---------------------------------------------------------------------------
# CLI: exit codes (tests 16–17)
# ---------------------------------------------------------------------------


def test_doctor_exit_code_one_on_any_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exit code is 1 when at least one check fails."""
    import oh_no_my_claudecode.doctor.commands as cmd_mod

    _has_fail = [
        CheckResult(name="initialized", status="fail", detail="not found", fix="run onmc init"),
        *[
            CheckResult(name=n, status="ok", detail="fine", fix=None)
            for n in ("version", "on_path", "hooks", "mcp", "wrap")
        ],
    ]
    monkeypatch.setattr(cmd_mod, "run_all_checks", lambda *a, **kw: _has_fail)

    runner = _cli_runner()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1


def test_doctor_exit_code_zero_on_warns_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exit code is 0 when checks have only warn (no fail)."""
    import oh_no_my_claudecode.doctor.commands as cmd_mod

    _warns = [
        CheckResult(name=n, status="warn", detail="advisory", fix="do something")
        for n in ("initialized", "version", "on_path", "hooks", "mcp", "wrap")
    ]
    monkeypatch.setattr(cmd_mod, "run_all_checks", lambda *a, **kw: _warns)

    runner = _cli_runner()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
