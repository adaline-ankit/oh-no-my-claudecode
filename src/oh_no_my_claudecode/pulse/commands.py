"""CLI surface for the ``pulse`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time.  No shared hub is touched — **zero** edits to
``cli.py``.

``onmc pulse`` is the one-shot "is it stuck?" heartbeat: it reads live swarm
state (reusing the ``missioncontrol`` reader), reduces it to a liveness verdict
(▶ working / ⏸ idle / ⚠️ possibly-stuck), prints it, and — with ``--notify`` —
pushes it to the configured notify sink(s) so the verdict reaches your phone.
It is the push-a-verdict complement to ``onmc watch`` (a terminal-only TUI).

The real clock is injected here (``time.time``); the frame/verdict builder in
:mod:`oh_no_my_claudecode.pulse.heartbeat` is a pure function of on-disk state
plus that injected ``now_ms``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.pulse.heartbeat import (
    VERDICT_STUCK,
    Pulse,
    build_pulse,
    render_pulse_text,
    to_event,
)


def _repo_root() -> Path:
    """Resolve the repo root from CWD, or exit cleanly when not in an onmc repo."""
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo(
            "Not inside an onmc repository (no repo root found). Run from your project.",
            err=True,
        )
        raise typer.Exit(code=1) from None


def _push(repo_root: Path, pulse: Pulse) -> None:
    """Push *pulse* to the configured notify sink(s).  Exception-safe."""
    from oh_no_my_claudecode.notify.events import EventKind, EventSeverity, NotifyEvent
    from oh_no_my_claudecode.notify.router import emit_event

    payload = to_event(pulse)
    severity = (
        EventSeverity.FAILURE
        if payload["severity"] == "failure"
        else EventSeverity.ROUTINE
    )
    event = NotifyEvent(
        kind=EventKind.GENERIC,
        title=str(payload["title"]),
        severity=severity,
        detail=str(payload["detail"]),
    )
    emit_event(repo_root, event)


def register(app: typer.Typer) -> None:
    """Register the ``pulse`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("pulse")
    def pulse_command(
        swarm_id: Annotated[
            str | None,
            typer.Argument(
                help="Only pulse this swarm. Omit to pulse every active swarm.",
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the pulse as machine-readable JSON."),
        ] = False,
        notify: Annotated[
            bool,
            typer.Option("--notify", help="Push the verdict via the configured notify sink(s)."),
        ] = False,
        stuck_after: Annotated[
            float,
            typer.Option(
                "--stuck-after",
                help="Seconds a running unit may make no progress before it is flagged stuck.",
            ),
        ] = 300.0,
    ) -> None:
        """Live "is it stuck?" heartbeat for your swarms — push it to your phone.

        Reads the current swarm state and emits ONE compact liveness verdict:
        ▶ working / ⏸ idle / ⚠️ possibly-stuck. Solves *Interactive Entropy* —
        not knowing whether the agent is making progress, idle, or wedged.

        With ``--notify`` the verdict is pushed to the configured notify
        sink(s) (Slack / Discord / file) so you get "still working: 4m elapsed"
        or "⚠️ no progress for 5m" on your phone. Unlike ``onmc watch`` (a
        terminal-only auto-refresh monitor), pulse is a one-shot verdict + push.

        Read-only: never mutates swarm state. Exits 0 with a friendly message
        when there are no active swarms.
        """
        if stuck_after <= 0:
            typer.echo("--stuck-after must be a positive number of seconds.", err=True)
            raise typer.Exit(code=1)

        repo_root = _repo_root()
        now_ms = int(time.time() * 1000)
        pulse = build_pulse(
            repo_root,
            swarm_id=swarm_id,
            now_ms=now_ms,
            stuck_after_ms=int(stuck_after * 1000),
        )

        if notify:
            _push(repo_root, pulse)

        if as_json:
            typer.echo(json.dumps(pulse.to_dict()))
            return

        typer.echo(render_pulse_text(pulse))
        # A stuck verdict is an actionable, non-zero condition — surface it in
        # the exit code so scripts / watchers can branch on it.  Empty and idle
        # are healthy (0).
        if pulse.overall == VERDICT_STUCK:
            raise typer.Exit(code=2)
