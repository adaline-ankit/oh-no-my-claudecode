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
from oh_no_my_claudecode.pack.readiness import brain_readiness_warnings


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
        strict: Annotated[
            bool,
            typer.Option(
                "--strict",
                help=(
                    "Refuse to build the pack when the brain is unready "
                    "(never ingested or repo-file index empty). "
                    "Without --strict a warning is printed to stderr and the "
                    "pack proceeds (possibly unreliable)."
                ),
            ),
        ] = False,
    ) -> None:
        """Build a per-task context pack: dead-ends, decisions, reuse, files.

        Composes recorded dead-ends + decisions with a tiny code-graph slice and
        reuse hints into a terse, deterministic, offline markdown brief for a
        spawned agent.

        Explicit file paths named in the goal are force-included first so the
        agent always starts with the exact files it was told to edit.
        """
        service = OnmcService(Path.cwd())
        try:
            repo_root, _config, storage = service._load_context()
        except FileNotFoundError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

        warnings = brain_readiness_warnings(storage)
        if warnings:
            typer.echo(
                "WARNING: brain may be unready — context pack could be unreliable.", err=True
            )
            for w in warnings:
                typer.echo(f"  • {w}", err=True)
            if strict:
                typer.echo(
                    "Refusing to build pack (--strict). Run `onmc ingest` then retry.",
                    err=True,
                )
                raise typer.Exit(code=1)

        pack = build_pack(storage, repo_root, goal, budget=budget)

        if as_json:
            typer.echo(json.dumps(pack.to_dict(), indent=2, sort_keys=True))
            return
        typer.echo(render_pack_markdown(pack))
