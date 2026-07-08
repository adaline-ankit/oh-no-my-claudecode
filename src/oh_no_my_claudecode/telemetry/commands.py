"""CLI surface for the ``telemetry`` feature — auto-discovered.

Follows the auto-discovery convention (``command_registry.py``): this module
exposes a top-level ``register(app)`` that the registry invokes at CLI build
time, so ``onmc live`` ships with **zero edits** to ``cli.py``.

Commands
--------
``onmc live``           — Snapshot: active agents/units + last N events.
``onmc live tail``      — Print events (bounded read, not an infinite loop).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.telemetry.bus import Event, active_agents, read_events

_DEFAULT_TAIL_N = 50
_LIVE_DIR_NAME = Path(".onmc") / "live"


def _live_dir(repo_root: Path) -> Path:
    return repo_root / ".onmc" / "live"


def _snapshot_dict(repo_root: Path) -> dict[str, object]:
    """Return a JSON-serialisable snapshot of current live state."""
    events = read_events(_live_dir(repo_root))
    agents = active_agents(events)
    last_n = [
        {
            "ts": e.ts,
            "kind": e.kind,
            "swarm_id": e.swarm_id,
            "unit": e.unit,
            "agent": e.agent,
            "tool": e.tool,
            "detail": e.detail,
            "session_id": e.session_id,
        }
        for e in events[-_DEFAULT_TAIL_N:]
    ]
    return {
        "active_agents": agents,
        "recent_events": last_n,
        "total_events": len(events),
    }


def _format_event(ev: Event) -> str:
    parts = [f"ts={ev.ts:.3f}", f"kind={ev.kind}"]
    if ev.swarm_id:
        parts.append(f"swarm={ev.swarm_id[:8]}")
    if ev.unit:
        parts.append(f"unit={ev.unit}")
    if ev.tool:
        parts.append(f"tool={ev.tool}")
    if ev.detail:
        parts.append(f"detail={ev.detail[:80]}")
    if ev.session_id:
        parts.append(f"session={ev.session_id[:8]}")
    return "  ".join(parts)


def register(app: typer.Typer) -> None:
    """Register the ``onmc live`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    live_app = typer.Typer(
        name="live",
        help="Live agent activity: snapshot active agents and recent events.",
        no_args_is_help=False,
        invoke_without_command=True,
    )

    @live_app.callback(invoke_without_command=True)
    def live_snapshot(
        ctx: typer.Context,
        as_json: Annotated[
            bool,
            typer.Option(
                "--json",
                help="Emit JSON instead of human-readable text.",
            ),
        ] = False,
        n: Annotated[
            int,
            typer.Option(
                "--last",
                help="Number of recent events to show (default: 50).",
                metavar="N",
            ),
        ] = _DEFAULT_TAIL_N,
    ) -> None:
        """Show active agents and recent events (snapshot).

        Reads ``.onmc/live/events.jsonl`` and prints the current active units
        plus the last N events.  Use ``onmc live tail`` for a filtered view.

        Examples:

            onmc live              # human-readable snapshot

            onmc live --json       # JSON snapshot (pipeline-friendly)

            onmc live --last 10    # show only last 10 events
        """
        if ctx.invoked_subcommand is not None:
            return
        try:
            repo_root = discover_repo_root(Path.cwd())
        except RepoDiscoveryError:
            typer.echo("error: no git repository found from the current directory.", err=True)
            raise typer.Exit(code=1) from None

        events = read_events(_live_dir(repo_root))
        agents = active_agents(events)
        recent = events[-n:] if n > 0 else []

        if as_json:
            payload = {
                "active_agents": agents,
                "recent_events": [
                    {
                        "ts": e.ts,
                        "kind": e.kind,
                        "swarm_id": e.swarm_id,
                        "unit": e.unit,
                        "agent": e.agent,
                        "tool": e.tool,
                        "detail": e.detail,
                        "session_id": e.session_id,
                    }
                    for e in recent
                ],
                "total_events": len(events),
            }
            typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        else:
            typer.echo(f"active agents: {len(agents)}")
            for a in agents:
                typer.echo(
                    f"  unit={a['unit']}  swarm={a['swarm_id']}  "
                    f"since={a['since_ts']:.3f}"
                )
            typer.echo(f"\nrecent events ({len(recent)} of {len(events)} total):")
            for ev in recent:
                typer.echo(f"  {_format_event(ev)}")

    @live_app.command("tail")
    def live_tail(
        since: Annotated[
            float | None,
            typer.Option(
                "--since",
                help="Only show events with ts > SINCE (Unix timestamp).",
                metavar="TS",
            ),
        ] = None,
        kinds: Annotated[
            str | None,
            typer.Option(
                "--kinds",
                help="Comma-separated list of event kinds to include.",
                metavar="KINDS",
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option(
                "--json",
                help="Emit one JSON object per line instead of text.",
            ),
        ] = False,
        limit: Annotated[
            int,
            typer.Option(
                "--limit",
                help="Maximum number of events to return (default: 200).",
                metavar="N",
            ),
        ] = 200,
    ) -> None:
        """Print events from the live log (bounded, not an infinite tail).

        Reads ``.onmc/live/events.jsonl`` and prints matching events.
        Use ``--since TS`` to page through events after a known timestamp,
        ``--kinds k1,k2`` to filter by event kind.

        Examples:

            onmc live tail                      # last 200 events

            onmc live tail --since 1700000000   # events after that timestamp

            onmc live tail --kinds tool_call    # only tool_call events

            onmc live tail --json               # JSONL output
        """
        try:
            repo_root = discover_repo_root(Path.cwd())
        except RepoDiscoveryError:
            typer.echo("error: no git repository found from the current directory.", err=True)
            raise typer.Exit(code=1) from None

        kind_list: list[str] | None = None
        if kinds:
            kind_list = [k.strip() for k in kinds.split(",") if k.strip()]

        events = read_events(_live_dir(repo_root), since_ts=since, kinds=kind_list)
        events = events[-limit:] if limit > 0 else events

        for ev in events:
            if as_json:
                typer.echo(
                    json.dumps(
                        {
                            "ts": ev.ts,
                            "kind": ev.kind,
                            "swarm_id": ev.swarm_id,
                            "unit": ev.unit,
                            "agent": ev.agent,
                            "tool": ev.tool,
                            "detail": ev.detail,
                            "session_id": ev.session_id,
                        },
                        ensure_ascii=False,
                    )
                )
            else:
                typer.echo(_format_event(ev))

    app.add_typer(live_app, name="live")
