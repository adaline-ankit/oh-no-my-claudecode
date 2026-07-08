"""Pure check logic for ``onmc doctor``.

Each function takes explicit path/callable arguments so tests can run
without a real Claude Code install or a live onmc binary.  No I/O is
hidden — filesystem reads are all performed here with defensive
exception handling that converts errors into ``fail`` / ``warn`` results.

Check catalogue
---------------
1. ``initialized`` — ``.onmc/memory.db`` present under repo root.
2. ``version``     — installed package version (info-level ok).
3. ``on_path``     — ``onmc`` binary visible on PATH.
4. ``hooks``       — project-scoped Claude Code hooks present in settings.json.
5. ``mcp``         — onmc MCP server registered in ``.mcp.json``.
6. ``wrap``        — ``/onmc`` slash command file present + deep-wrap state.
"""

from __future__ import annotations

import importlib.metadata
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

__all__ = [
    "CheckResult",
    "CheckStatus",
    "check_hooks",
    "check_initialized",
    "check_mcp",
    "check_on_path",
    "check_version",
    "check_wrap",
    "run_all_checks",
]

CheckStatus = Literal["ok", "warn", "fail"]

# Human-readable labels shown in the table.
CHECK_LABELS: dict[str, str] = {
    "initialized": "onmc initialized",
    "version": "version",
    "on_path": "onmc on PATH",
    "hooks": "hooks installed",
    "mcp": "MCP wired",
    "wrap": "/onmc wrap command",
}


@dataclass(frozen=True)
class CheckResult:
    """Result of a single doctor check."""

    name: str
    """Internal check identifier (matches CHECK_LABELS keys)."""
    status: CheckStatus
    """``"ok"``, ``"warn"``, or ``"fail"``."""
    detail: str
    """One-line human-readable message."""
    fix: str | None
    """Actionable fix hint, or ``None`` when the check passed."""

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "fix": self.fix,
        }


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------


def check_initialized(repo_root: Path | None) -> CheckResult:
    """Check 1: ``.onmc/memory.db`` present under *repo_root*.

    Returns ``fail`` when *repo_root* is ``None`` (not in a git repo) or the
    database file does not exist.
    """
    if repo_root is None:
        return CheckResult(
            name="initialized",
            status="fail",
            detail="not inside a git repository",
            fix="run from inside a git repo, then run `onmc init`",
        )
    db = repo_root / ".onmc" / "memory.db"
    try:
        exists = db.exists()
    except OSError:
        exists = False
    if exists:
        return CheckResult(
            name="initialized",
            status="ok",
            detail=str(db),
            fix=None,
        )
    return CheckResult(
        name="initialized",
        status="fail",
        detail=".onmc/memory.db not found",
        fix="run `onmc init`",
    )


