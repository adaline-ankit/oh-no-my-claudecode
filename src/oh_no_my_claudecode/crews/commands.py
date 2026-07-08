"""CLI surface for the ``crews`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc crews`` ships with **zero edits**
to ``cli.py`` or any other shared hub.

Subcommands
-----------
``onmc crews export <plan> [--json] [--out FILE]``
    Convert an onmc mission plan or swarm manifest JSON file into a portable
    CrewAI crew specification.  Pure — always works, no crewai needed.

``onmc crews run <spec> [--json]``
    Execute a crew specification JSON file using the crewai backend, wrapping
    the result in an onmc accountability receipt.  Requires the ``[crewai]``
    extra.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.crews.interop import (
    crewai_available,
    plan_to_crew_spec,
    run_crew,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json_file(path: Path) -> dict[str, Any]:
    """Load a JSON file and return its contents as a dict.

    Exits with code 1 and a clear error message on read or parse failure.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"error: cannot read {path}: {exc}", err=True)
        raise typer.Exit(code=1) from None
    try:
        data: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        typer.echo(f"error: {path} is not valid JSON: {exc}", err=True)
        raise typer.Exit(code=1) from None
    if not isinstance(data, dict):
        typer.echo(f"error: {path} must contain a JSON object, got {type(data).__name__}", err=True)
        raise typer.Exit(code=1) from None
    return data


def _write_or_print(payload: str, out: Path | None) -> None:
    """Write *payload* to *out* (file) or stdout."""
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        typer.echo(f"written to {out}", err=True)
    else:
        typer.echo(payload)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(app: typer.Typer) -> None:
    """Register the ``onmc crews`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    crews_app = typer.Typer(
        help=(
            "Optional CrewAI interop: export an onmc plan as a crew spec (pure, "
            "no extras needed) or run a crew spec under an onmc receipt "
            "(requires the [crewai] extra)."
        ),
        no_args_is_help=True,
    )

    @crews_app.command("export")
    def export_command(
        plan: Annotated[
            Path,
            typer.Argument(
                help=(
                    "Path to an onmc mission-plan JSON file "
                    "(MissionPlan.to_dict() shape) or a swarm manifest."
                ),
                metavar="PLAN",
            ),
        ],
        out: Annotated[
            Path | None,
            typer.Option(
                "--out",
                help="Write the crew spec to FILE instead of stdout.",
                metavar="FILE",
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option(
                "--json",
                help=(
                    "Wrap the crew spec in an onmc JSON envelope "
                    '{"kind": "crews_export", "spec": {...}} for pipeline composition.'
                ),
            ),
        ] = False,
    ) -> None:
        """Export an onmc plan or swarm manifest as a CrewAI crew specification.

        Pure operation — no crewai installation required.  The output is a
        portable JSON dict describing agents and tasks that can be passed to
        ``onmc crews run`` or used directly with the crewai library.

        Examples:

            onmc crews export mission_plan.json

            onmc crews export swarm_manifest.json --out crew.json

            onmc crews export plan.json --json
        """
        plan_data = _load_json_file(plan)
        spec = plan_to_crew_spec(plan_data)

        if as_json:
            payload = json.dumps({"kind": "crews_export", "spec": spec}, indent=2)
        else:
            payload = json.dumps(spec, indent=2)

        _write_or_print(payload, out)

    @crews_app.command("run")
    def run_command(
        spec: Annotated[
            Path,
            typer.Argument(
                help="Path to a crew specification JSON file (output of 'onmc crews export').",
                metavar="SPEC",
            ),
        ],
        as_json: Annotated[
            bool,
            typer.Option(
                "--json",
                help="Emit the run receipt as JSON instead of a human-readable summary.",
            ),
        ] = False,
    ) -> None:
        """Run a crew specification using the crewai backend under an onmc receipt.

        Requires the ``[crewai]`` optional extra::

            pip install "oh-no-my-claudecode[crewai]"

        The run result is wrapped in an onmc accountability receipt (goal,
        outcome, agent count, timestamps, onmc version).

        Examples:

            onmc crews run crew.json

            onmc crews run crew.json --json
        """
        if not crewai_available():
            typer.echo(
                "error: crewai is not installed.\n"
                "Install the optional extra: "
                "pip install 'oh-no-my-claudecode[crewai]'",
                err=True,
            )
            raise typer.Exit(code=1)

        spec_data = _load_json_file(spec)

        try:
            receipt = run_crew(spec_data)
        except RuntimeError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from None
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"error: crew run failed: {exc}", err=True)
            raise typer.Exit(code=1) from None

        if as_json:
            typer.echo(json.dumps(receipt.to_dict(), indent=2))
        else:
            typer.echo("crew run complete")
            typer.echo(f"  spec_hash : {receipt.spec_hash}")
            typer.echo(f"  goal      : {receipt.goal[:80]}")
            typer.echo(f"  agents    : {receipt.agent_count}")
            typer.echo(f"  tasks     : {receipt.task_count}")
            typer.echo(f"  outcome   : {receipt.outcome[:120]}")
            typer.echo(f"  started   : {receipt.started_at}")
            typer.echo(f"  ended     : {receipt.ended_at}")

    app.add_typer(crews_app, name="crews")
