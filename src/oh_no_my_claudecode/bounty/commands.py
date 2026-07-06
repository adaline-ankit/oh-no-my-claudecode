"""CLI surface for the ``bounty`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc bounty`` ships with **zero
edits** to ``cli.py`` or any other shared hub.

``onmc bounty`` is a *stakes layer* for tasks: post a points wager on a task,
then collect (or forfeit) the payout when it is resolved.  State is stored in
``.onmc/bounty/`` under the repository root:

- ``bounties.json`` — the live board (all posted bounties + their status).
- ``ledger.jsonl``  — append-only claim ledger (one record per claim).

Payout formula: ``reward * multiplier`` where multiplier is 1/2/3 for
easy/med/hard.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.bounty.board import (
    BOUNTY_SUBDIR,
    DIFFICULTIES,
    STATUS_OPEN,
    balance,
    claim,
    forfeit,
    list_bounties,
    payout,
    post,
    total_pot,
)
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root

bounty_app = typer.Typer(
    help="Wager points on tasks — post bounties, claim payouts, track balance.",
    no_args_is_help=True,
)


def _resolve_bounty_dir() -> Path:
    """Resolve the .onmc/bounty directory from cwd, exiting cleanly if no repo."""
    try:
        repo_root = discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("Not inside a repository. Run from within your project.", err=True)
        raise typer.Exit(code=1) from None
    return repo_root / BOUNTY_SUBDIR


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def register(app: typer.Typer) -> None:
    """Register the ``onmc bounty`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(bounty_app, name="bounty")


# ---------------------------------------------------------------------------
# post
# ---------------------------------------------------------------------------


@bounty_app.command("post")
def post_command(
    task: Annotated[str, typer.Argument(help="Task description for the bounty.")],
    reward: Annotated[
        int,
        typer.Option("--reward", "-r", help="Base reward points to wager (> 0)."),
    ],
    difficulty: Annotated[
        str,
        typer.Option(
            "--difficulty",
            "-d",
            help="Difficulty multiplier: easy (1×), med (2×), hard (3×).",
        ),
    ] = "med",
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the new bounty as a JSON envelope."),
    ] = False,
) -> None:
    """Post a new bounty with a points wager on a task.

    The bounty is persisted to ``.onmc/bounty/bounties.json``.  Difficulty
    multiplies the payout: easy=1×, med=2×, hard=3×.

    Examples:

        onmc bounty post "fix the auth bug" --reward 50

        onmc bounty post "refactor the parser" --reward 100 --difficulty hard

        onmc bounty post "update README" --reward 20 --difficulty easy --json
    """
    if difficulty not in DIFFICULTIES:
        typer.echo(
            f"Error: --difficulty must be one of {list(DIFFICULTIES)}, "
            f"got {difficulty!r}.",
            err=True,
        )
        raise typer.Exit(code=1)
    if reward <= 0:
        typer.echo("Error: --reward must be > 0.", err=True)
        raise typer.Exit(code=1)

    bounty_dir = _resolve_bounty_dir()
    b = post(task, reward, difficulty, bounty_dir=bounty_dir, now_iso=_now_iso())
    computed = payout(reward, difficulty)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "kind": "bounty_posted",
                    "bounty": b.to_dict(),
                    "payout_if_claimed": computed,
                },
                indent=2,
            )
        )
        return

    typer.echo(
        f"Bounty posted  id={b.id}  reward={reward}  "
        f"difficulty={difficulty}  payout={computed}pts"
    )
    typer.echo(f"  Task: {task}")


# ---------------------------------------------------------------------------
# list / board
# ---------------------------------------------------------------------------


@bounty_app.command("list")
def list_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit open bounties as a JSON envelope."),
    ] = False,
) -> None:
    """List all open bounties and the total pot.

    Shows each open bounty with its id, reward, difficulty, payout, and task
    description.

    Examples:

        onmc bounty list

        onmc bounty list --json
    """
    bounty_dir = _resolve_bounty_dir()
    open_bounties = list_bounties(bounty_dir=bounty_dir, status=STATUS_OPEN)
    pot = total_pot(bounty_dir=bounty_dir)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "kind": "bounty_list",
                    "open": [b.to_dict() for b in open_bounties],
                    "total_pot": pot,
                },
                indent=2,
            )
        )
        return

    if not open_bounties:
        typer.echo("No open bounties.")
        return

    typer.echo(f"Open bounties  ({len(open_bounties)} total, pot={pot}pts)")
    typer.echo("")
    for b in open_bounties:
        computed = payout(b.reward, b.difficulty)
        typer.echo(
            f"  [{b.id}]  {computed:>5}pts  ({b.difficulty:4s})  {b.task}"
        )


@bounty_app.command("board")
def board_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the full board as a JSON envelope."),
    ] = False,
) -> None:
    """Show the full bounty board (open, claimed, and forfeited).

    Alias for ``onmc bounty list`` with all statuses visible.

    Examples:

        onmc bounty board

        onmc bounty board --json
    """
    bounty_dir = _resolve_bounty_dir()
    all_bounties = list_bounties(bounty_dir=bounty_dir)
    pot = total_pot(bounty_dir=bounty_dir)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "kind": "bounty_board",
                    "bounties": [b.to_dict() for b in all_bounties],
                    "total_pot": pot,
                },
                indent=2,
            )
        )
        return

    if not all_bounties:
        typer.echo("Bounty board is empty.")
        return

    open_count = sum(1 for b in all_bounties if b.status == STATUS_OPEN)
    typer.echo(
        f"Bounty board  ({len(all_bounties)} total, "
        f"{open_count} open, pot={pot}pts)"
    )
    typer.echo("")
    for b in all_bounties:
        computed = payout(b.reward, b.difficulty) if b.status == STATUS_OPEN else b.payout_awarded
        status_tag = b.status.upper()[:8]
        typer.echo(
            f"  [{b.id}]  {status_tag:8s}  {computed:>5}pts  "
            f"({b.difficulty:4s})  {b.task}"
        )


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------


@bounty_app.command("claim")
def claim_command(
    bounty_id: Annotated[str, typer.Argument(help="Bounty ID to claim.")],
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the claim result as a JSON envelope."),
    ] = False,
) -> None:
    """Claim a bounty — mark it resolved and award the payout.

    The payout is appended to ``.onmc/bounty/ledger.jsonl`` and the bounty
    status is updated to ``claimed``.

    Examples:

        onmc bounty claim abc123de

        onmc bounty claim abc123de --json
    """
    bounty_dir = _resolve_bounty_dir()
    try:
        b = claim(bounty_id, bounty_dir=bounty_dir, now_iso=_now_iso())
    except KeyError:
        typer.echo(f"Error: bounty {bounty_id!r} not found.", err=True)
        raise typer.Exit(code=1) from None
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    if as_json:
        typer.echo(
            json.dumps(
                {"kind": "bounty_claimed", "bounty": b.to_dict()},
                indent=2,
            )
        )
        return

    typer.echo(
        f"Bounty claimed!  id={b.id}  payout={b.payout_awarded}pts  task={b.task!r}"
    )


# ---------------------------------------------------------------------------
# forfeit
# ---------------------------------------------------------------------------


@bounty_app.command("forfeit")
def forfeit_command(
    bounty_id: Annotated[str, typer.Argument(help="Bounty ID to forfeit.")],
    reason: Annotated[
        str,
        typer.Option("--reason", "-r", help="Optional rationale for forfeiting."),
    ] = "",
) -> None:
    """Forfeit a bounty — close it unpaid.

    The bounty status is updated to ``forfeited`` with an optional reason.
    No payout is recorded.

    Examples:

        onmc bounty forfeit abc123de

        onmc bounty forfeit abc123de --reason "task no longer relevant"
    """
    bounty_dir = _resolve_bounty_dir()
    try:
        b = forfeit(bounty_id, bounty_dir=bounty_dir, now_iso=_now_iso(), reason=reason)
    except KeyError:
        typer.echo(f"Error: bounty {bounty_id!r} not found.", err=True)
        raise typer.Exit(code=1) from None
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    msg = f"Bounty forfeited  id={b.id}  task={b.task!r}"
    if reason:
        msg += f"  reason={reason!r}"
    typer.echo(msg)


# ---------------------------------------------------------------------------
# balance
# ---------------------------------------------------------------------------


@bounty_app.command("balance")
def balance_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the balance as a JSON envelope."),
    ] = False,
) -> None:
    """Show total points earned from claimed bounties.

    Sums all ``payout_awarded`` values in ``.onmc/bounty/ledger.jsonl``.

    Examples:

        onmc bounty balance

        onmc bounty balance --json
    """
    bounty_dir = _resolve_bounty_dir()
    total = balance(bounty_dir=bounty_dir)

    if as_json:
        typer.echo(
            json.dumps(
                {"kind": "bounty_balance", "total_earned": total},
                indent=2,
            )
        )
        return

    typer.echo(f"Balance: {total}pts earned from claimed bounties.")
