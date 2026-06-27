"""CLI surface for the ``route`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. Rendering is done inline here (a local Rich console
with a plain-text fallback) — the shared rendering hub is untouched, and the
routing logic is called directly from :mod:`oh_no_my_claudecode.route.router`.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from oh_no_my_claudecode.route.router import RouteDecision, route_task


def _render_plain(decision: RouteDecision) -> None:
    """Emit the decision as aligned ``key: value`` lines (no Rich dependency)."""
    rows = decision.to_dict()
    width = max(len(key) for key in rows)
    for key, value in rows.items():
        typer.echo(f"{key.rjust(width)} : {value}")


def _render_rich(decision: RouteDecision) -> bool:
    """Render the decision as a Rich table; return False if Rich is unavailable."""
    try:
        from rich.console import Console
        from rich.table import Table
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        return False

    table = Table(title="onmc route — decision", show_header=True)
    table.add_column("field", style="bold cyan", no_wrap=True)
    table.add_column("value", overflow="fold")
    for key, value in decision.to_dict().items():
        table.add_row(key, str(value))
    Console().print(table)
    return True


def register(app: typer.Typer) -> None:
    """Register the ``route`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("route")
    def route_command(
        task: Annotated[
            str,
            typer.Argument(help="The task description to route."),
        ],
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the decision as JSON."),
        ] = False,
    ) -> None:
        """Deterministically route a task to an agent/model/strategy/gate.

        Pure keyword/intent matching — no LLM call. The same task always yields
        the same decision.
        """
        decision = route_task(task)
        if as_json:
            typer.echo(json.dumps(decision.to_dict()))
            return
        if not _render_rich(decision):
            _render_plain(decision)
