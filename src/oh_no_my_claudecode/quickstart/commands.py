"""CLI surface for ``onmc quickstart`` — auto-discovered.

Follows the auto-discovery convention: a top-level :func:`register` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time, so ``onmc quickstart`` ships with **zero edits** to
``cli.py`` or any other shared hub.

``onmc quickstart`` is a compatibility bootstrap. New users should run
``onmc setup``. This command remains callable for existing automation and
prints the same canonical ``setup -> run -> missioncontrol`` handoff.

Examples::

    onmc quickstart          # interactive (asks nothing by default)
    onmc quickstart --yes    # non-interactive / CI-safe
    onmc quickstart --json   # machine-readable envelope
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.quickstart.flow import QuickstartResult, StepResult, run_quickstart

# Status glyphs for the human-readable card.
_GLYPH: dict[str, str] = {
    "done": "✓",
    "skipped": "~",
    "error": "✗",
}

_STEP_LABELS: dict[str, str] = {
    "init": "memory",
    "plug": "hooks + MCP",
    "wrap": "/onmc",
}


def _render_card(result: QuickstartResult) -> None:
    """Print the friendly ready card to stdout."""
    all_ok = result.success

    typer.echo("")
    if all_ok:
        typer.echo("onmc quickstart complete — you are ready.")
    else:
        typer.echo("onmc quickstart finished with errors (see below).")
    typer.echo("")

    # Step status lines.
    for step in result.steps:
        glyph = _GLYPH.get(step.status, "?")
        label = _STEP_LABELS.get(step.name, step.name)
        typer.echo(f"  {glyph}  {label:<14}  {step.detail}")

    typer.echo("")
    typer.echo("Day-1 commands to try:")
    _descriptions: dict[str, str] = {
        'onmc run "your task"': "preview the canonical runtime contract",
        "onmc status": "check repository and ONMC readiness",
        "onmc missioncontrol": "inspect durable run and proof state",
        "onmc ui": "visual memory dashboard",
    }
    for cmd in result.day1_commands:
        desc = _descriptions.get(cmd, "")
        if desc:
            typer.echo(f"  {cmd:<38}  {desc}")
        else:
            typer.echo(f"  {cmd}")
    typer.echo("")


def _render_step(step: StepResult, *, verbose: bool = False) -> None:  # noqa: ARG001
    """Print a single step result line (used for streaming feedback)."""
    glyph = _GLYPH.get(step.status, "?")
    label = _STEP_LABELS.get(step.name, step.name)
    typer.echo(f"  {glyph}  {label:<14}  {step.detail}")


def register(app: typer.Typer) -> None:
    """Register the ``onmc quickstart`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("quickstart")
    def quickstart_command(
        yes: Annotated[
            bool,
            typer.Option(
                "--yes/--no-yes",
                "-y",
                help="Non-interactive mode — skip any prompts (CI-safe).",
            ),
        ] = False,
        as_json: Annotated[
            bool,
            typer.Option(
                "--json",
                help=(
                    "Emit a machine-readable JSON envelope "
                    '{"kind": "quickstart", "steps": [...], "day1_commands": [...]}'
                    " for pipeline composition."
                ),
            ),
        ] = False,
    ) -> None:
        """Compatibility bootstrap; prefer ``onmc setup`` for new repositories.

        Composes three steps in one idempotent command:

        1. **init**   — initialise the repo memory store (same as ``onmc setup``).
        2. **plug**   — install Claude Code hooks, MCP server, and /onmc slash commands
                       (same as ``onmc plug claude-code``).
        3. **wrap**   — install the deep-wrap control plane with default-active enabled
                       (same as ``onmc wrap --default-active``).

        Safe to re-run: each step reports ``already configured`` when already done.
        Afterward, use ``onmc run "your task"`` as the canonical task path.

        Examples:

            onmc quickstart              # run all three steps, show ready card

            onmc quickstart --yes        # non-interactive / CI

            onmc quickstart --json       # machine-readable output
        """
        try:
            repo_root = discover_repo_root(Path.cwd())
        except RepoDiscoveryError:
            typer.echo("error: not a git repository — run from inside your project.", err=True)
            raise typer.Exit(code=1) from None

        result = run_quickstart(repo_root)

        if as_json:
            typer.echo(json.dumps(result.to_dict(), indent=2))
        else:
            _render_card(result)

        if not result.success:
            raise typer.Exit(code=1)
