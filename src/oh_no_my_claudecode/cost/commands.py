"""CLI surface for the ``cost`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. Receipts are loaded directly via
:func:`oh_no_my_claudecode.ledger.accounting.load_receipts` — no shared service
hub is touched.

The pure cost logic lives in :mod:`oh_no_my_claudecode.cost.cost`; this layer
only resolves the repo root, loads receipts, supplies ``now`` for the trailing
``--days`` window, and renders. Degrades gracefully: no receipts in the window
prints an honest "no agent runs" note and exits 0.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.cost.cost import (
    DEFAULT_DAYS,
    CostReport,
    build_cost_report,
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


def _report_to_dict(report: CostReport) -> dict[str, object]:
    """Serialise a :class:`CostReport` to plain JSON-safe structures."""
    return {
        "since": report.since.isoformat(),
        "now": report.now.isoformat(),
        "days": report.days,
        "total_runs": report.total_runs,
        "total_cost_usd": report.total_cost_usd,
        "cost_unknown_count": report.cost_unknown_count,
        "verified_count": report.verified_count,
        "cost_per_verified_run_usd": report.cost_per_verified_run_usd,
        "by_model": [asdict(m) for m in report.by_model],
        "by_day": [asdict(d) for d in report.by_day],
        "forecast_daily_avg_usd": report.forecast_daily_avg_usd,
        "forecast_monthly_usd": report.forecast_monthly_usd,
        "excluded_undated_count": report.excluded_undated_count,
        "notes": list(report.notes),
    }


def register(app: typer.Typer) -> None:
    """Register the ``cost`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("cost")
    def cost_command(
        days: Annotated[
            int,
            typer.Option("--days", help="Trailing window size in days. Defaults to 30."),
        ] = DEFAULT_DAYS,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the cost report as JSON."),
        ] = False,
    ) -> None:
        """Spend breakdown and forecast from run receipts.

        Reads run receipts from ``.agent-memory/receipts/`` and reports total
        spend, spend by model, spend by day over the trailing window, cost
        per verified run, and a clearly-labelled linear forecast of monthly
        spend. Deterministic and offline — no LLM call. Distinct from
        ``onmc savings`` (an ROI estimate) and ``onmc standup`` (an activity
        digest): this is about money. An empty window prints an honest
        "no agent runs" note and exits 0.
        """
        repo_root = _resolve_repo_root()
        now = datetime.now(UTC)
        receipts = load_receipts(repo_root, scope="project", now=now)
        report = build_cost_report(receipts, now=now, days=days)

        if as_json:
            typer.echo(json.dumps(_report_to_dict(report)))
            return
        typer.echo(render_text(report))
