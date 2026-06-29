"""CLI surface for the ``mission`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc mission`` ships with **zero
edits** to ``cli.py`` or any other shared hub.  Rendering is done inline here.

``onmc mission "<goal>"`` composes the shipped engineering pipeline
(recall/guard → pack → codegraph → swarm plan) into one mission plan.  The
default is plan mode: a deterministic, offline dry-run that spawns no agents.
``--execute`` hands the plan to the swarm (materialising its manifest) but still
spawns nothing in this build.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.mission.pipeline import (
    DEFAULT_CONCURRENCY,
    render_mission_markdown,
    run_mission,
)
from oh_no_my_claudecode.pack.builder import DEFAULT_BUDGET


def register(app: typer.Typer) -> None:
    """Register the ``onmc mission`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("mission")
    def mission_command(
        goal: Annotated[
            str,
            typer.Argument(help="The mission goal — what you want done."),
        ],
        execute: Annotated[
            bool,
            typer.Option(
                "--execute",
                help="Hand the plan to the swarm (materialise its manifest). "
                "Default is plan mode: a safe, offline dry-run that spawns nothing.",
            ),
        ] = False,
        concurrency: Annotated[
            int,
            typer.Option("--concurrency", min=1, help="Advisory swarm fan-out width."),
        ] = DEFAULT_CONCURRENCY,
        budget: Annotated[
            int,
            typer.Option("--budget", min=400, help="Context-pack markdown character budget."),
        ] = DEFAULT_BUDGET,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the mission plan as JSON instead of markdown."),
        ] = False,
    ) -> None:
        """Run the engineering pipeline end-to-end into one mission plan.

        Composes recorded dead-ends (guard) + a deterministic context pack +
        the code-graph blast radius + the swarm units the mission would run.
        Plan mode (the default) is offline and deterministic and spawns no
        agents; ``--execute`` additionally allocates the swarm manifest.
        """
        service = OnmcService(Path.cwd())
        try:
            repo_root, _config, storage = service._load_context()
        except FileNotFoundError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

        plan = run_mission(
            storage,
            repo_root,
            goal,
            budget=budget,
            execute=execute,
            concurrency=concurrency,
        )

        if as_json:
            typer.echo(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
            return
        typer.echo(render_mission_markdown(plan))
