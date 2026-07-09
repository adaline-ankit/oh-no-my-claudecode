"""CLI surface for the ``gateway`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): this module exposes a top-level
``register(app)`` that the registry invokes at CLI build time, so ``onmc
gateway`` ships with **zero edits** to ``cli.py`` or any shared hub.

The ``gateway`` group is the live front door of onmc's accountable agent
runtime — the brain a transport router (OpenClaw / Slack / Telegram / Claude
Code Channels) posts inbound messages to:

- ``serve``    — start the ``http.server`` gateway daemon (``--dry`` by default).
- ``simulate`` — run one message through the pure pipeline and print the
  decision as JSON (the offline-friendly way to see the gateway decide).
- ``health``   — print the health payload the daemon serves at ``GET /health``.

Every subcommand is a thin wrapper over the pure
:mod:`oh_no_my_claudecode.gateway.pipeline` / ``.server`` modules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root

gateway_app = typer.Typer(
    help="Accountable agent gateway: webhook -> mission-bridge -> trust decision.",
    no_args_is_help=True,
)


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
    """Register the ``onmc gateway`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(gateway_app, name="gateway")


@gateway_app.command("serve")
def gateway_serve_command(
    host: Annotated[
        str,
        typer.Option("--host", help="Bind address (use 0.0.0.0 to expose to the network)."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", help="TCP port to listen on."),
    ] = 8770,
    dry: Annotated[
        bool,
        typer.Option(
            "--dry/--no-dry",
            help="Dry mode: accept & decide but never spawn a live swarm (default).",
        ),
    ] = True,
) -> None:
    """Start the gateway HTTP daemon.

    Exposes two endpoints:

    \\b
    POST /webhook   ← {channel, user_id, text} → mission-bridge decision
    GET  /health    ← {ok, version}

    A transport router (OpenClaw / Slack / Telegram / Claude Code Channels)
    posts inbound chat here; the gateway authorizes the sender, parses the
    message, and returns whether it was denied / an action / ignored / accepted.

    Live swarm dispatch is an intentional follow-up: ``--dry`` (the default)
    decides everything but spawns nothing, so simply serving the daemon can
    never spend money or launch agents.
    """
    from oh_no_my_claudecode.gateway.server import GatewayServer

    repo_root = _repo_root()

    if dry:
        typer.echo(
            "onmc gateway: DRY mode — accepted missions are decided but not dispatched "
            "(live swarm dispatch is a follow-up).",
            err=True,
        )
    typer.echo(f"onmc gateway: listening on http://{host}:{port}", err=True)
    typer.echo("  POST /webhook   GET /health", err=True)
    typer.echo("Press Ctrl-C to stop.", err=True)

    with GatewayServer(repo_root, host=host, port=port) as srv:
        typer.echo(f"onmc gateway: ready on http://{host}:{srv.port}", err=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            typer.echo("\nonmc gateway: shutting down.", err=True)


@gateway_app.command("simulate")
def gateway_simulate_command(
    channel: Annotated[
        str,
        typer.Argument(help="Transport channel, e.g. slack / telegram / openclaw."),
    ],
    user_id: Annotated[
        str,
        typer.Argument(help="The transport's raw user id (scoped with the channel)."),
    ],
    text: Annotated[
        str,
        typer.Argument(help="The inbound chat message to route through the pipeline."),
    ],
    mention: Annotated[
        str,
        typer.Option("--mention", help="Bot handle to strip (e.g. @onmc)."),
    ] = "@onmc",
) -> None:
    """Run one message through the gateway pipeline and print the decision (JSON).

    Offline-friendly: reads only the mission allowlist, spawns nothing. Exits 1
    when the sender is denied so a script can branch on the outcome.
    """
    from oh_no_my_claudecode.gateway.pipeline import STATUS_DENIED, handle_inbound
    from oh_no_my_claudecode.gateway.server import _result_to_dict

    result = handle_inbound(
        _repo_root(),
        channel=channel,
        user_id=user_id,
        text=text,
        mention=mention,
    )
    typer.echo(json.dumps(_result_to_dict(result)))
    if result.status == STATUS_DENIED:
        raise typer.Exit(code=1)


@gateway_app.command("health")
def gateway_health_command() -> None:
    """Print the health payload the daemon serves at ``GET /health`` (JSON)."""
    from oh_no_my_claudecode.gateway.server import route

    _status, payload = route("GET", "/health", None, repo_root=_repo_root())
    typer.echo(json.dumps(payload))
