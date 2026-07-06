"""CLI surface for the ``watch`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time.  No shared hub is touched.

``onmc watch`` is the terminal-native complement to the web ``onmc ui``: a
continuously-refreshing live view of what active swarms are doing right now.
It is strictly **read-only** — it resolves the repo's swarm base the same way
``onmc missioncontrol`` does and re-renders :func:`build_frame` /
:func:`render_frame` on an interval.  The refresh loop lives entirely in this
module; the frame builder itself is a pure function of on-disk swarm state
(see :mod:`oh_no_my_claudecode.watch.watch`).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from rich.console import Console

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.watch.watch import WatchFrame, build_frame, render_frame

_DEFAULT_INTERVAL_SECONDS = 2.0


def _swarm_base() -> Path:
    """Resolve ``<repo>/.onmc/swarm`` from the current working directory.

    Mirrors how ``onmc missioncontrol`` anchors state.  Exits with a clear
    message (not a traceback) when not inside an onmc repo.
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


def _console() -> Console:
    """Return a shared Rich Console (import lazily so tests can inject their own)."""
    from rich.console import Console

    return Console()


def _clear_screen(console: Console) -> None:
    """Clear the terminal between frames.

    Uses Rich's own clear (ANSI) rather than shelling out to ``cls``/``clear``
    — avoids a subprocess for a purely cosmetic action.
    """
    console.clear()


def _render_rich(frame: WatchFrame, console: Console) -> None:
    """Render *frame* with Rich styling; falls back to plain text on failure."""
    if not frame.swarms:
        console.print("[yellow]No active swarms.[/yellow]")
        return

    console.print(f"[bold]onmc watch[/bold] — {len(frame.swarms)} active swarm(s)")
    console.print()
    for s in frame.swarms:
        console.print(
            f"[bold cyan]{s.swarm_id}[/bold cyan]  "
            f"[bold yellow]running[/bold yellow]={s.running}  "
            f"[cyan]queued[/cyan]={s.queued}  "
            f"[dim]pending[/dim]={s.pending}  "
            f"[bold green]done[/bold green]={s.done}  "
            f"[bold red]failed[/bold red]={s.failed}  "
            f"verified={s.verified_count}/{s.total}"
        )
        for goal in s.recent_goals:
            trimmed = goal if len(goal) <= 70 else goal[:67] + "..."
            console.print(f"    - {trimmed}")
        console.print()


def register(app: typer.Typer) -> None:
    """Register the ``watch`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("watch")
    def watch_command(
        interval: Annotated[
            float,
            typer.Option("--interval", help="Seconds between refreshes."),
        ] = _DEFAULT_INTERVAL_SECONDS,
        once: Annotated[
            bool,
            typer.Option("--once", help="Render exactly one frame and exit."),
        ] = False,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit one JSON frame and exit (implies --once)."),
        ] = False,
        show_all: Annotated[
            bool,
            typer.Option(
                "--all",
                help="Include swarms whose units are all terminal, not just active ones.",
            ),
        ] = False,
    ) -> None:
        """Auto-refreshing terminal live monitor of active swarms.

        The terminal-native complement to the web ``onmc ui``: continuously
        re-renders a compact summary of every active swarm under
        ``.onmc/swarm`` — running/queued/pending/done/failed unit counts,
        verified count, and the most recent in-flight unit goals. Unlike
        ``onmc missioncontrol`` (a one-shot snapshot of a single named
        swarm), ``watch`` re-renders on an interval across all swarms until
        interrupted with Ctrl-C.

        Read-only: never mutates swarm state. An empty repo (no active
        swarms) renders an honest empty-state message.
        """
        if interval <= 0:
            typer.echo("--interval must be a positive number of seconds.", err=True)
            raise typer.Exit(code=1)

        base = _swarm_base()
        active_only = not show_all

        # --json always renders exactly one frame — there is no meaningful
        # "streaming JSON" mode here, so it implies --once.
        if as_json:
            frame = build_frame(base, active_only=active_only)
            typer.echo(json.dumps(frame.to_dict()))
            return

        if once:
            frame = build_frame(base, active_only=active_only)
            typer.echo(render_frame(frame))
            return

        console = _console()
        try:
            while True:
                frame = build_frame(base, active_only=active_only)
                _clear_screen(console)
                _render_rich(frame, console)
                console.print(
                    f"[dim]refreshing every {interval:g}s — Ctrl-C to stop[/dim]"
                )
                time.sleep(interval)
        except KeyboardInterrupt:
            # Clean, silent exit on Ctrl-C — this is the expected way to stop
            # a live monitor, not an error.
            raise typer.Exit(code=0) from None
