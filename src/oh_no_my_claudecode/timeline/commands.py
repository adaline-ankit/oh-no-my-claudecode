"""CLI surface for the ``timeline`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. Storage is opened directly, mirroring the roast
command's ``_open_context`` — no shared service hub is touched.

The pure timeline logic lives in :mod:`oh_no_my_claudecode.timeline.timeline`;
this layer only loads the memories, supplies ``now`` for relative ``--since``
parsing, and renders. Degrades gracefully: an empty brain prints a
"no history yet" note and exits 0.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.config import (
    config_exists,
    create_state_dirs,
    database_path,
    load_config,
)
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.timeline.timeline import (
    Timeline,
    build_timeline,
    render_markdown,
)


def _open_context() -> tuple[Path, SQLiteStorage]:
    """Resolve the repo root and open an initialised storage handle.

    Mirrors the roast command's ``_open_context`` so failure messages match the
    rest of the CLI, without routing through the service hub.
    """
    try:
        repo_root = discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        raise typer.Exit(code=1) from None
    if not config_exists(repo_root):
        typer.echo("ONMC is not initialized. Run `onmc init` first.", err=True)
        raise typer.Exit(code=1)
    config = load_config(repo_root)
    create_state_dirs(config, repo_root)
    storage = SQLiteStorage(database_path(config, repo_root))
    storage.initialize()
    return repo_root, storage


def _timeline_to_dict(tl: Timeline) -> dict[str, object]:
    """Serialise a :class:`Timeline` to plain JSON-safe structures."""
    return {
        "total": tl.total,
        "notes": list(tl.notes),
        "periods": [
            {
                "label": period.label,
                "entries": [
                    {
                        "ts": entry.ts.isoformat() if entry.ts is not None else None,
                        "kind": entry.kind,
                        "title": entry.title,
                        "summary": entry.summary,
                    }
                    for entry in period.entries
                ],
            }
            for period in tl.periods
        ],
    }


def _render_rich(tl: Timeline) -> bool:
    """Render *tl* via the shared Rich console; return False if Rich is absent."""
    try:
        from rich.console import Console

        from oh_no_my_claudecode.timeline.timeline import render_summary
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        return False
    render_summary(tl, Console())
    return True


def register(app: typer.Typer) -> None:
    """Register the ``timeline`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("timeline")
    def timeline_command(
        since: Annotated[
            str | None,
            typer.Option(
                "--since",
                help=(
                    "Only include milestones on/after this point — "
                    "an ISO date (2026-07-01) or a relative window (30d)."
                ),
            ),
        ] = None,
        group: Annotated[
            str,
            typer.Option("--group", help="Period granularity: 'day' or 'week'."),
        ] = "day",
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the timeline as JSON."),
        ] = False,
        as_markdown: Annotated[
            bool,
            typer.Option("--markdown", help="Emit the timeline as a markdown story."),
        ] = False,
    ) -> None:
        """Tell this repo's evolution story from its brain.

        Orders the durable memory (decisions, invariants, gotchas, dead-ends)
        over time into a readable narrative grouped into periods. Deterministic
        and offline. An empty brain prints a 'no history yet' note and exits 0.
        """
        if group not in ("day", "week"):
            typer.echo("--group must be 'day' or 'week'.", err=True)
            raise typer.Exit(code=1)

        _, storage = _open_context()
        memories = storage.list_memories()
        tl = build_timeline(
            memories,
            since=since,
            group=group,  # type: ignore[arg-type]
            now=datetime.now(UTC),
        )

        if as_json:
            typer.echo(json.dumps(_timeline_to_dict(tl)))
            return
        if as_markdown:
            typer.echo(render_markdown(tl))
            return
        if not _render_rich(tl):
            typer.echo(render_markdown(tl))
