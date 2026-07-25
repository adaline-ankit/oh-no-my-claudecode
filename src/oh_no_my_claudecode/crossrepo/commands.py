"""CLI surface for the ``crossrepo`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time.  Rendering is inline (a local Rich console with a
plain-text fallback) — no shared rendering/console/service hub is touched, and
no other feature module is modified.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.crossrepo.crossrepo import (
    CROSSREPO_PROVENANCE_NOTE,
    CrossRepoMap,
    RecallHit,
    federated_recall,
    scan_repos,
)

#: Inline marker prefixed to a hit the origin repo had quarantined.  Cross-repo
#: recall never drops such a hit — it just refuses to show it as reviewed.
#: Deliberately bracket-free: Rich parses ``[...]`` as markup and would swallow
#: the label instead of printing it.
_UNPROMOTED_MARKER = "⚠ unpromoted in origin repo —"

crossrepo_app = typer.Typer(
    name="crossrepo",
    help="Cross-repo brain: impact map + federated memory recall across sibling repos.",
    no_args_is_help=True,
)


def _resolve_paths(raw: list[str]) -> list[Path]:
    """Normalise raw path strings to expanded :class:`Path` objects.

    Deduplication and existence checks are left to the pure layer so the same
    ``skipped`` notes surface consistently between the CLI and library callers.
    """
    return [Path(value).expanduser() for value in raw]


# ---------------------------------------------------------------------------
# Rendering (inline, local console with plain fallback)
# ---------------------------------------------------------------------------


def _render_scan_plain(result: CrossRepoMap) -> None:
    """Emit the impact map as plain text (no Rich dependency)."""
    lines = ["", "  onmc crossrepo — impact map", ""]
    if result.repos:
        lines.append(f"  repos scanned: {len(result.repos)}")
        for repo in result.repos:
            module_list = ", ".join(repo.modules) if repo.modules else "(no modules)"
            lines.append(f"   • {repo.name}: {module_list}")
    else:
        lines.append("  No usable repos scanned.")
    lines.append("")
    if result.impacts:
        lines.append(f"  shared modules (ripple surface): {len(result.impacts)}")
        for impact in result.impacts:
            lines.append(f"   ⇄ {impact.shared_module}  →  {', '.join(impact.repos)}")
    else:
        lines.append("  No shared modules — these repos don't ripple into each other.")
    if result.skipped:
        lines.append("")
        lines.append("  skipped:")
        for path, reason in result.skipped:
            lines.append(f"   × {path} ({reason})")
    lines.append("")
    typer.echo("\n".join(lines))


def _render_scan_rich(result: CrossRepoMap) -> bool:
    """Render the impact map as a Rich table; return False if Rich is unavailable."""
    try:
        from rich.console import Console
        from rich.table import Table
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        return False

    console = Console()
    repo_table = Table(title="onmc crossrepo — repos", show_lines=False)
    repo_table.add_column("repo", style="bold")
    repo_table.add_column("top-level modules")
    if result.repos:
        for repo in result.repos:
            repo_table.add_row(repo.name, ", ".join(repo.modules) or "[dim](none)[/dim]")
    else:
        repo_table.add_row("[dim](none)[/dim]", "[dim]no usable repos[/dim]")
    console.print(repo_table)

    impact_table = Table(title="ripple surface — shared modules", border_style="cyan")
    impact_table.add_column("shared module", style="bold cyan")
    impact_table.add_column("appears in")
    if result.impacts:
        for impact in result.impacts:
            impact_table.add_row(impact.shared_module, ", ".join(impact.repos))
    else:
        impact_table.add_row("[dim](none)[/dim]", "[dim]no cross-repo ripple[/dim]")
    console.print(impact_table)

    if result.skipped:
        for path, reason in result.skipped:
            console.print(f"[yellow]skipped[/yellow] {path} [dim]({reason})[/dim]")
    return True


def _render_recall_plain(hits: list[RecallHit], query: str) -> None:
    """Emit federated recall hits as plain text, provenance first.

    The provenance note precedes the hits so a reader — human or agent — sees
    that this is unreviewed cross-repo content before reading any of it, and a
    hit quarantined in its origin repo is marked inline rather than dropped.
    """
    lines = ["", f"  onmc crossrepo recall — “{query}”", ""]
    if not hits:
        lines.append("  No matching memories across the given repos.")
    else:
        lines.append(f"  ⚠ {CROSSREPO_PROVENANCE_NOTE}")
        lines.append("")
        lines.append(f"  {len(hits)} hit(s):")
        for hit in hits:
            marker = f" {_UNPROMOTED_MARKER}" if hit.unpromoted else ""
            lines.append(f"   [{hit.repo}] ({hit.score}){marker} {hit.title}")
            if hit.summary:
                lines.append(f"        {hit.summary}")
    lines.append("")
    typer.echo("\n".join(lines))


def _render_recall_rich(hits: list[RecallHit], query: str) -> bool:
    """Render federated recall hits as a Rich table; return False if unavailable.

    Carries the same provenance as the plain renderer: a standing caption for
    the whole result set plus a per-row marker for hits their origin repo had
    quarantined.
    """
    try:
        from rich.console import Console
        from rich.table import Table
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        return False

    console = Console()
    table = Table(
        title=f"onmc crossrepo recall — “{query}”",
        caption=f"⚠ {CROSSREPO_PROVENANCE_NOTE}",
        caption_style="yellow",
        border_style="green",
    )
    table.add_column("repo", style="bold")
    table.add_column("score", justify="right", style="dim")
    table.add_column("memory")
    if not hits:
        table.add_row("[dim](none)[/dim]", "", "[dim]no matches[/dim]")
    else:
        for hit in hits:
            memory_cell = hit.title
            if hit.unpromoted:
                memory_cell = f"[yellow]{_UNPROMOTED_MARKER}[/yellow] {memory_cell}"
            if hit.summary:
                memory_cell += f"\n[dim]{hit.summary}[/dim]"
            table.add_row(hit.repo, str(hit.score), memory_cell)
    console.print(table)
    return True


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@crossrepo_app.command("scan")
def scan_command(
    paths: Annotated[
        list[str],
        typer.Argument(help="Sibling repo paths to scan for the cross-repo impact map."),
    ],
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the impact map as JSON."),
    ] = False,
) -> None:
    """Map where a change in one repo ripples into its siblings.

    Scans each repo's top-level module/package names and reports the modules
    shared across two or more repos — the ripple surface. Deterministic and
    offline: same repos always yield the same map.
    """
    result = scan_repos(_resolve_paths(paths))
    if as_json:
        typer.echo(json.dumps(result.to_dict()))
        return
    if not _render_scan_rich(result):
        _render_scan_plain(result)


@crossrepo_app.command("recall")
def recall_command(
    query: Annotated[str, typer.Argument(help="Search query for federated memory recall.")],
    repos: Annotated[
        list[str] | None,
        typer.Option("--repo", "-r", help="Repo path to search (repeatable)."),
    ] = None,
    paths: Annotated[
        list[str] | None,
        typer.Argument(help="Additional repo paths to search (positional)."),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit recall hits as JSON."),
    ] = False,
) -> None:
    """Search every repo's ``.agent-memory/`` export for a query, attributed by repo.

    Loads each repo's memory export (skipping repos without one), ranks hits by
    deterministic token overlap, and reports the best matches with their source
    repo. Pass repos via ``--repo`` (repeatable) and/or positional paths.

    Results are unreviewed cross-repo content and are labelled as such; a memory
    quarantined in its origin repo is marked, never silently dropped. ``--json``
    carries the same signal per hit as ``unpromoted`` / ``provenance``.
    """
    raw = list(repos or []) + list(paths or [])
    if not raw:
        typer.echo("No repos given. Pass paths positionally or via --repo.", err=True)
        raise typer.Exit(code=1)
    hits = federated_recall(_resolve_paths(raw), query)
    if as_json:
        typer.echo(json.dumps([hit.to_dict() for hit in hits]))
        return
    if not _render_recall_rich(hits, query):
        _render_recall_plain(hits, query)


def register(app: typer.Typer) -> None:
    """Register the ``crossrepo`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(crossrepo_app, name="crossrepo")
