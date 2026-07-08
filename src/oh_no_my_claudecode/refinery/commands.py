"""CLI surface for ``onmc refinery`` — Bors-style merge queue.

Auto-discovered by :mod:`oh_no_my_claudecode.command_registry`: exposes a
top-level ``register(app)`` callable so ``onmc refinery`` ships with
**zero edits** to ``cli.py`` or any other shared hub.

Sub-commands
------------
``onmc refinery add <pr> [--priority N]``
    Enqueue a PR (or update its priority if already queued).

``onmc refinery status [--json]``
    Show the current queue: positions, states, reasons.

``onmc refinery run [--max N] [--json]``
    Process the queue head(s): rebase → wait-green → merge.

``onmc refinery drop <pr>``
    Remove a PR from the queue.

``onmc refinery clear``
    Flush the entire queue.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.refinery.driver import ProcessResult, RealGh, process
from oh_no_my_claudecode.refinery.queue import (
    REFINERY_SUBDIR,
    active_entries,
    clear,
    drop,
    enqueue,
    load_queue,
    save_queue,
)

refinery_app = typer.Typer(
    help="Bors-style serialised merge queue: enqueue PRs, process one at a time.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_queue_dir() -> Path:
    """Resolve the .onmc/refinery directory from cwd."""
    from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root

    try:
        repo_root = discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("error: not inside a git repository.", err=True)
        raise typer.Exit(code=1) from None
    return repo_root / REFINERY_SUBDIR


def _state_badge(state: str) -> str:
    labels = {
        "queued": "[queued]",
        "testing": "[testing]",
        "merged": "[merged]",
        "kicked": "[kicked]",
    }
    return labels.get(state, f"[{state}]")


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


def register(app: typer.Typer) -> None:
    """Register the ``onmc refinery`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(refinery_app, name="refinery")


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------


@refinery_app.command("add")
def add_command(
    pr: Annotated[int, typer.Argument(help="PR number to enqueue.")],
    priority: Annotated[
        int,
        typer.Option("--priority", help="Queue priority (higher = processed first). Default 0."),
    ] = 0,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit result as a JSON object."),
    ] = False,
) -> None:
    """Enqueue a PR (or update its priority if already present).

    The queue is persisted to ``.onmc/refinery/queue.json``.

    Examples:

        onmc refinery add 123

        onmc refinery add 456 --priority 10
    """
    queue_dir = _resolve_queue_dir()
    queue = load_queue(queue_dir)
    was_present = any(e.pr == pr for e in queue.entries)
    queue = enqueue(queue, pr, priority=priority)
    save_queue(queue, queue_dir)

    active = active_entries(queue)
    position = next((i + 1 for i, e in enumerate(active) if e.pr == pr), None)

    if as_json:
        typer.echo(json.dumps({
            "kind": "refinery_add",
            "pr": pr,
            "priority": priority,
            "updated": was_present,
            "position": position,
        }))
    else:
        verb = "Updated" if was_present else "Enqueued"
        typer.echo(f"{verb} PR #{pr} (priority={priority}, position={position}).")


@refinery_app.command("status")
def status_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the queue as a JSON object."),
    ] = False,
) -> None:
    """Show the current merge queue.

    Displays each entry with its position, PR number, state, and kick reason
    (if applicable).

    Examples:

        onmc refinery status

        onmc refinery status --json
    """
    queue_dir = _resolve_queue_dir()
    queue = load_queue(queue_dir)

    entries = queue.entries
    if as_json:
        typer.echo(json.dumps({
            "kind": "refinery_status",
            "total": len(entries),
            "entries": [
                {
                    "pr": e.pr,
                    "priority": e.priority,
                    "state": e.state.value,
                    "reason": e.reason,
                    "enqueued_at": e.enqueued_at,
                }
                for e in entries
            ],
        }))
        return

    if not entries:
        typer.echo("Refinery queue is empty.")
        return

    active = active_entries(queue)
    typer.echo(f"Refinery queue — {len(active)} active, {len(entries)} total\n")
    for i, e in enumerate(entries, 1):
        badge = _state_badge(e.state.value)
        line = f"  {i:>3}. PR #{e.pr}  priority={e.priority}  {badge}"
        if e.reason:
            line += f"  reason: {e.reason}"
        typer.echo(line)


@refinery_app.command("run")
def run_command(
    max_n: Annotated[
        int,
        typer.Option("--max", help="Maximum number of PRs to process (default: 1)."),
    ] = 1,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit results as a JSON object."),
    ] = False,
) -> None:
    """Process the merge queue head(s).

    For each head PR: rebase onto main, wait for CI green (quality + CodeQL),
    then merge. Failed or conflicting PRs are kicked back with a reason and
    the next entry is processed.

    Examples:

        onmc refinery run

        onmc refinery run --max 3

        onmc refinery run --json
    """
    queue_dir = _resolve_queue_dir()
    queue = load_queue(queue_dir)
    if not active_entries(queue):
        if as_json:
            typer.echo(json.dumps({"kind": "refinery_run", "results": []}))
        else:
            typer.echo("Refinery queue is empty — nothing to process.")
        return

    gh = RealGh()
    results: list[ProcessResult] = process(queue, gh=gh, queue_dir=queue_dir, max_n=max_n)

    if as_json:
        typer.echo(json.dumps({
            "kind": "refinery_run",
            "results": [
                {
                    "pr": r.pr,
                    "action": r.action.value,
                    "success": r.success,
                    "reason": r.reason,
                }
                for r in results
            ],
        }))
        return

    if not results:
        typer.echo("No PRs were advanced (queue may be empty or all waiting).")
        return
    for r in results:
        status = "ok" if r.success else "failed"
        line = f"  PR #{r.pr}  action={r.action.value}  status={status}"
        if r.reason:
            line += f"  ({r.reason})"
        typer.echo(line)


@refinery_app.command("drop")
def drop_command(
    pr: Annotated[int, typer.Argument(help="PR number to remove from the queue.")],
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit result as a JSON object."),
    ] = False,
) -> None:
    """Remove a PR from the queue (any state).

    Examples:

        onmc refinery drop 123
    """
    queue_dir = _resolve_queue_dir()
    queue = load_queue(queue_dir)
    was_present = any(e.pr == pr for e in queue.entries)
    queue = drop(queue, pr)
    save_queue(queue, queue_dir)

    if as_json:
        typer.echo(json.dumps({"kind": "refinery_drop", "pr": pr, "was_present": was_present}))
    else:
        if was_present:
            typer.echo(f"Dropped PR #{pr} from the queue.")
        else:
            typer.echo(f"PR #{pr} was not in the queue.")


@refinery_app.command("clear")
def clear_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit result as a JSON object."),
    ] = False,
) -> None:
    """Flush the entire merge queue.

    Examples:

        onmc refinery clear
    """
    queue_dir = _resolve_queue_dir()
    queue = load_queue(queue_dir)
    count = len(queue.entries)
    queue = clear(queue)
    save_queue(queue, queue_dir)

    if as_json:
        typer.echo(json.dumps({"kind": "refinery_clear", "removed": count}))
    else:
        typer.echo(f"Queue cleared ({count} entries removed).")
