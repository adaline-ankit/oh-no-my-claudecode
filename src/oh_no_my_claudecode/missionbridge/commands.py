"""CLI surface for the ``missionbridge`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time.  No shared hub is touched.

Exposes a ``mission-bridge`` command group that turns a verified swarm run into
a chat experience — the offline-testable brain a gateway (Slack / Telegram /
Claude Code Channels) wires into:

- ``card``    — render a swarm's trust report for a channel (slack/telegram/plain)
- ``intake``  — normalize an inbound chat message into a mission goal + options
- ``approve`` — parse a chat reply (button callback or free text) into an action
- ``allow``   — manage the deny-by-default command allowlist

Every subcommand is a thin, deterministic wrapper over the pure bridge modules;
the live inbound-webhook wiring lives outside onmc.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.missionbridge.approve import parse_action
from oh_no_my_claudecode.missionbridge.auth import (
    add_identity,
    authorize,
    load_policy,
    remove_identity,
)
from oh_no_my_claudecode.missionbridge.card import (
    build_card,
    render_plain,
    render_slack_blocks,
    render_telegram,
)
from oh_no_my_claudecode.missionbridge.intake import parse_intake


def _repo_root() -> Path:
    """Resolve the onmc repo root from the cwd, or exit cleanly if outside one."""
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo(
            "Not inside an onmc repository (no repo root found). Run from your project.",
            err=True,
        )
        raise typer.Exit(code=1) from None


def register(app: typer.Typer) -> None:
    """Register the ``mission-bridge`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    bridge = typer.Typer(
        help="Turn a verified swarm run into a chat experience (card / intake / approve / allow).",
        no_args_is_help=True,
    )

    @bridge.command("card")
    def card_command(
        swarm_id: Annotated[
            str,
            typer.Argument(help="Swarm id to build the trust card for."),
        ],
        goal: Annotated[
            str,
            typer.Option("--goal", help="Optional mission goal for the card header."),
        ] = "",
        fmt: Annotated[
            str,
            typer.Option("--format", "-f", help="Render format: slack | telegram | plain."),
        ] = "plain",
    ) -> None:
        """Build a swarm's channel-agnostic trust card and render it.

        Reads the swarm manifest + tamper-evident receipts (read-only) and
        emits a card marking each unit VERIFIED or HELD, with honest cost.
        """
        card = build_card(_repo_root(), swarm_id, goal=goal)
        choice = fmt.lower()
        if choice == "slack":
            typer.echo(json.dumps(render_slack_blocks(card)))
        elif choice == "telegram":
            text, keyboard = render_telegram(card)
            typer.echo(json.dumps({"text": text, "inline_keyboard": keyboard}))
        elif choice == "plain":
            typer.echo(render_plain(card))
        else:
            typer.echo(f"Unknown --format {fmt!r} (expected slack | telegram | plain).", err=True)
            raise typer.Exit(code=1)

    @bridge.command("intake")
    def intake_command(
        message: Annotated[
            str,
            typer.Argument(help="Inbound chat message to normalize into a mission request."),
        ],
        mention: Annotated[
            str,
            typer.Option("--mention", help="Bot handle to strip (e.g. @onmc)."),
        ] = "@onmc",
    ) -> None:
        """Parse a chat message into a mission goal + optional concurrency/budget.

        Emits JSON; exits 1 with ``{"task": null}`` when there is no goal (empty
        or mention-only) so a gateway can ignore it.
        """
        task = parse_intake(message, mention=mention)
        if task is None:
            typer.echo(json.dumps({"task": None}))
            raise typer.Exit(code=1)
        typer.echo(json.dumps({"task": dataclasses.asdict(task)}))

    @bridge.command("approve")
    def approve_command(
        message: Annotated[
            str,
            typer.Argument(help="Chat reply or button callback_data to resolve."),
        ],
    ) -> None:
        """Resolve a chat reply into a structured approve action (JSON)."""
        action = parse_action(message)
        typer.echo(
            json.dumps(
                {
                    "kind": str(action.kind),
                    "unit_id": action.unit_id,
                    "raw": action.raw,
                }
            )
        )

    @bridge.command("allow")
    def allow_command(
        identity: Annotated[
            str | None,
            typer.Argument(help="Channel-scoped identity, e.g. slack:U123 or telegram:456."),
        ] = None,
        remove: Annotated[
            bool,
            typer.Option("--remove", help="Remove the identity instead of adding it."),
        ] = False,
        check: Annotated[
            str | None,
            typer.Option("--check", help="Test an identity against the allowlist and exit."),
        ] = None,
        as_list: Annotated[
            bool,
            typer.Option("--list", help="List the current allowlist and exit."),
        ] = False,
    ) -> None:
        """Manage the deny-by-default mission command allowlist.

        Identities are channel-scoped (``slack:U123``), so the same raw id on a
        different channel is a different principal.
        """
        root = _repo_root()

        if as_list:
            policy = load_policy(root)
            typer.echo(
                json.dumps(
                    {
                        "allowed": sorted(policy.allowed_identities),
                        "open_when_empty": policy.open_when_empty,
                    }
                )
            )
            return

        if check is not None:
            policy = load_policy(root)
            channel, _, user_id = check.partition(":")
            decision = authorize(policy, channel=channel, user_id=user_id)
            typer.echo(json.dumps({"allowed": decision.allowed, "reason": decision.reason}))
            if not decision.allowed:
                raise typer.Exit(code=1)
            return

        if identity is None:
            typer.echo("Provide an IDENTITY, or use --list / --check.", err=True)
            raise typer.Exit(code=1)

        path = remove_identity(root, identity) if remove else add_identity(root, identity)
        verb = "removed" if remove else "added"
        typer.echo(f"{verb} {identity} ({path})")

    app.add_typer(bridge, name="mission-bridge")
