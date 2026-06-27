"""CLI surface for the ``pack`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so the command ships with **zero edits**
to ``cli.py`` or any other shared hub. Rendering is done inline here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.pack.builder import DEFAULT_BUDGET, build_pack, render_pack_markdown


def register(app: typer.Typer) -> None:
    """Register the ``onmc pack`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("pack")
    def pack_command(
        goal: Annotated[
            str,
            typer.Argument(help="Goal or task description for the spawned agent."),
        ],
        budget: Annotated[
            int,
            typer.Option("--budget", min=400, help="Maximum markdown characters."),
        ] = DEFAULT_BUDGET,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the pack as JSON instead of markdown."),
        ] = False,
    ) -> None:
        """Build a per-task context pack: dead-ends, decisions, reuse, files.

        Composes recorded dead-ends + decisions with a tiny code-graph slice and
        reuse hints into a terse, deterministic, offline markdown brief for a
        spawned agent.
        """
        service = OnmcService(Path.cwd())
        try:
            repo_root, _config, storage = service._load_context()
        except FileNotFoundError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

        pack = build_pack(storage, repo_root, goal, budget=budget)

        if as_json:
            typer.echo(json.dumps(pack.to_dict(), indent=2, sort_keys=True))
            return
        typer.echo(render_pack_markdown(pack))
