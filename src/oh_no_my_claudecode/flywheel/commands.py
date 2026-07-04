"""CLI surface for the ``flywheel`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time.  Rendering is inline (a local Rich table with a
plain-text fallback) — no shared rendering hub is touched.  Receipts are read
via the ledger's own loader; nothing in ``ledger/`` is modified.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.flywheel.analyze import (
    FlywheelReport,
    load_trajectories,
    recommend,
    summarize,
)


def _resolve_repo_root() -> Path:
    """Resolve the repo root from cwd, exiting cleanly if not in a repo."""
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("Not inside a repository. Run from within your project.", err=True)
        raise typer.Exit(code=1) from None


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 UTC string; return None on failure/empty input."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _since_cutoff(since: str | None, now: datetime) -> datetime | None:
    """Turn a ``--since`` value into a cutoff datetime, or None for no filter.

    Accepts a relative duration (``7d``, ``48h``, ``30m``) or an ISO-8601 date/
    datetime.  Returns ``None`` (and warns) when the value cannot be parsed, so
    an unparseable filter never silently drops all data.
    """
    if not since:
        return None
    raw = since.strip().lower()
    try:
        if raw.endswith("d"):
            return now - timedelta(days=float(raw[:-1]))
        if raw.endswith("h"):
            return now - timedelta(hours=float(raw[:-1]))
        if raw.endswith("m"):
            return now - timedelta(minutes=float(raw[:-1]))
    except ValueError:
        pass
    iso = _parse_iso(since)
    if iso is not None:
        return iso if iso.tzinfo else iso.replace(tzinfo=UTC)
    typer.echo(f"Could not parse --since '{since}'; ignoring filter.", err=True)
    return None


def _receipt_time(data: dict[str, Any]) -> datetime | None:
    """Timestamp of a receipt (ended_at preferred, then started_at)."""
    return _parse_iso(str(data.get("ended_at") or "")) or _parse_iso(
        str(data.get("started_at") or "")
    )


def _filter_since(
    trajectories: list[dict[str, Any]], cutoff: datetime | None
) -> list[dict[str, Any]]:
    """Keep trajectories at/after *cutoff* (all when *cutoff* is None).

    Receipts without a parseable timestamp are dropped only when a cutoff is
    active — with no cutoff, everything is kept.
    """
    if cutoff is None:
        return trajectories
    kept: list[dict[str, Any]] = []
    for data in trajectories:
        when = _receipt_time(data)
        if when is None:
            continue
        if when.astimezone(UTC) >= cutoff.astimezone(UTC):
            kept.append(data)
    return kept


def _render_plain(report: FlywheelReport, suggestions: list[str]) -> None:
    """Emit the flywheel report as plain text (no Rich dependency)."""
    lines = [
        "",
        "  onmc flywheel — verified trajectory analysis",
        f"  {report.total} runs  |  {report.verified_total} verified",
        "",
        "  By model:",
    ]
    if report.by_model:
        for s in report.by_model:
            cost = "n/a" if s.avg_cost is None else f"${s.avg_cost:.4f}"
            lines.append(
                f"   • {s.model}: verified {s.verified}/{s.runs} "
                f"({s.verified_rate:.0%})  avg cost {cost}  avg wall {s.avg_wall:.1f}s"
            )
    else:
        lines.append("   (no runs recorded)")
    lines.append("")
    lines.append("  Recommendations:")
    for tip in suggestions:
        lines.append(f"   → {tip}")
    if report.note:
        lines.append("")
        lines.append(f"  note: {report.note}")
    lines.append("")
    typer.echo("\n".join(lines))


def _render_rich(report: FlywheelReport, suggestions: list[str]) -> bool:
    """Render the report as a Rich table; return False if Rich is unavailable."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        return False

    console = Console()
    table = Table(
        title=f"onmc flywheel — {report.total} runs, {report.verified_total} verified",
        title_style="bold",
    )
    table.add_column("model", style="cyan")
    table.add_column("verified", justify="right")
    table.add_column("rate", justify="right")
    table.add_column("avg cost", justify="right")
    table.add_column("avg wall", justify="right")

    for i, s in enumerate(report.by_model):
        cost = "n/a" if s.avg_cost is None else f"${s.avg_cost:.4f}"
        rate_style = "green" if s.verified_rate >= 0.7 else (
            "yellow" if s.verified_rate >= 0.4 else "red"
        )
        row_style = "bold" if i == 0 and report.best and s.model == report.best.model else None
        table.add_row(
            s.model,
            f"{s.verified}/{s.runs}",
            Text(f"{s.verified_rate:.0%}", style=rate_style),
            cost,
            f"{s.avg_wall:.1f}s",
            style=row_style,
        )

    console.print(table)

    rec = Text()
    rec.append("Recommendations\n", style="bold")
    for tip in suggestions:
        rec.append(f"  → {tip}\n")
    if report.note:
        rec.append(f"\nnote: {report.note}", style="dim italic")
    console.print(rec)
    return True


def register(app: typer.Typer) -> None:
    """Register the ``flywheel`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("flywheel")
    def flywheel_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the flywheel report as JSON."),
        ] = False,
        since: Annotated[
            str | None,
            typer.Option(
                "--since",
                help="Only include runs since this time (e.g. 7d, 48h, or ISO date).",
            ),
        ] = None,
    ) -> None:
        """Mine verified run trajectories to recommend winning approaches.

        Reads the tamper-evident run receipts written by ``onmc loop`` /
        ``onmc swarm``, aggregates them by model and goal keyword, and reports
        which approaches produced *verified* results — plus ranked
        recommendations. Deterministic and fully offline (no LLM call).
        """
        repo_root = _resolve_repo_root()
        trajectories = load_trajectories(repo_root)
        cutoff = _since_cutoff(since, datetime.now(UTC))
        trajectories = _filter_since(trajectories, cutoff)

        report = summarize(trajectories)
        suggestions = recommend(report)

        if as_json:
            payload = report.to_dict()
            payload["recommendations"] = suggestions
            typer.echo(json.dumps(payload))
            return

        if not _render_rich(report, suggestions):
            _render_plain(report, suggestions)
