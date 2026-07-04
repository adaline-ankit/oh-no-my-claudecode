"""CLI surface for the ``missioncontrol`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time.  No shared hub is touched.

The command is strictly **read-only**: it resolves the repo's swarm base
(``.onmc/swarm``) the same way the swarm code does, reads the manifest +
receipts, and renders a live dashboard.  It never mutates swarm state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from rich.console import Console

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.missioncontrol.dashboard import (
    build_dashboard,
    list_swarm_ids,
    render_dashboard,
    render_swarm_list,
)


def _swarm_base() -> Path:
    """Resolve ``<repo>/.onmc/swarm`` from the current working directory.

    Mirrors how the swarm orchestrator anchors state.  Exits with a clear
    message (not a traceback) when not inside an onmc repo.
    """
    try:
        repo_root = discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo(
            "Not inside an onmc repository (no repo root found). Run from your project.",
            err=True,
        )
        raise typer.Exit(code=1) from None
    return repo_root / ".onmc" / "swarm"


def _console() -> Console:
    """Return a shared Rich Console (import lazily so tests can inject their own)."""
    from rich.console import Console

    return Console()


def register(app: typer.Typer) -> None:
    """Register the ``missioncontrol`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("missioncontrol")
    def missioncontrol_command(
        swarm_id: Annotated[
            str | None,
            typer.Argument(help="Swarm id to inspect. Omit with --all to list swarms."),
        ] = None,
        show_all: Annotated[
            bool,
            typer.Option("--all", help="List all swarms under .onmc/swarm and exit."),
        ] = False,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit machine-readable JSON instead of a table."),
        ] = False,
    ) -> None:
        """Live, read-only dashboard for an onmc swarm.

        Reads the swarm manifest + tamper-evident receipts and shows each unit's
        state (pending/queued/running/done/failed/aborted), whether a receipt
        exists, its verified flag and diff_sha, plus the abort-sentinel state.
        Never mutates swarm state.
        """
        base = _swarm_base()
        console = _console()

        if show_all:
            ids = list_swarm_ids(base)
            if as_json:
                typer.echo(json.dumps({"swarms": ids}))
                return
            render_swarm_list(ids, console)
            return

        if swarm_id is None:
            typer.echo(
                "Provide a SWARM_ID, or pass --all to list swarms.",
                err=True,
            )
            raise typer.Exit(code=1)

        model = build_dashboard(base, swarm_id)
        if as_json:
            typer.echo(json.dumps(model.to_dict()))
        else:
            render_dashboard(model, console)
        # A missing swarm is an error in BOTH modes: exit 1 so automation can
        # rely on the exit code regardless of --json (the JSON still carries
        # exists=false for callers that parse it).
        if not model.exists:
            raise typer.Exit(code=1)
