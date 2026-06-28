"""CLI surface for the ``mission`` feature — auto-discovered.

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
from oh_no_my_claudecode.mission.planner import MissionPlan, compile_mission
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
            typer.Argument(help="The mission goal / task description."),
        ],
        budget: Annotated[
            int,
            typer.Option("--budget", min=400, help="Context grounding budget (chars)."),
        ] = DEFAULT_BUDGET,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the mission plan as JSON."),
        ] = False,
    ) -> None:
        """Assemble a grounded mission plan: dead-ends, files, route, next command.

        One call composes onmc's shipped primitives — recall + guard (decisions
        and dead-ends), pack + codegraph (a tiny relevant file set), and route
        (recommended agent/model/strategy) — into a single MISSION PLAN plus the
        exact ``onmc swarm plan ...`` command to run next. Deterministic and
        offline; it PLANS the mission, it does not spawn agents.
        """
        service = OnmcService(Path.cwd())
        try:
            repo_root, _config, storage = service._load_context()  # noqa: SLF001
        except FileNotFoundError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

        plan = compile_mission(storage, repo_root, goal, budget=budget)

        if as_json:
            typer.echo(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
            return

        typer.echo(_render_plan(plan))


def _render_plan(plan: MissionPlan) -> str:
    """Render a :class:`MissionPlan` to a terse, legible briefing.

    Kept as a module-level pure function so it is unit-testable without Typer.
    """
    lines: list[str] = ["# Mission Plan", "", plan.brief, ""]

    lines.append("## Dead ends (do not retry)")
    if plan.dead_ends:
        lines.extend(
            f"- {title} — {why}" if why else f"- {title}"
            for title, why in plan.dead_ends
        )
    else:
        lines.append("_(none recorded)_")
    lines.append("")

    lines.append("## Context files")
    if plan.context_files:
        lines.extend(f"- {path}" for path in plan.context_files)
    else:
        lines.append("_(none)_")
    lines.append("")

    lines.append("## Recommended route")
    if plan.route is not None:
        r = plan.route
        lines.append(
            f"- agent=`{r.agent}` · model=`{r.model_tier}` · "
            f"strategy=`{r.strategy}` · gate=`{r.gate}`"
        )
        lines.append(f"- {r.rationale}")
    else:
        lines.append("_(none)_")
    lines.append("")

    lines.append("## Suggested units")
    if plan.suggested_units:
        lines.extend(f"{i}. {unit}" for i, unit in enumerate(plan.suggested_units, 1))
    else:
        lines.append("_(none)_")
    lines.append("")

    lines.append("## Run next")
    lines.append(f"    {plan.next_command}" if plan.next_command else "_(nothing to run)_")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"
