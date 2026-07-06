"""CLI surface for the ``compare`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. No shared hub is touched.

The command is strictly **read-only** and makes no LLM calls: it resolves the
repo's swarm base (``.onmc/swarm``) the same way ``missioncontrol`` and
``postmortem`` do, builds a
:class:`~oh_no_my_claudecode.missioncontrol.dashboard.DashboardModel` for each
side via
:func:`~oh_no_my_claudecode.missioncontrol.dashboard.build_dashboard`, reads
each unit's receipt via
:func:`~oh_no_my_claudecode.badge.badge.load_receipt` (same resolution
``onmc postmortem``/``onmc badge`` use), and hands both off to the pure
:mod:`oh_no_my_claudecode.compare.compare` core.

Distinct from ``onmc race`` (a model tournament over *all* receipts) and
``onmc postmortem`` (a narrative recap of a *single* run) — this is a
head-to-head comparison of exactly two swarm runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.badge.badge import load_receipt
from oh_no_my_claudecode.compare.compare import (
    Comparison,
    RunMetrics,
    build_comparison,
    build_run_metrics,
    render_text,
)
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.missioncontrol.dashboard import UnitStatus, build_dashboard, list_swarm_ids


def _swarm_base() -> Path:
    """Resolve ``<repo>/.onmc/swarm`` from the current working directory.

    Mirrors how ``missioncontrol``/``postmortem`` anchor state. Exits with a
    clear message (not a traceback) when not inside an onmc repo.
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
    already knows how to resolve a manifest unit's ``receipt_path`` — avoids
    re-parsing manifest JSON by hand (same approach as ``onmc postmortem``).
    """

    def _read(unit: UnitStatus) -> dict[str, Any] | None:
        return load_receipt(swarm_id, unit_id=unit.unit_id, repo_root=repo_root)

    return _read


def _most_recent_other_swarm_id(base: Path, exclude: str) -> str | None:
    """Return the most recently started swarm id other than *exclude*.

    ``list_swarm_ids`` returns ids in sorted (lexicographic) order; onmc
    swarm ids are generated with a monotonically increasing/time-ordered
    prefix, so the lexicographically last non-excluded id is also the most
    recent one — same assumption ``onmc postmortem`` relies on.
    """
    ids = [i for i in list_swarm_ids(base) if i != exclude]
    return ids[-1] if ids else None


def _build_run_metrics(base: Path, swarm_id: str) -> RunMetrics:
    model = build_dashboard(base, swarm_id)
    repo_root = base.parent.parent  # <repo>/.onmc/swarm -> <repo>
    return build_run_metrics(model, _make_receipt_reader(repo_root, swarm_id))


def register(app: typer.Typer) -> None:
    """Register the ``compare`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("compare")
    def compare_command(
        swarm_id_a: Annotated[
            str,
            typer.Argument(help="First swarm id to compare."),
        ],
        swarm_id_b: Annotated[
            str | None,
            typer.Argument(
                help="Second swarm id to compare. Omit to use the most recent OTHER swarm."
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the structured comparison as JSON."),
        ] = False,
    ) -> None:
        """Side-by-side, read-only comparison of two swarm runs.

        Reads each swarm's manifest + unit receipts and reports units total,
        verified count/rate, wall time, cost, average iterations, and models
        used for both runs side by side, with a per-metric winner marker and
        a one-line verdict on which run did better. Never calls an LLM, never
        mutates swarm state. Degrades gracefully on missing/partial data
        instead of crashing.
        """
        base = _swarm_base()

        resolved_b = swarm_id_b
        if resolved_b is None:
            resolved_b = _most_recent_other_swarm_id(base, exclude=swarm_id_a)
            if resolved_b is None:
                typer.echo(
                    "No other swarms found under .onmc/swarm to compare against. "
                    "Provide a second SWARM_ID.",
                    err=True,
                )
                raise typer.Exit(code=1)

        run_a = _build_run_metrics(base, swarm_id_a)
        run_b = _build_run_metrics(base, resolved_b)
        comparison: Comparison = build_comparison(run_a, run_b)

        if as_json:
            typer.echo(json.dumps(comparison.to_dict()))
        else:
            typer.echo(render_text(comparison))

        if not run_a.exists or not run_b.exists:
            raise typer.Exit(code=1)
