"""CLI surface for the ``connect`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): this module exposes a top-level
``register(app)`` the registry invokes at CLI build time, so ``onmc connect``
ships with **zero edits** to ``cli.py``.

``connect`` is the bidirectional ecosystem bridge — it plugs onmc's accountable
brain underneath OpenClaw's transport and mirrors Hermes memory:

- ``openclaw``  — route one OpenClaw event (read from a JSON file) through the
  gateway pipeline and print the OpenClaw-shaped reply.
- ``hermes``    — run the continuous Hermes memory mirror (dry by default).
- ``test-sink`` — format / send a test message via the Telegram or OpenClaw sink.

Every subcommand is a thin wrapper over the pure
:mod:`oh_no_my_claudecode.connect.openclaw` / ``.hermes`` / ``.sinks`` modules and
prints JSON only (never Rich tables) so it is trivially scriptable and testable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.connect.hermes import sync_hermes
from oh_no_my_claudecode.connect.openclaw import handle_openclaw
from oh_no_my_claudecode.connect.sinks import OpenClawSink, TelegramSink
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.notify.events import EventKind, EventSeverity, NotifyEvent

connect_app = typer.Typer(
    help="Bidirectional ecosystem adapter: OpenClaw transport + Hermes memory.",
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
    """Register the ``onmc connect`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(connect_app, name="connect")


@connect_app.command("openclaw")
def connect_openclaw_command(
    file: Annotated[
        Path,
        typer.Option("--file", help="Path to a JSON file holding one OpenClaw event envelope."),
    ],
    dry: Annotated[
        bool,
        typer.Option(
            "--dry/--no-dry",
            help="Dry mode: decide but never spawn a live swarm (default).",
        ),
    ] = True,
) -> None:
    """Route one OpenClaw event through the gateway and print the reply (JSON).

    Reads the event envelope from *file* (offline-friendly), translates it into a
    gateway decision, and prints the OpenClaw-shaped reply.  Live swarm dispatch
    is an intentional follow-up, so this always uses the dry dispatcher and never
    spends money or launches agents.
    """
    repo_root = _repo_root()
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except OSError as exc:
        typer.echo(f"cannot read event file {file}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        typer.echo(f"event file {file} is not valid JSON: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not dry:
        typer.echo(
            "onmc connect: live dispatch is a follow-up — using the dry dispatcher.",
            err=True,
        )
    reply = handle_openclaw(repo_root, payload)
    typer.echo(json.dumps(reply))


@connect_app.command("hermes")
def connect_hermes_command(
    from_path: Annotated[
        Path,
        typer.Option("--from", help="Hermes MEMORY.md / USER.md file or directory to mirror."),
    ],
    dry: Annotated[
        bool,
        typer.Option(
            "--dry/--apply",
            help="Dry mode: report the delta without writing (default). --apply writes.",
        ),
    ] = True,
) -> None:
    """Run the continuous Hermes memory mirror and print the result (JSON).

    Imports only entries new or changed since the last sync (tracked in
    ``.onmc/connect/hermes-state.json``).  A missing source reports all zeros
    rather than failing.
    """
    repo_root = _repo_root()
    result = sync_hermes(repo_root, from_path, dry_run=dry)
    typer.echo(
        json.dumps(
            {
                "imported": result.imported,
                "skipped": result.skipped,
                "total": result.total,
                "dry_run": result.dry_run,
            }
        )
    )


@connect_app.command("test-sink")
def connect_test_sink_command(
    kind: Annotated[
        str,
        typer.Argument(help="Which sink to test: 'telegram' or 'openclaw'."),
    ],
    to: Annotated[
        str | None,
        typer.Option(
            "--to",
            help="Destination URL. Omit for a dry preview of the payload (no network).",
        ),
    ] = None,
    message: Annotated[
        str,
        typer.Option("--message", help="Test message body."),
    ] = "onmc connect test",
) -> None:
    """Format (and optionally send) a test message via a connect sink (JSON).

    With no ``--to`` this is a dry preview: it prints the endpoint + payload the
    sink *would* POST, touching no network.  With ``--to`` it uses the real
    stdlib transport (errors are swallowed by the sink, never raised).
    """
    _repo_root()
    if kind not in ("telegram", "openclaw"):
        typer.echo(f"unknown sink {kind!r}: expected 'telegram' or 'openclaw'.", err=True)
        raise typer.Exit(code=1)

    event = NotifyEvent(kind=EventKind.GENERIC, title=message, severity=EventSeverity.ROUTINE)
    sink: TelegramSink | OpenClawSink
    if kind == "telegram":
        sink = TelegramSink(bot_token=to or "", chat_id="onmc-connect-test")
    else:
        sink = OpenClawSink(to or "")

    if to:
        sink.emit(event)
    typer.echo(
        json.dumps(
            {
                "sink": kind,
                "sent": bool(to),
                "endpoint": sink.endpoint,
                "payload": sink.format(event),
            }
        )
    )
