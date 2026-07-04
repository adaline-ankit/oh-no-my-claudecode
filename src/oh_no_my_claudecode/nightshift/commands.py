"""CLI surface for the ``nightshift`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): this module exposes a top-level
``register(app)`` that the registry invokes at CLI build time, so ``onmc
nightshift`` ships with **zero edits** to ``cli.py`` or any other shared hub.
Rendering is done inline via :func:`render_morning_digest`.

``onmc nightshift`` plans a bounded overnight swarm from a backlog of goals
(passed via repeated ``--goal`` or a ``--file``), honouring a ``--budget`` cap.
The default is dry-run (plan mode): it prints the
:class:`~oh_no_my_claudecode.nightshift.runner.NightshiftPlan` plus a sample
morning digest and spawns **nothing** — mirroring ``onmc mission``'s plan-mode
safety.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.nightshift.digest import render_morning_digest
from oh_no_my_claudecode.nightshift.runner import (
    DEFAULT_BUDGET,
    NightshiftSummary,
    plan_nightshift,
)


def _read_goals_file(path: Path) -> list[str]:
    """Read one goal per non-blank, non-comment line from *path*.

    Lines beginning with ``#`` (after stripping) are treated as comments and
    skipped.  A missing/unreadable file raises ``typer.Exit(1)`` with a message.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"Cannot read goals file {path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    goals: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        goals.append(stripped)
    return goals


def register(app: typer.Typer) -> None:
    """Register the ``onmc nightshift`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("nightshift")
    def nightshift_command(
        goal: Annotated[
            list[str] | None,
            typer.Option(
                "--goal",
                help="A backlog goal for the overnight swarm. Repeatable.",
            ),
        ] = None,
        file: Annotated[
            Path | None,
            typer.Option(
                "--file",
                help="Read backlog goals from a file (one per line, # comments ignored).",
            ),
        ] = None,
        budget: Annotated[
            int,
            typer.Option("--budget", help="Max swarm units to schedule overnight."),
        ] = DEFAULT_BUDGET,
        dry_run: Annotated[
            bool,
            typer.Option(
                "--dry-run/--no-dry-run",
                help="Plan only — spawn nothing (default). "
                "Print the plan + a sample morning digest.",
            ),
        ] = True,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the nightshift plan as JSON."),
        ] = False,
    ) -> None:
        """Plan a bounded, verified overnight swarm + preview the morning digest.

        Collects the backlog from repeated ``--goal`` and/or a ``--file``,
        de-duplicates and orders it deterministically, and truncates to
        ``--budget`` units. Dry-run (the default) is offline and spawns no
        agents: it prints the plan and a sample morning digest. Only ``--json``
        suppresses the digest, emitting the plan as JSON.
        """
        goals: list[str] = list(goal or [])
        if file is not None:
            goals.extend(_read_goals_file(file))

        if not goals:
            typer.echo(
                "No goals given. Pass --goal <goal> (repeatable) or --file <path>.",
                err=True,
            )
            raise typer.Exit(code=1)

        plan = plan_nightshift(goals, budget=budget)

        if as_json:
            typer.echo(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
            return

        if not dry_run:
            # Non-dry-run from the CLI still does NOT launch a process swarm here
            # (spawning is the model's job, driven from the emitted plan). It
            # simply omits the "dry-run" framing so scripts can gate on it.
            typer.echo(
                "nightshift: --no-dry-run planned the swarm but does not spawn "
                "agents from the CLI; drive the fan-out from this plan.",
                err=True,
            )

        # Render the plan itself as a morning-report preview, then a sample of
        # what the morning summary would look like once receipts come back.
        render_morning_digest(plan)
        sample = NightshiftSummary(
            verified=plan.scheduled_count,
            failed=0,
            total=plan.scheduled_count,
            results=[
                {"goal": unit.goal, "verified": True, "pr_url": None}
                for unit in plan.units
            ],
        )
        typer.echo("")
        typer.echo("Sample morning digest (illustrative — all-verified outcome):")
        render_morning_digest(sample)
