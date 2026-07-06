"""CLI surface for the ``standup`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. Receipts are loaded directly via
:func:`oh_no_my_claudecode.ledger.accounting.load_receipts` — no shared service
hub is touched.

The pure standup logic lives in :mod:`oh_no_my_claudecode.standup.standup`;
this layer only resolves the repo root, loads receipts, supplies ``now`` for
relative ``--since`` parsing, and renders. Degrades gracefully: no receipts in
the window prints an honest "no agent runs" note and exits 0.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.ledger.accounting import load_receipts
from oh_no_my_claudecode.standup.standup import (
    DEFAULT_SINCE,
    StandupReport,
    build_standup,
    render_text,
)


def _resolve_repo_root() -> Path:
    """Resolve the repo root from cwd, exiting cleanly if not in a repo."""
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("Not inside a repository. Run from within your project.", err=True)
        raise typer.Exit(code=1) from None


def _report_to_dict(report: StandupReport) -> dict[str, object]:
    """Serialise a :class:`StandupReport` to plain JSON-safe structures."""
    return {
        "since": report.since.isoformat(),
        "now": report.now.isoformat(),
        "since_label": report.since_label,
        "total_runs": report.total_runs,
        "verified_count": report.verified_count,
        "failed_count": report.failed_count,
        "success_rate": report.success_rate,
        "total_cost_usd": report.total_cost_usd,
        "cost_unknown_count": report.cost_unknown_count,
        "total_wall_seconds": report.total_wall_seconds,
        "by_model": [asdict(m) for m in report.by_model],
        "top_goals": [asdict(g) for g in report.top_goals],
        "notable": [asdict(n) for n in report.notable],
        "excluded_undated_count": report.excluded_undated_count,
        "notes": list(report.notes),
    }


def register(app: typer.Typer) -> None:
    """Register the ``standup`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("standup")
    def standup_command(
        since: Annotated[
            str,
            typer.Option(
                "--since",
                help=(
                    "Window to summarize — a relative window (24h, 7d) or an "
                    "ISO date/datetime. Defaults to 24h."
                ),
            ),
        ] = DEFAULT_SINCE,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the standup as JSON."),
        ] = False,
    ) -> None:
        """Summarize recent agent run activity — a daily-standup-style digest.

        Reads run receipts from ``.agent-memory/receipts/`` and reports total
        runs, verified/failed counts, cost, wall time, a per-model breakdown,
        top goals worked on, and notable items (failures, high-iteration
        runs) within the window. Deterministic and offline — no LLM call. An
        empty window prints an honest "no agent runs" note and exits 0.
        """
        repo_root = _resolve_repo_root()
        now = datetime.now(UTC)
        receipts = load_receipts(repo_root, scope="project", now=now)
        report = build_standup(receipts, now=now, since=since)

        if as_json:
            typer.echo(json.dumps(_report_to_dict(report)))
            return
        typer.echo(render_text(report))
