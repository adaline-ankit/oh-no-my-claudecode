"""CLI surface for ``onmc teams`` — auto-discovered AutoGen interop.

Follows the auto-discovery convention: exposes ``register(app)`` so zero edits
are needed in ``cli.py`` or any other shared hub.

Sub-commands
------------
``onmc teams export <PLAN>``
    Convert an onmc mission/swarm plan JSON file (or ``-`` for stdin) into a
    portable AutoGen team/GroupChat specification.  Pure — no autogen needed.
    Supports ``--json`` (onmc envelope) and ``--out FILE``.

``onmc teams run <SPEC>``
    Execute an AutoGen team spec file and wrap the run under an onmc receipt.
    Requires the ``[autogen]`` extra.  Errors cleanly when absent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.teams.interop import (
    autogen_available,
    autogen_runner,
    plan_to_team_spec,
    run_team,
)

# ---------------------------------------------------------------------------
# Sub-app
# ---------------------------------------------------------------------------

_teams_app = typer.Typer(
    name="teams",
    help=(
        "AutoGen / AG2 interop — export onmc plans as team specs and run them "
        "under onmc receipts.  The ``export`` command is always available; "
        "``run`` requires the ``[autogen]`` extra."
    ),
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Register ``onmc teams`` onto the root app.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(_teams_app, name="teams")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@_teams_app.command("export")
def export_command(
    plan: Annotated[
        str,
        typer.Argument(
            metavar="PLAN",
            help=(
                "Path to an onmc mission/swarm plan JSON file, "
                "or ``-`` to read from stdin."
            ),
        ),
    ],
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            metavar="FILE",
            help="Write the team spec to FILE instead of stdout.",
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                'Wrap in an onmc envelope {"kind": "autogen-team", "spec": {...}} '
                "for pipeline composition."
            ),
        ),
    ] = False,
) -> None:
    """Convert an onmc plan to an AutoGen team/GroupChat specification.

    Reads a JSON plan produced by ``onmc mission --json`` (or any swarm plan)
    and emits a portable AutoGen GroupChat spec.  Pure — no autogen installation
    needed.

    Examples:

        onmc teams export mission.json

        onmc teams export mission.json --json

        onmc teams export mission.json --out team.json

        onmc mission --json | onmc teams export -
    """
    # Read plan JSON.
    try:
        raw = (
            sys.stdin.read()
            if plan == "-"
            else Path(plan).read_text(encoding="utf-8")
        )
    except (OSError, IsADirectoryError) as exc:
        typer.echo(f"error: cannot read plan: {exc}", err=True)
        raise typer.Exit(code=1) from None

    try:
        plan_dict = json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.echo(f"error: invalid JSON in plan: {exc}", err=True)
        raise typer.Exit(code=1) from None

    spec = plan_to_team_spec(plan_dict)

    if as_json:
        payload = json.dumps(
            {"kind": "autogen-team", "spec": spec}, indent=2, sort_keys=True
        )
    else:
        payload = json.dumps(spec, indent=2, sort_keys=True)

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        typer.echo(f"team spec written to {out}", err=True)
    else:
        typer.echo(payload)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@_teams_app.command("run")
def run_command(
    spec_path: Annotated[
        Path,
        typer.Argument(
            metavar="SPEC",
            help="Path to an AutoGen team spec JSON file (from ``onmc teams export``).",
        ),
    ],
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit a JSON receipt envelope instead of a human-readable summary."
            ),
        ),
    ] = False,
) -> None:
    """Run an AutoGen team spec under an onmc receipt.

    Executes the team described in SPEC using pyautogen / ag2 and records a
    tamper-evident onmc receipt.  Requires the ``[autogen]`` optional extra:

        pip install 'oh-no-my-claudecode[autogen]'

    Examples:

        onmc teams run team.json

        onmc teams run team.json --json
    """
    if not autogen_available():
        typer.echo(
            "error: the [autogen] extra is required.  "
            "Install with: pip install 'oh-no-my-claudecode[autogen]'",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        raw = spec_path.read_text(encoding="utf-8")
    except (OSError, IsADirectoryError) as exc:
        typer.echo(f"error: cannot read spec: {exc}", err=True)
        raise typer.Exit(code=1) from None

    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.echo(f"error: invalid JSON in spec: {exc}", err=True)
        raise typer.Exit(code=1) from None

    outcome = run_team(spec, runner=autogen_runner)

    if as_json:
        typer.echo(json.dumps(outcome, indent=2, sort_keys=True))
    else:
        typer.echo(f"status:       {outcome['status']}")
        typer.echo(f"receipt_path: {outcome['receipt_path']}")