def check_version(
    version_fn: Callable[[], str] | None = None,
) -> CheckResult:
    """Check 2: installed package version (always ``ok`` when found).

    *version_fn* is injectable for tests; defaults to
    ``importlib.metadata.version("oh-no-my-claudecode")``.
    """
    _fn: Callable[[], str] = version_fn if version_fn is not None else _default_version
    try:
        ver = _fn()
        return CheckResult(
            name="version",
            status="ok",
            detail=f"v{ver}",
            fix=None,
        )
    except importlib.metadata.PackageNotFoundError:
        return CheckResult(
            name="version",
            status="fail",
            detail="package oh-no-my-claudecode not found",
            fix=(
                "install via `pip install oh-no-my-claudecode`"
                " or `uv tool install oh-no-my-claudecode`"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="version",
            status="warn",
            detail=f"version lookup failed: {exc}",
            fix=None,
        )


def _default_version() -> str:
    return importlib.metadata.version("oh-no-my-claudecode")


def check_on_path(
    which_fn: Callable[[str], str | None] | None = None,
) -> CheckResult:
    """Check 3: ``onmc`` binary is visible on PATH.

    *which_fn* is injectable for tests; defaults to ``shutil.which``.
    Returns ``warn`` (not ``fail``) — the CLI still works via ``uv run``.
    """
    _which: Callable[[str], str | None] = which_fn if which_fn is not None else shutil.which
    found = _which("onmc")
    if found:
        return CheckResult(
            name="on_path",
            status="ok",
            detail=found,
            fix=None,
        )
    return CheckResult(
        name="on_path",
        status="warn",
        detail="onmc binary not found on PATH",
        fix="add uv tool bin to PATH (e.g. export PATH=\"$HOME/.local/bin:$PATH\")",
    )


def check_hooks(repo_root: Path | None) -> CheckResult:
    """Check 4: project-scoped Claude Code hooks present in settings.json.

    Returns ``warn`` (not ``fail``) when hooks are absent — the user may not
    have run ``onmc quickstart`` yet but onmc core features still work without
    hooks.  Returns ``fail`` only when there is no git repo to check at all.
    """
    if repo_root is None:
        return CheckResult(
            name="hooks",
            status="fail",
            detail="not inside a git repository",
            fix="run `onmc quickstart`",
        )
    settings_path = repo_root / ".claude" / "settings.json"
    try:
        from oh_no_my_claudecode.hooks.installer import hooks_installed

        ok = hooks_installed(settings_path=settings_path)
    except Exception:  # noqa: BLE001
        ok = False
    if ok:
        return CheckResult(
            name="hooks",
            status="ok",
            detail="all onmc hooks present in .claude/settings.json",
            fix=None,
        )
    if not settings_path.exists():
        detail = ".claude/settings.json not found"
    else:
        detail = "onmc hooks missing from .claude/settings.json"
    return CheckResult(
        name="hooks",
        status="warn",
        detail=detail,
        fix="run `onmc quickstart`",
    )


def check_mcp(repo_root: Path | None) -> CheckResult:
    """Check 5: onmc MCP server registered in ``.mcp.json``.

    Returns ``warn`` (not ``fail``) when MCP is absent — the MCP server is an
    optional integration and onmc core features work without it.  Returns
    ``fail`` only when there is no git repo to check at all.
    """
    if repo_root is None:
        return CheckResult(
            name="mcp",
            status="fail",
            detail="not inside a git repository",
            fix="run `onmc plug claude-code`",
        )
    mcp_path = repo_root / ".mcp.json"
    try:
        from oh_no_my_claudecode.hooks.installer import mcp_registered

        ok = mcp_registered(mcp_path=mcp_path)
    except Exception:  # noqa: BLE001
        ok = False
    if ok:
        return CheckResult(
            name="mcp",
            status="ok",
            detail="onmc MCP server registered in .mcp.json",
            fix=None,
        )
    if not mcp_path.exists():
        detail = ".mcp.json not found"
    else:
        detail = "onmc MCP server not registered in .mcp.json"
    return CheckResult(
        name="mcp",
        status="warn",
        detail=detail,
        fix="run `onmc plug claude-code`",
    )


def check_wrap(repo_root: Path | None) -> CheckResult:
    """Check 6: ``/onmc`` slash command file present + deep-wrap active state.

    Returns ``warn`` (not ``fail``) when the slash command is absent — the wrap
    layer is an optional deep-integration and core onmc features work without it.
    Returns ``fail`` only when there is no git repo to check at all.  When the
    file is present, returns ``ok`` (active/inactive state is informational only
    — toggling is intentional behaviour).
    """
    if repo_root is None:
        return CheckResult(
            name="wrap",
            status="fail",
            detail="not inside a git repository",
            fix="run `onmc wrap`",
        )
    command_file = repo_root / ".claude" / "commands" / "onmc.md"
    try:
        installed = command_file.exists()
    except OSError:
        installed = False
    if not installed:
        return CheckResult(
            name="wrap",
            status="warn",
            detail=".claude/commands/onmc.md not found",
            fix="run `onmc wrap`",
        )
    try:
        from oh_no_my_claudecode.wrap.session import is_active

        active = is_active(repo_root)
    except Exception:  # noqa: BLE001
        active = False
    state = "active" if active else "inactive"
    return CheckResult(
        name="wrap",
        status="ok",
        detail=f"/onmc command installed; deep-wrap {state}",
        fix=None,
    )


# ---------------------------------------------------------------------------
# Aggregate runner
# ---------------------------------------------------------------------------


def run_all_checks(
    repo_root: Path | None,
    *,
    version_fn: Callable[[], str] | None = None,
    which_fn: Callable[[str], str | None] | None = None,
) -> list[CheckResult]:
    """Run all six checks and return them in declaration order.

    All path-dependent checks receive *repo_root* directly.  Version and PATH
    checks accept optional injectable callables so tests can run offline.
    """
    return [
        check_initialized(repo_root),
        check_version(version_fn=version_fn),
        check_on_path(which_fn=which_fn),
        check_hooks(repo_root),
        check_mcp(repo_root),
        check_wrap(repo_root),
    ]
