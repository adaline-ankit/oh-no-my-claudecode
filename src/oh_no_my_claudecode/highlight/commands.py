"""CLI surface for the ``highlight`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc highlight`` ships with **zero
edits** to ``cli.py`` or any other shared hub.

``onmc highlight`` mines verified run receipts for the BEST moments in a session
and renders a curated, ranked "best-of" recap — like a sports highlight reel.
Distinct from ``replay`` (full step-by-step) and ``timeline`` (chronological
milestones).

Outputs
-------
- Default: Rich-rendered table (falls back to plain text if Rich is absent).
- ``--json``: JSON envelope ``{"kind": "highlight", "reel": {...}}``.
- ``--markdown``: Shareable Markdown block.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.highlight.reel import Reel, build_reel, render_markdown

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_repo_root() -> Path:
    """Discover the repo root; fall back to cwd if discovery fails."""
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        return Path.cwd().resolve()


def _load_receipts(repo_root: Path) -> list[dict[str, Any]]:
    """Load all run receipts; return empty list on any failure."""
    try:
        from oh_no_my_claudecode.ledger.accounting import load_receipts

        return load_receipts(repo_root, scope="project")
    except Exception:  # noqa: BLE001
        return []


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 string to an aware UTC datetime; return None on failure."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _since_cutoff(since: str | None, now: datetime) -> datetime | None:
    """Parse a ``--since`` value into a UTC cutoff, or None for no filter.

    Accepts a relative duration (``7d``, ``48h``, ``30m``) or an ISO-8601
    date/datetime.  Returns ``None`` (and warns) when the value cannot be
    parsed, so an unparseable filter never silently drops all data.
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


def _render_plain(reel: Reel) -> None:
    """Render the reel as plain text (no Rich dependency)."""
    if not reel.moments:
        typer.echo("")
        typer.echo("  onmc highlight reel — no highlights yet")
        typer.echo("  Run `onmc loop` or `onmc swarm` to earn verified completions.")
        typer.echo("")
        return

    typer.echo("")
    typer.echo(
        f"  onmc highlight reel  |  {reel.total_verified} verified"
        f"  |  {reel.streak_days}-day streak"
    )
    typer.echo("")
    for m in reel.moments:
        typer.echo(f"  {m.headline}")
        if m.detail:
            typer.echo(f"    {m.detail}")
        typer.echo("")


def _render_rich(reel: Reel) -> bool:
    """Render the reel via Rich; return False if Rich is unavailable."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text
    except Exception:  # noqa: BLE001
        return False

    console = Console()

    if not reel.moments:
        console.print(
            "\n  [dim]onmc highlight reel — no highlights yet.[/dim]\n"
            "  Run [bold]onmc loop[/bold] or [bold]onmc swarm[/bold]"
            " to earn verified completions.\n"
        )
        return True

    table = Table(
        title=(
            f"onmc highlight reel  |  {reel.total_verified} verified"
            f"  |  {reel.streak_days}-day streak"
        ),
        title_style="bold",
        show_header=True,
    )
    table.add_column("moment", style="bold cyan", min_width=18)
    table.add_column("headline", min_width=40)
    table.add_column("detail", style="dim")

    emoji_map = {
        "trophy": "🏆",
        "skull": "💀",
        "fire": "🔥",
        "zap": "⚡",
        "lightning": "⚡",
    }

    for m in reel.moments:
        emoji = emoji_map.get(m.emoji, m.emoji)
        kind_text = Text(f"{emoji}  {m.kind}", style="bold")
        table.add_row(kind_text, m.headline, m.detail)

    console.print(table)
    return True


# ---------------------------------------------------------------------------
# Auto-discovery entry point
# ---------------------------------------------------------------------------


def register(app: typer.Typer) -> None:
    """Register the ``onmc highlight`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("highlight")
    def highlight_command(
        since: Annotated[
            str | None,
            typer.Option(
                "--since",
                help=(
                    "Only include runs since this point — "
                    "a relative window (7d, 48h, 30m) or ISO date (2026-07-01)."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            typer.Option(
                "--limit",
                help="Maximum number of highlight moments to show (default 5).",
                min=1,
                max=20,
            ),
        ] = 5,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the reel as a JSON envelope."),
        ] = False,
        as_markdown: Annotated[
            bool,
            typer.Option(
                "--markdown", help="Emit the reel as a shareable Markdown block."
            ),
        ] = False,
    ) -> None:
        """Curated highlight reel: the best moments from your verified runs.

        Mines verified run receipts for the most spectacular achievements —
        biggest win, boss kills, streaks, efficiency records, and speed runs —
        and renders them as a ranked "best-of" recap. Distinct from `replay`
        (step-by-step) and `timeline` (chronological narrative).

        Deterministic and fully offline (no LLM call). An empty receipt store
        prints a "no highlights yet" note and exits 0.

        Examples:

            onmc highlight                  # rich table (plain text fallback)

            onmc highlight --since 7d       # only runs from the last 7 days

            onmc highlight --limit 3        # top 3 moments only

            onmc highlight --markdown       # shareable Markdown block

            onmc highlight --json           # JSON envelope for pipelines
        """
        now = datetime.now(UTC)
        repo_root = _resolve_repo_root()
        receipts = _load_receipts(repo_root)
        cutoff = _since_cutoff(since, now)

        reel = build_reel(receipts, now=now, limit=limit, since=cutoff)

        if as_json:
            payload = json.dumps({"kind": "highlight", "reel": reel.to_dict()})
            typer.echo(payload)
            return

        if as_markdown:
            typer.echo(render_markdown(reel))
            return

        if not _render_rich(reel):
            _render_plain(reel)
