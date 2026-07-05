"""CLI surface for the ``whip`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc whip`` ships with **zero edits**
to ``cli.py`` or any other shared hub.

``onmc whip`` is a control surface for *steering* a running Claude Code agent
and recording *reward signals* (praise or correction).  State is stored in
``.onmc/whip/`` under the repository root:

- ``pending.jsonl`` — the directive queue (nudges + redirects).
- ``rewards.jsonl``  — the reward signal ledger (treats + cracks).

The reward ledger mirrors the flywheel receipt schema so future flywheel
analysis can consume reward signals alongside run receipts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.whip.steer import (
    WHIP_SUBDIR,
    clear,
    enqueue,
    pending,
    record_signal,
    tally,
)

whip_app = typer.Typer(
    help=(
        "Steer a running agent and record reward signals "
        "(the reins + whip control surface)."
    ),
    no_args_is_help=True,
)


def _resolve_whip_dir() -> Path:
    """Resolve the .onmc/whip directory from cwd, exiting cleanly if no repo."""
    try:
        repo_root = discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("Not inside a repository. Run from within your project.", err=True)
        raise typer.Exit(code=1) from None
    return repo_root / WHIP_SUBDIR


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def register(app: typer.Typer) -> None:
    """Register the ``onmc whip`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(whip_app, name="whip")


# ---------------------------------------------------------------------------
# Directive commands
# ---------------------------------------------------------------------------


@whip_app.command("nudge")
def nudge_command(
    msg: Annotated[str, typer.Argument(help="Gentle steering message to queue.")],
) -> None:
    """Queue a gentle steering directive for the running agent.

    The message is appended to ``.onmc/whip/pending.jsonl`` and delivered
    (in FIFO order, after any pending redirects) when the agent next calls
    ``onmc whip pending`` or ``onmc whip clear``.

    Examples:

        onmc whip nudge "prefer smaller functions"

        onmc whip nudge "add a docstring to each new public method"
    """
    whip_dir = _resolve_whip_dir()
    record = enqueue("nudge", msg, whip_dir=whip_dir, ts=_now_iso())
    typer.echo(f"Queued nudge: {record['msg']!r}  [{record['ts']}]")


@whip_app.command("redirect")
def redirect_command(
    msg: Annotated[str, typer.Argument(help="Hard course-correction message to queue.")],
) -> None:
    """Queue a hard course-correction directive for the running agent.

    Redirects have higher priority than nudges: ``onmc whip pending`` and
    ``onmc whip clear`` surface all redirects first (FIFO within the redirect
    group), then nudges (FIFO within the nudge group).

    Examples:

        onmc whip redirect "stop — revert the last edit, it breaks the API contract"

        onmc whip redirect "do NOT touch the migration files"
    """
    whip_dir = _resolve_whip_dir()
    record = enqueue("redirect", msg, whip_dir=whip_dir, ts=_now_iso())
    typer.echo(f"Queued redirect: {record['msg']!r}  [{record['ts']}]")


@whip_app.command("pending")
def pending_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit directives as a JSON envelope."),
    ] = False,
) -> None:
    """Show queued directives without consuming them.

    Directives are shown in priority order: redirects first, then nudges,
    each sub-group in FIFO insertion order.  This command is read-only;
    to consume-and-clear the queue use ``onmc whip clear``.

    Examples:

        onmc whip pending

        onmc whip pending --json
    """
    whip_dir = _resolve_whip_dir()
    items = pending(whip_dir=whip_dir)
    if as_json:
        typer.echo(json.dumps({"kind": "whip_pending", "directives": items}, indent=2))
        return
    if not items:
        typer.echo("No directives pending.")
        return
    for i, item in enumerate(items, 1):
        kind = item.get("kind", "?")
        msg_text = item.get("msg", "")
        ts_text = item.get("ts", "")
        typer.echo(f"[{i}] {kind:8s}  {msg_text}  ({ts_text})")


@whip_app.command("clear")
def clear_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit a JSON confirmation envelope."),
    ] = False,
) -> None:
    """Consume and discard all queued directives.

    After this call ``onmc whip pending`` will show an empty queue.  Use this
    to drain stale directives that are no longer relevant.

    Examples:

        onmc whip clear

        onmc whip clear --json
    """
    whip_dir = _resolve_whip_dir()
    count = clear(whip_dir=whip_dir)
    if as_json:
        typer.echo(json.dumps({"kind": "whip_clear", "discarded": count}, indent=2))
        return
    typer.echo(f"Cleared {count} directive(s).")


# ---------------------------------------------------------------------------
# Reward-signal commands
# ---------------------------------------------------------------------------


@whip_app.command("crack")
def crack_command(
    reason: Annotated[
        str,
        typer.Option("--reason", "-r", help="Optional rationale for the correction."),
    ] = "",
    goal: Annotated[
        str,
        typer.Option("--goal", help="Override the current goal label (default: 'current')."),
    ] = "current",
    agent: Annotated[
        str,
        typer.Option("--agent", help="Agent identifier (default: 'claude')."),
    ] = "claude",
) -> None:
    """Record a negative reward signal (correction) for the current agent run.

    Signals are appended to ``.onmc/whip/rewards.jsonl`` — a schema
    compatible with flywheel receipts so future analysis can learn from
    steering feedback alongside run outcomes.

    Examples:

        onmc whip crack

        onmc whip crack --reason "hallucinated an API that doesn't exist"

        onmc whip crack --goal "add timeout param" --agent my-swarm-unit
    """
    whip_dir = _resolve_whip_dir()
    record = record_signal(
        "crack", goal=goal, agent=agent, reason=reason, whip_dir=whip_dir, ts=_now_iso()
    )
    msg = f"Correction recorded for goal={record['goal']!r}"
    if reason:
        msg += f": {reason}"
    typer.echo(msg)


@whip_app.command("treat")
def treat_command(
    reason: Annotated[
        str,
        typer.Option("--reason", "-r", help="Optional rationale for the praise."),
    ] = "",
    goal: Annotated[
        str,
        typer.Option("--goal", help="Override the current goal label (default: 'current')."),
    ] = "current",
    agent: Annotated[
        str,
        typer.Option("--agent", help="Agent identifier (default: 'claude')."),
    ] = "claude",
) -> None:
    """Record a positive reward signal (praise) for the current agent run.

    Signals are appended to ``.onmc/whip/rewards.jsonl`` — a schema
    compatible with flywheel receipts so future analysis can learn from
    steering feedback alongside run outcomes.

    Examples:

        onmc whip treat

        onmc whip treat --reason "minimal diff, all tests green"

        onmc whip treat --goal "refactor parser" --agent my-swarm-unit
    """
    whip_dir = _resolve_whip_dir()
    record = record_signal(
        "treat", goal=goal, agent=agent, reason=reason, whip_dir=whip_dir, ts=_now_iso()
    )
    msg = f"Praise recorded for goal={record['goal']!r}"
    if reason:
        msg += f": {reason}"
    typer.echo(msg)


@whip_app.command("tally")
def tally_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the reward tally as a JSON envelope."),
    ] = False,
) -> None:
    """Show the reward signal tally (praises vs corrections per goal/agent).

    Aggregates all signals in ``.onmc/whip/rewards.jsonl`` and prints a
    summary table.  With ``--json``, emits a machine-readable envelope for
    pipeline composition or flywheel consumption.

    Examples:

        onmc whip tally

        onmc whip tally --json
    """
    whip_dir = _resolve_whip_dir()
    result = tally(whip_dir=whip_dir)
    if as_json:
        typer.echo(json.dumps({"kind": "whip_tally", "tally": result}, indent=2))
        return
    total = result["total"]
    if total == 0:
        typer.echo("No reward signals recorded yet.")
        return
    typer.echo(
        f"Reward tally  treats={result['treats']}  cracks={result['cracks']}  total={total}"
    )
    if result["by_goal"]:
        typer.echo("\nBy goal:")
        for goal_label, counts in sorted(result["by_goal"].items()):
            typer.echo(
                f"  {goal_label!r:40s}  treats={counts['treats']}  cracks={counts['cracks']}"
            )
    if result["by_agent"]:
        typer.echo("\nBy agent:")
        for agent_label, counts in sorted(result["by_agent"].items()):
            typer.echo(
                f"  {agent_label!r:20s}  treats={counts['treats']}  cracks={counts['cracks']}"
            )
