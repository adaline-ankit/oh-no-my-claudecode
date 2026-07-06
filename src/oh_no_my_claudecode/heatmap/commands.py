"""CLI surface for the ``heatmap`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. Receipts are read via the ledger's own loader
(:func:`oh_no_my_claudecode.ledger.accounting.load_receipts`); nothing in
``ledger/`` is modified. Rendering is inline plain text — the grid is
block-glyph text, not a Rich table, so it looks right in any terminal.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.heatmap.heatmap import (
    DEFAULT_WEEKS,
    Heatmap,
    build_heatmap,
    render_text,
)
from oh_no_my_claudecode.ledger.accounting import load_receipts


def _resolve_repo_root() -> Path:
    """Resolve the repo root from cwd, exiting cleanly if not in a repo."""
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("Not inside a repository. Run from within your project.", err=True)
        raise typer.Exit(code=1) from None


def _heatmap_to_dict(hm: Heatmap) -> dict[str, object]:
    """Serialise a :class:`Heatmap` to plain JSON-safe structures."""
    return {
        "days": [
            {
                "date": cell.day.isoformat(),
                "count": cell.count,
                "verified_count": cell.verified_count,
            }
            for cell in hm.days
        ],
        "totals": {
            "weeks": hm.weeks,
            "total_runs": hm.total_runs,
            "active_days": hm.active_days,
            "busiest_day": (
                {"date": hm.busiest_day.day.isoformat(), "count": hm.busiest_day.count}
                if hm.busiest_day is not None
                else None
            ),
            "current_streak": hm.current_streak,
        },
        "notes": list(hm.notes),
    }


def register(app: typer.Typer) -> None:
    """Register the ``heatmap`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("heatmap")
    def heatmap_command(
        weeks: Annotated[
            int,
            typer.Option("--weeks", help="Number of weeks to include in the grid."),
        ] = DEFAULT_WEEKS,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the heatmap as JSON."),
        ] = False,
    ) -> None:
        """Render a GitHub-contributions-style heatmap of agent run activity.

        Reads the tamper-evident run receipts written by ``onmc loop`` /
        ``onmc swarm``, buckets them by calendar day, and renders a
        block-glyph calendar grid plus totals (total runs, active days,
        busiest day, current streak). Deterministic and fully offline (no
        LLM call). An empty receipts directory prints a "no runs yet" note
        and exits 0.
        """
        if weeks < 1:
            typer.echo("--weeks must be at least 1.", err=True)
            raise typer.Exit(code=1)

        repo_root = _resolve_repo_root()
        receipts = load_receipts(repo_root, scope="project")
        today = datetime.now(UTC).date()
        hm = build_heatmap(receipts, today=today, weeks=weeks)

        if as_json:
            typer.echo(json.dumps(_heatmap_to_dict(hm)))
            return

        typer.echo(render_text(hm))
