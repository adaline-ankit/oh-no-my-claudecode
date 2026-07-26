"""CLI surface for the canonical runtime's read-only Mission Control view.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time.  No shared hub is touched.

The default command replays ``onmc run`` events from the durable runtime store.
The previous swarm dashboard remains callable through ``--all`` or by passing a
swarm id that does not match a canonical run.
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
from oh_no_my_claudecode.missioncontrol.runtime import (
    RuntimeDashboard,
    build_runtime_dashboard,
    render_runtime_dashboard,
)


def _repo_root() -> Path:
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo(
            "Not inside an onmc repository (no repo root found). Run from your project.",
            err=True,
        )
        raise typer.Exit(code=1) from None


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
        run_or_swarm_id: Annotated[
            str | None,
            typer.Argument(
                help=(
                    "Canonical run id to inspect. Legacy swarm ids remain accepted "
                    "as an advanced compatibility view."
                )
            ),
        ] = None,
        show_all: Annotated[
            bool,
            typer.Option(
                "--all",
                help="Advanced: list legacy swarms under .onmc/swarm and exit.",
            ),
        ] = False,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit machine-readable JSON instead of a table."),
        ] = False,
    ) -> None:
        """Read-only progress and proof view over the canonical runtime.

        With no arguments, shows recent ``onmc run`` state reconstructed from
        append-only durable events. ``verified`` appears only when the matching
        tamper-evident harness receipt validates. Legacy swarm inspection remains
        available by id or with ``--all``.
        """
        repo_root = _repo_root()
        console = _console()

        if show_all:
            base = repo_root / ".onmc" / "swarm"
            ids = list_swarm_ids(base)
            if as_json:
                typer.echo(json.dumps({"swarms": ids}))
                return
            render_swarm_list(ids, console)
            return

        runtime = build_runtime_dashboard(repo_root)
        if run_or_swarm_id is None:
            if as_json:
                typer.echo(json.dumps(runtime.to_dict()))
            else:
                render_runtime_dashboard(runtime, console)
            return

        run = next((item for item in runtime.runs if item.run_id == run_or_swarm_id), None)
        if run is not None:
            selected = RuntimeDashboard(
                runs=(run,),
                corrupt_run_ids=(
                    (run.run_id,) if run.run_id in runtime.corrupt_run_ids else ()
                ),
            )
            if as_json:
                typer.echo(json.dumps(selected.to_dict()))
            else:
                render_runtime_dashboard(selected, console)
            return

        # Backward compatibility: an id that is not a canonical run is resolved
        # against the legacy swarm store.
        model = build_dashboard(repo_root / ".onmc" / "swarm", run_or_swarm_id)
        if as_json:
            typer.echo(json.dumps(model.to_dict()))
        else:
            render_dashboard(model, console)
        # A missing swarm is an error in BOTH modes: exit 1 so automation can
        # rely on the exit code regardless of --json (the JSON still carries
        # exists=false for callers that parse it).
        if not model.exists:
            raise typer.Exit(code=1)
