"""CLI surface for the ``bottleneck`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. Receipts are loaded directly via
:func:`oh_no_my_claudecode.ledger.accounting.load_receipts` — no shared service
hub is touched.

The pure bottleneck logic lives in
:mod:`oh_no_my_claudecode.bottleneck.bottleneck`; this layer only resolves the
repo root, loads receipts, and renders. Degrades gracefully: no receipts with
timing data prints an honest "no agent runs" note and exits 0.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.bottleneck.bottleneck import (
    DEFAULT_TOP,
    BottleneckReport,
    build_bottleneck,
    render_text,
)
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.ledger.accounting import load_receipts


def _resolve_repo_root() -> Path:
    """Resolve the repo root from cwd, exiting cleanly if not in a repo."""
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("Not inside a repository. Run from within your project.", err=True)
        raise typer.Exit(code=1) from None


def _report_to_dict(report: BottleneckReport) -> dict[str, object]:
    """Serialise a :class:`BottleneckReport` to plain JSON-safe structures."""
    return {
        "total_runs": report.total_runs,
        "excluded_count": report.excluded_count,
        "total_wall_seconds": report.total_wall_seconds,
        "by_goal": [asdict(g) for g in report.by_goal],
        "by_model": [asdict(m) for m in report.by_model],
        "outliers": [asdict(o) for o in report.outliers],
        "time_sink_summary": list(report.time_sink_summary),
        "notes": list(report.notes),
    }


def register(app: typer.Typer) -> None:
    """Register the ``bottleneck`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("bottleneck")
    def bottleneck_command(
        top: Annotated[
            int,
            typer.Option("--top", help="Number of entries to show per ranked list. Defaults to 5."),
        ] = DEFAULT_TOP,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the bottleneck report as JSON."),
        ] = False,
    ) -> None:
        """Find what's slowing your agents down.

        Reads run receipts from ``.agent-memory/receipts/`` and ranks the
        slowest goals (by total and average wall-clock time), the slowest
        models (by average wall-clock and average iterations), and flags
        outlier runs (unusually slow or iteration-heavy relative to the rest
        of the fleet). Deterministic and offline — no LLM call. An empty
        receipt set prints an honest "no agent runs" note and exits 0.
        """
        repo_root = _resolve_repo_root()
        receipts = load_receipts(repo_root, scope="project")
        report = build_bottleneck(receipts, top=top)

        if as_json:
            typer.echo(json.dumps(_report_to_dict(report)))
            return
        typer.echo(render_text(report))
