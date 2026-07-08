"""Pure orchestration for ``onmc quickstart`` — zero side effects except through runners.

The ``run_quickstart`` function accepts injectable step-runners so tests can
assert ordering, idempotency, and error handling without touching the filesystem
or any Claude Code config.

Public API
----------
plan_quickstart()           → list[StepSpec]       ordered step descriptors
run_quickstart(root, ...)   → QuickstartResult     composed result with card
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

__all__ = [
    "DAY1_COMMANDS",
    "QuickstartResult",
    "StepResult",
    "StepSpec",
    "plan_quickstart",
    "run_quickstart",
]

# Day-1 commands shown on the ready card (order matters — shown top-to-bottom).
DAY1_COMMANDS: list[str] = [
    "/onmc",
    'onmc autopilot "your goal"',
    "onmc brief",
    "onmc ui",
]

# Type alias for a step runner callable.
StepRunner = Callable[[Path], "StepResult"]


@dataclass(slots=True)
class StepSpec:
    """Descriptor for a single quickstart step."""

    name: str
    label: str


@dataclass(slots=True)
class StepResult:
    """Outcome of running one quickstart step."""

    name: str
    status: Literal["done", "skipped", "error"]
    detail: str


@dataclass(slots=True)
class QuickstartResult:
    """Composed result of the full quickstart flow."""

    steps: list[StepResult]
    day1_commands: list[str] = field(default_factory=lambda: list(DAY1_COMMANDS))

    @property
    def success(self) -> bool:
        """Return True when no step ended in error."""
        return not any(s.status == "error" for s in self.steps)

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-compatible dict (onmc envelope)."""
        return {
            "kind": "quickstart",
            "steps": [
                {"name": s.name, "status": s.status, "detail": s.detail}
                for s in self.steps
            ],
            "day1_commands": self.day1_commands,
        }


def plan_quickstart() -> list[StepSpec]:
    """Return the ordered sequence of quickstart steps.

    The three steps mirror the three CLI commands that ``onmc quickstart``
    composes:

    - ``init``  — :func:`OnmcService.init_project` (same as ``onmc setup``).
    - ``plug``  — :func:`plug_target("claude-code")` (same as ``onmc plug claude-code``).
    - ``wrap``  — wrap hooks + state + slash command (same as ``onmc wrap --default-active``).
    """
    return [
        StepSpec(name="init", label="Initialize repo memory"),
        StepSpec(name="plug", label="Integrate Claude Code (hooks + MCP + slash commands)"),
        StepSpec(name="wrap", label="Activate control plane (default-active)"),
    ]


# ---------------------------------------------------------------------------
# Default step runners (real implementations)
# ---------------------------------------------------------------------------


def _default_init_runner(repo_root: Path) -> StepResult:
    """Initialize the onmc memory store for *repo_root*.

    Idempotent: returns ``"skipped"`` when ``.onmc/config.yaml`` already exists.
    Calls the same code path as ``onmc setup`` / ``onmc init``.
    """
    from oh_no_my_claudecode.config import config_exists  # noqa: PLC0415
    from oh_no_my_claudecode.core.service import OnmcService  # noqa: PLC0415

    if config_exists(repo_root):
        return StepResult(name="init", status="skipped", detail="already initialized")
    OnmcService(cwd=repo_root).init_project()
    return StepResult(name="init", status="done", detail="memory store created")


def _default_plug_runner(repo_root: Path) -> StepResult:
    """Install Claude Code hooks, MCP server, and slash commands.

    Idempotent: returns ``"skipped"`` when hooks + MCP are both present.
    Calls the same code path as ``onmc plug claude-code``.
    """
    from oh_no_my_claudecode.hooks.installer import (  # noqa: PLC0415
        hooks_installed,
        mcp_config_path,
        mcp_registered,
        project_settings_path,
    )
    from oh_no_my_claudecode.integrations.plug import plug_target  # noqa: PLC0415

    sp = project_settings_path(repo_root)
    mp = mcp_config_path(repo_root)
    if sp.exists() and hooks_installed(settings_path=sp) and mcp_registered(mcp_path=mp):
        return StepResult(
            name="plug",
            status="skipped",
            detail="hooks + MCP already configured",
        )
    plug_target("claude-code", repo_root=repo_root)
    return StepResult(
        name="plug",
        status="done",
        detail="hooks + MCP + slash commands installed",
    )


def _default_wrap_runner(repo_root: Path) -> StepResult:
    """Install the onmc wrap control plane and activate it by default.

    Idempotent: returns ``"skipped"`` when ``.onmc/wrap.json`` already exists.
    Calls the same code path as ``onmc wrap --default-active``.
    """
    from oh_no_my_claudecode.hooks.installer import (  # noqa: PLC0415
        install_wrap_hooks,
        project_settings_backup_path,
        project_settings_path,
    )
    from oh_no_my_claudecode.wrap.state import (  # noqa: PLC0415
        upsert_claude_md_stanza,
        wrap_state_path,
        write_wrap_state,
    )

    if wrap_state_path(repo_root).is_file():
        return StepResult(name="wrap", status="skipped", detail="already configured")

    settings_path = project_settings_path(repo_root)
    backup_path = project_settings_backup_path(repo_root)
    install_wrap_hooks(
        repo_root=repo_root,
        strict=True,
        settings_path=settings_path,
        backup_path=backup_path,
    )
    write_wrap_state(repo_root, strict=True, default_active=True)
    upsert_claude_md_stanza(repo_root)
    # Install the /onmc slash command (same as wrap_callback does).
    _install_slash_command(repo_root)
    return StepResult(
        name="wrap",
        status="done",
        detail="/onmc slash command + wrap hooks installed (default-active)",
    )


def _install_slash_command(repo_root: Path) -> None:
    """Write the /onmc Claude Code slash command file.

    Delegates to ``wrap.commands._write_slash_command`` — the same private
    helper the ``onmc wrap`` callback calls — so the command body stays in
    one canonical place.
    """
    from oh_no_my_claudecode.wrap import commands as _wrap_cmds  # noqa: PLC0415

    _wrap_cmds._write_slash_command(repo_root)  # noqa: SLF001


def _make_default_runners() -> dict[str, StepRunner]:
    return {
        "init": _default_init_runner,
        "plug": _default_plug_runner,
        "wrap": _default_wrap_runner,
    }


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------


def run_quickstart(
    repo_root: Path,
    *,
    runners: dict[str, StepRunner] | None = None,
) -> QuickstartResult:
    """Run the quickstart flow against *repo_root*.

    Each step is executed via its *runner* callable — replace with fakes in
    tests to avoid any filesystem writes or real config mutations.  A runner
    that raises is caught: the step is recorded as ``"error"`` and execution
    continues so callers always receive a full result.

    Parameters
    ----------
    repo_root:
        Absolute path to the git repository root.
    runners:
        Optional mapping of step name → runner.  Missing keys fall back to
        the real default implementations.  Pass a complete dict in tests to
        fully isolate from the filesystem.
    """
    effective: dict[str, StepRunner] = _make_default_runners()
    if runners is not None:
        effective.update(runners)

    specs = plan_quickstart()
    results: list[StepResult] = []
    for spec in specs:
        runner = effective.get(spec.name)
        if runner is None:  # pragma: no cover — only reachable if plan_quickstart() is extended
            results.append(
                StepResult(name=spec.name, status="error", detail="no runner registered")
            )
            continue
        try:
            results.append(runner(repo_root))
        except Exception as exc:  # noqa: BLE001
            results.append(StepResult(name=spec.name, status="error", detail=str(exc)))

    return QuickstartResult(steps=results)
