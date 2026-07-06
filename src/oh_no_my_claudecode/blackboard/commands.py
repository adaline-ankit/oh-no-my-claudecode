"""CLI surface for the ``blackboard`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. No shared hub is touched.

Adds a Typer sub-group ``onmc blackboard`` with two commands:

- ``post``  — append one entry to a swarm's board.
- ``show``  — render the board (or filter/dump it as JSON).

Swarm-dir resolution mirrors ``missioncontrol``: the swarm base is
``<repo>/.onmc/swarm``, and when no ``swarm-id`` is given the most recently
modified swarm directory (via
:func:`oh_no_my_claudecode.missioncontrol.dashboard.list_swarm_ids`) is used.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.blackboard.blackboard import (
    VALID_KINDS,
    BoardEntry,
    InvalidEntryError,
    append_entry,
    filter_entries,
    read_board,
    render_board,
)
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.missioncontrol.dashboard import list_swarm_ids

blackboard_app = typer.Typer(
    name="blackboard",
    help="Shared-memory coordination board for a swarm — post and read findings/claims/warnings.",
    no_args_is_help=True,
)


def _swarm_base() -> Path:
    """Resolve ``<repo>/.onmc/swarm`` from the current working directory.

    Mirrors ``missioncontrol``'s ``_swarm_base`` so failure messages and
    resolution behaviour match the rest of the CLI.
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


def _most_recent_swarm_id(base: Path) -> str | None:
    """Return the most recently modified swarm id under *base*, or ``None``.

    "Most recent" is the swarm directory with the newest mtime among those
    :func:`list_swarm_ids` recognises (i.e. has a ``manifest.json``) — the
    same set missioncontrol's ``--all`` would list.
    """
    ids = list_swarm_ids(base)
    if not ids:
        return None
    return max(ids, key=lambda sid: (base / sid).stat().st_mtime)


def _resolve_swarm_id(base: Path, swarm_id: str | None) -> str:
    """Resolve an explicit *swarm_id*, or fall back to the most recent swarm.

    Exits with a clear message (not a traceback) when no swarm-id is given
    and none can be found.
    """
    if swarm_id is not None:
        return swarm_id
    resolved = _most_recent_swarm_id(base)
    if resolved is None:
        typer.echo(
            "No swarms found under .onmc/swarm. Provide a SWARM_ID or run a swarm first.",
            err=True,
        )
        raise typer.Exit(code=1)
    return resolved


def _board_path(base: Path, swarm_id: str) -> Path:
    return base / swarm_id / "blackboard.jsonl"


@blackboard_app.command("post")
def post_command(
    swarm_id: Annotated[str, typer.Argument(help="Swarm id to post to.")],
    note: Annotated[str, typer.Option("--note", help="The note text to post.")],
    unit: Annotated[
        str,
        typer.Option("--unit", help="Posting unit id (or a human handle)."),
    ] = "human",
    kind: Annotated[
        str,
        typer.Option(
            "--kind",
            help=f"Entry kind: one of {', '.join(VALID_KINDS)}.",
        ),
    ] = "finding",
) -> None:
    """Append one entry to a swarm's blackboard.

    The board is append-only: this never rewrites or removes prior entries.
    """
    base = _swarm_base()
    entry = BoardEntry(ts=time.time(), unit_id=unit, kind=kind, note=note)
    try:
        append_entry(_board_path(base, swarm_id), entry)
    except InvalidEntryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"posted to {swarm_id}: [{kind}] {note}")


@blackboard_app.command("show")
def show_command(
    swarm_id: Annotated[
        str | None,
        typer.Argument(help="Swarm id to show. Omit to use the most recently modified swarm."),
    ] = None,
    kind: Annotated[
        str | None,
        typer.Option("--kind", help=f"Filter to one kind: one of {', '.join(VALID_KINDS)}."),
    ] = None,
    unit: Annotated[
        str | None,
        typer.Option("--unit", help="Filter to entries posted by this unit id."),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the raw entries as JSON instead of a rendered board."),
    ] = False,
) -> None:
    """Render a swarm's blackboard in post order.

    Shows a small header (entry count, distinct units) followed by one line
    per entry: timestamp · unit · kind · note. An empty or missing board
    prints an honest empty-state message rather than an error.
    """
    base = _swarm_base()
    resolved_id = _resolve_swarm_id(base, swarm_id)
    entries = read_board(_board_path(base, resolved_id))
    entries = filter_entries(entries, kind=kind, unit_id=unit)

    if as_json:
        typer.echo(json.dumps([e.to_dict() for e in entries]))
        return
    typer.echo(render_board(entries))


def register(app: typer.Typer) -> None:
    """Register the ``blackboard`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(blackboard_app, name="blackboard")
