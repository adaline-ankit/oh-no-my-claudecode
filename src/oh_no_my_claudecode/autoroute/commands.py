"""CLI surface for the ``autoroute`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time.  Rendering is inline (a local Rich line with a
plain-text fallback) — no shared rendering hub is touched.  Trajectories are
read via the flywheel's own loader; nothing in ``flywheel/`` is modified.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.autoroute.autoroute import Suggestion, suggest_from_repo
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root

autoroute_app = typer.Typer(
    name="autoroute",
    help="Apply flywheel learning: recommend the historically-best model for a goal.",
    no_args_is_help=True,
)


def _resolve_repo_root() -> Path:
    """Resolve the repo root from cwd, exiting cleanly if not in a repo.

    Mirrors the flywheel command's resolution so failure messages match the
    rest of the CLI.
    """
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("Not inside a repository. Run from within your project.", err=True)
        raise typer.Exit(code=1) from None


def _render_rich(suggestion: Suggestion) -> bool:
    """Render the suggestion as a Rich line; return False if Rich is unavailable."""
    try:
        from rich.console import Console
        from rich.text import Text
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        return False

    if suggestion.confidence >= 0.75:
        conf_style = "bold green"
    elif suggestion.confidence >= 0.4:
        conf_style = "yellow"
    else:
        conf_style = "dim"

    body = Text()
    body.append("autoroute → ", style="bold cyan")
    body.append(f"{suggestion.model}", style="bold")
    body.append(f"   confidence {suggestion.confidence:.0%}", style=conf_style)
    body.append(f"   [{suggestion.basis}]\n", style="dim")
    body.append(suggestion.rationale, style="italic")
    Console().print(body)
    return True


def _render_plain(suggestion: Suggestion) -> None:
    """Emit the suggestion as plain text (no Rich dependency)."""
    typer.echo(
        f"autoroute -> {suggestion.model}  "
        f"(confidence {suggestion.confidence:.0%})  [{suggestion.basis}]"
    )
    typer.echo(f"  {suggestion.rationale}")


@autoroute_app.command("suggest")
def suggest_command(
    goal: Annotated[
        str,
        typer.Argument(help="The goal/task to recommend a model for."),
    ],
    default: Annotated[
        str,
        typer.Option("--default", help="Model to fall back to when history is thin."),
    ] = "sonnet",
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the suggestion as JSON."),
    ] = False,
) -> None:
    """Recommend the historically-best model for GOAL from verified receipts.

    Deterministic and offline: reuses the flywheel's learned per-goal-keyword
    and overall verified-outcome stats to pick a model, with an honest
    confidence and basis.  With no receipts it returns the default model at
    confidence 0 (exit 0) — never fabricates a recommendation.
    """
    repo_root = _resolve_repo_root()
    suggestion = suggest_from_repo(repo_root, goal, default_model=default)
    if as_json:
        typer.echo(json.dumps(suggestion.to_dict()))
        return
    if not _render_rich(suggestion):
        _render_plain(suggestion)


def register(app: typer.Typer) -> None:
    """Register the ``autoroute`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(autoroute_app, name="autoroute")
