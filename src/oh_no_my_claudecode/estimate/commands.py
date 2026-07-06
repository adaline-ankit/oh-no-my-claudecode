"""CLI surface for the ``estimate`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. Rendering is inline (a local Rich table with a
plain-text fallback), mirroring ``race.commands`` / ``flywheel.commands`` — no
shared rendering hub is touched. Receipts are read via the ledger's own
loader; nothing in ``ledger/`` is modified.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.estimate.estimate import Estimate, build_estimate, render_text
from oh_no_my_claudecode.ledger.accounting import load_receipts


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


def _render_rich(estimate: Estimate) -> bool:
    """Render *estimate* as a Rich panel; return False if Rich is unavailable."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        return False

    console = Console()
    title = f"onmc estimate — '{estimate.goal}'"
    if estimate.model:
        title += f" (model: {estimate.model})"

    if estimate.fallback == "empty":
        console.print(Text(title, style="bold"))
        console.print(Text("ESTIMATE from historical data — no run history found at all."))
        console.print(Text(f"note: {estimate.note}", style="dim italic"))
        return True

    table = Table(title=title, title_style="bold")
    table.add_column("metric", style="cyan")
    table.add_column("expected", justify="right")
    table.add_column("range", justify="right")

    ew = estimate.expected_wall_seconds
    ei = estimate.expected_iterations
    table.add_row("cost", _fmt_cost(estimate.expected_cost_usd), _fmt_range_money(estimate))
    table.add_row(
        "wall time",
        "n/a" if ew is None else f"{ew:g}s",
        _fmt_range_wall(estimate),
    )
    table.add_row(
        "iterations",
        "n/a" if ei is None else f"{ei:g}",
        _fmt_range_iter(estimate),
    )
    vp = estimate.verified_probability
    table.add_row("probability verified", "n/a" if vp is None else f"{vp:.0%}", "")

    console.print(table)

    basis = {
        "none": "similar past runs",
        "overall": "overall corpus (fallback — too few similar runs)",
    }.get(estimate.fallback, "similar past runs")
    footer = Text()
    footer.append(
        f"sample: {estimate.sample_size} run(s) — basis: {basis} — "
        f"confidence: {estimate.confidence}\n",
        style="bold" if estimate.confidence == "high" else "yellow",
    )
    if estimate.matched_keywords:
        footer.append(f"matched keywords: {', '.join(estimate.matched_keywords)}\n")
    footer.append("ESTIMATE from historical data — not a guarantee\n", style="bold")
    footer.append(f"note: {estimate.note}", style="dim italic")
    console.print(footer)
    return True


def _fmt_range_money(estimate: Estimate) -> str:
    rng = estimate.cost_range
    if rng.low is None or rng.high is None:
        return "n/a"
    return f"${rng.low:.4f} - ${rng.high:.4f}"


def _fmt_range_wall(estimate: Estimate) -> str:
    rng = estimate.wall_seconds_range
    if rng.low is None or rng.high is None:
        return "n/a"
    return f"{rng.low:g}s - {rng.high:g}s"


def _fmt_range_iter(estimate: Estimate) -> str:
    rng = estimate.iterations_range
    if rng.low is None or rng.high is None:
        return "n/a"
    return f"{rng.low:g} - {rng.high:g}"


def register(app: typer.Typer) -> None:
    """Register the ``estimate`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("estimate")
    def estimate_command(
        goal: Annotated[
            str,
            typer.Argument(help="Goal to forecast a run for (keyword-matched against history)."),
        ],
        model: Annotated[
            str | None,
            typer.Option("--model", help="Condition the estimate on a specific model."),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the estimate as JSON."),
        ] = False,
    ) -> None:
        """Predict cost/time/outcome for <goal> from similar past runs.

        Clusters recorded run receipts whose ``goal`` shares keywords with
        <goal> (same keyword-overlap approach as ``onmc race`` / ``onmc
        flywheel``) and forecasts expected cost (median + range), expected
        wall time, expected iterations, and probability-of-verified from that
        cluster. Requires >= 3 similar runs for a confident estimate; below
        that, honestly falls back to overall-corpus averages (or "no history"
        when there are no receipts at all) rather than guessing. Every number
        is explicitly labelled as an ESTIMATE derived from historical data.
        Deterministic and fully offline (no LLM call).
        """
        repo_root = _resolve_repo_root()
        receipts = load_receipts(repo_root, scope="project")
        estimate = build_estimate(receipts, goal, model=model)

        if as_json:
            typer.echo(json.dumps(estimate.to_dict()))
            return

        if not _render_rich(estimate):
            typer.echo(render_text(estimate))
