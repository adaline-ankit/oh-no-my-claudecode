"""CLI surface for the ``race`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. Rendering is inline (a local Rich table with a
plain-text fallback), mirroring ``flywheel.commands`` — no shared rendering hub
is touched. Receipts are read via the ledger's own loader; nothing in
``ledger/`` is modified.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.ledger.accounting import load_receipts
from oh_no_my_claudecode.race.race import RaceResult, race


def _resolve_repo_root() -> Path:
    """Resolve the repo root from cwd, exiting cleanly if not in a repo."""
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("Not inside a repository. Run from within your project.", err=True)
        raise typer.Exit(code=1) from None


def _fmt_cost(cost: float | None) -> str:
    """Render a cost as ``$X.XXXX`` or ``n/a`` — never a fabricated number."""
    return "n/a" if cost is None else f"${cost:.4f}"


def _render_plain(result: RaceResult) -> None:
    """Emit the race result as plain text (no Rich dependency)."""
    title = f"'{result.query}'" if result.query is not None else "all receipts"
    lines = [
        "",
        f"  onmc race — {title}",
        f"  {result.total_runs} runs  |  {result.verified_runs} verified",
    ]
    if result.matched_keywords:
        lines.append(f"  matched keywords: {', '.join(result.matched_keywords)}")
    lines.append("")
    lines.append("  Leaderboard:")
    if result.leaderboard:
        for row in result.leaderboard:
            marker = " *" if result.winner is not None and row.model == result.winner.model else ""
            lines.append(
                f"   • {row.model}: verified {row.verified}/{row.runs} "
                f"({row.verified_rate:.0%})  avg cost {_fmt_cost(row.avg_cost)}  "
                f"avg wall {row.avg_wall_seconds:.1f}s{marker}"
            )
    else:
        lines.append("   (no runs recorded)")
    lines.append("")
    if result.winner is not None:
        lines.append(f"  Winner: {result.winner.model}")
    else:
        lines.append("  Winner: none (insufficient data)")
    if result.note:
        lines.append(f"  note: {result.note}")
    lines.append("")
    typer.echo("\n".join(lines))


def _render_rich(result: RaceResult) -> bool:
    """Render the result as a Rich table; return False if Rich is unavailable."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        return False

    title = f"'{result.query}'" if result.query is not None else "all receipts"
    console = Console()
    table = Table(
        title=f"onmc race — {title} — {result.total_runs} runs, "
        f"{result.verified_runs} verified",
        title_style="bold",
    )
    table.add_column("model", style="cyan")
    table.add_column("verified", justify="right")
    table.add_column("rate", justify="right")
    table.add_column("avg cost", justify="right")
    table.add_column("avg wall", justify="right")

    for row in result.leaderboard:
        if row.verified_rate >= 0.7:
            rate_style = "green"
        elif row.verified_rate >= 0.4:
            rate_style = "yellow"
        else:
            rate_style = "red"
        is_winner = result.winner is not None and row.model == result.winner.model
        table.add_row(
            f"{row.model} 🏆" if is_winner else row.model,
            f"{row.verified}/{row.runs}",
            Text(f"{row.verified_rate:.0%}", style=rate_style),
            _fmt_cost(row.avg_cost),
            f"{row.avg_wall_seconds:.1f}s",
            style="bold" if is_winner else None,
        )

    console.print(table)

    footer = Text()
    if result.winner is not None:
        footer.append(f"Winner: {result.winner.model}\n", style="bold green")
    else:
        footer.append("Winner: none (insufficient data)\n", style="bold yellow")
    if result.note:
        footer.append(f"note: {result.note}", style="dim italic")
    console.print(footer)
    return True


def register(app: typer.Typer) -> None:
    """Register the ``race`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("race")
    def race_command(
        goal: Annotated[
            str | None,
            typer.Argument(help="Goal to cluster receipts on (keyword overlap)."),
        ] = None,
        all_receipts: Annotated[
            bool,
            typer.Option("--all", help="Race every model over the whole receipt corpus."),
        ] = False,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the race result as JSON."),
        ] = False,
    ) -> None:
        """Offline model/strategy tournament over recorded run receipts.

        Clusters run receipts whose ``goal`` shares keywords with <goal>,
        builds a per-model leaderboard (runs, verified rate, avg cost, avg
        wall-time) ranked by verified rate then cost, and declares a
        tournament winner. Requires >= 3 verified runs in the cluster, else
        prints an honest "insufficient data" instead of guessing. Use --all
        for an overall leaderboard with no clustering. Deterministic and
        fully offline (no LLM call).
        """
        if not all_receipts and not goal:
            typer.echo("Provide a goal, or pass --all for the overall leaderboard.", err=True)
            raise typer.Exit(code=1)
        if all_receipts and goal:
            typer.echo("Pass either a goal or --all, not both.", err=True)
            raise typer.Exit(code=1)

        repo_root = _resolve_repo_root()
        receipts = load_receipts(repo_root, scope="project")
        result = race(receipts, query=None if all_receipts else goal)

        if as_json:
            typer.echo(json.dumps(result.to_dict()))
            return

        if not _render_rich(result):
            _render_plain(result)
