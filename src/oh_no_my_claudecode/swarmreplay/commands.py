"""CLI surface for the ``swarmreplay`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. No shared hub is touched.

The command is strictly **read-only**: it resolves the repo's swarm base
(``.onmc/swarm``) the same way Mission Control does, reads the manifest +
receipts, and renders an ordered, per-iteration timeline. It never mutates
swarm state.

Named ``swarmreplay`` (not ``replay``) to avoid colliding with the existing
``onmc replay`` command group (Replay Lab, a different feature — see
:mod:`oh_no_my_claudecode.swarmreplay` docstring for the full rationale).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.missioncontrol.dashboard import list_swarm_ids
from oh_no_my_claudecode.swarmreplay.replay import (
    build_replay,
    render_step_text,
    render_text,
)


def _swarm_base() -> Path:
    """Resolve ``<repo>/.onmc/swarm`` from the current working directory.

    Mirrors how Mission Control anchors state. Exits with a clear message (not
    a traceback) when not inside an onmc repo.
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


def _most_recent_swarm_id(base: Path) -> str | None:
    """Return the most recently modified swarm id under *base*, or ``None``.

    "Most recent" is determined by each swarm dir's ``manifest.json`` mtime —
    the manifest is rewritten on every unit transition, so its mtime tracks
    the swarm's last activity without requiring any extra bookkeeping file.
    Ties (identical mtimes) break deterministically via swarm id (descending)
    so repeated calls against unchanged state are stable.
    """
    ids = list_swarm_ids(base)
    if not ids:
        return None

    def _mtime(swarm_id: str) -> float:
        manifest = base / swarm_id / "manifest.json"
        try:
            return manifest.stat().st_mtime
        except OSError:
            return -1.0

    return max(ids, key=lambda sid: (_mtime(sid), sid))


def register(app: typer.Typer) -> None:
    """Register the ``swarmreplay`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("swarmreplay")
    def swarmreplay_command(
        swarm_id: Annotated[
            str | None,
            typer.Argument(
                help="Swarm id to replay. Omit to use the most recently active swarm."
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the full ordered step list as JSON."),
        ] = False,
        step: Annotated[
            int | None,
            typer.Option("--step", help="Print only step N's detail (0-based index)."),
        ] = None,
    ) -> None:
        """Time-travel, step-by-step reconstruction of a swarm run.

        Reconstructs the ordered, cross-unit timeline of a swarm run from its
        manifest + tamper-evident receipts: units ordered by their receipt's
        started_at, one step per iteration (from iteration_hashes) within
        each unit. Read-only and deterministic — the same on-disk state
        always replays identically. This is the CLI foundation for a future
        UI scrubber, so --json emits a stable, additive-only schema.

        Examples:

          onmc swarmreplay                  # most recent swarm, human-readable

          onmc swarmreplay abc123           # a specific swarm

          onmc swarmreplay abc123 --json    # full ordered step list as JSON

          onmc swarmreplay abc123 --step 3  # just step 3's detail
        """
        base = _swarm_base()

        resolved_id = swarm_id
        if resolved_id is None:
            resolved_id = _most_recent_swarm_id(base)
            if resolved_id is None:
                if as_json:
                    empty_payload: dict[str, Any] = {
                        "swarm_id": None,
                        "exists": False,
                        "total": 0,
                        "steps": [],
                        "notes": [],
                    }
                    typer.echo(json.dumps(empty_payload))
                else:
                    typer.echo(
                        "No swarms found under .onmc/swarm. Run `onmc swarm` to start one.",
                        err=True,
                    )
                raise typer.Exit(code=1)

        replay = build_replay(base, resolved_id)

        if step is not None:
            if as_json:
                found = replay.step_at(step)
                typer.echo(json.dumps(found.to_dict() if found is not None else None))
            else:
                typer.echo(render_step_text(replay, step))
            if not replay.exists or replay.step_at(step) is None:
                raise typer.Exit(code=1)
            return

        if as_json:
            typer.echo(json.dumps(replay.to_dict()))
        else:
            typer.echo(render_text(replay))

        if not replay.exists:
            raise typer.Exit(code=1)
