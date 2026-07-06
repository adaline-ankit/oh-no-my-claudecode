"""CLI surface for the ``postmortem`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. No shared hub is touched.

The command is strictly **read-only** and makes no LLM calls: it resolves the
repo's swarm base (``.onmc/swarm``) the same way ``missioncontrol`` does,
builds a :class:`~oh_no_my_claudecode.missioncontrol.dashboard.DashboardModel`
via :func:`~oh_no_my_claudecode.missioncontrol.dashboard.build_dashboard`, reads
each unit's receipt via
:func:`~oh_no_my_claudecode.badge.badge.load_receipt` (reusing the same
manifest-driven resolution ``onmc badge`` uses — never hand-rolled JSON
parsing), and hands both off to the pure
:mod:`oh_no_my_claudecode.postmortem.postmortem` core.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.badge.badge import load_receipt
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.missioncontrol.dashboard import UnitStatus, build_dashboard, list_swarm_ids
from oh_no_my_claudecode.postmortem.postmortem import Postmortem, build_postmortem, render_text


def _swarm_base() -> Path:
    """Resolve ``<repo>/.onmc/swarm`` from the current working directory.

    Mirrors how ``missioncontrol`` anchors state. Exits with a clear message
    (not a traceback) when not inside an onmc repo.
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


def _make_receipt_reader(repo_root: Path, swarm_id: str) -> Any:
    """Build a per-unit receipt reader bound to *repo_root* and *swarm_id*.

    Delegates to :func:`~oh_no_my_claudecode.badge.badge.load_receipt`, which
    already knows how to resolve a manifest unit's ``receipt_path`` — this
    avoids re-parsing the manifest JSON by hand a second time.
    """

    def _read(unit: UnitStatus) -> dict[str, Any] | None:
        return load_receipt(swarm_id, unit_id=unit.unit_id, repo_root=repo_root)

    return _read


def _most_recent_swarm_id(base: Path) -> str | None:
    """Return the most recently started swarm id, or ``None`` when there are none.

    ``list_swarm_ids`` returns ids in sorted (lexicographic) order; onmc swarm
    ids are generated with a monotonically increasing/time-ordered prefix, so
    the lexicographically last id is also the most recent one — same
    assumption ``missioncontrol --all`` relies on for its listing.
    """
    ids = list_swarm_ids(base)
    return ids[-1] if ids else None


def register(app: typer.Typer) -> None:
    """Register the ``postmortem`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("postmortem")
    def postmortem_command(
        swarm_id: Annotated[
            str | None,
            typer.Argument(help="Swarm id to recap. Omit to use the most recent swarm."),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the structured postmortem as JSON."),
        ] = False,
    ) -> None:
        """LLM-free structured narrative recap of a completed swarm run.

        Reads the swarm manifest + each unit's tamper-evident receipt and
        assembles a deterministic English recap: an overview (units / verified
        / failed / total wall time), a per-unit account of what happened, and
        an honest summary of what went well versus what needs attention.
        Never calls an LLM. Never mutates swarm state. Degrades gracefully on
        missing/partial data instead of crashing.
        """
        base = _swarm_base()

        resolved_id = swarm_id
        if resolved_id is None:
            resolved_id = _most_recent_swarm_id(base)
            if resolved_id is None:
                typer.echo(
                    "No swarms found under .onmc/swarm. Provide a SWARM_ID or run a swarm first.",
                    err=True,
                )
                raise typer.Exit(code=1)

        model = build_dashboard(base, resolved_id)
        repo_root = base.parent.parent  # <repo>/.onmc/swarm -> <repo>
        pm: Postmortem = build_postmortem(model, _make_receipt_reader(repo_root, resolved_id))

        if as_json:
            typer.echo(json.dumps(pm.to_dict()))
        else:
            typer.echo(render_text(pm))

        if not pm.exists:
            raise typer.Exit(code=1)
