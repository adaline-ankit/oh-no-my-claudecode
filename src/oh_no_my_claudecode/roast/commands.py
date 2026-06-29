"""CLI surface for the ``roast`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. All rendering is inline here (a local Rich console
with a plain-text fallback) — no shared rendering/console/service hub is
touched. Storage is opened directly, mirroring the service's ``_load_context``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.config import (
    config_exists,
    create_state_dirs,
    database_path,
    load_config,
)
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.roast.scorer import RoastReport, compute_roast
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

_UPSELL = "Run `onmc mission harden-agent-readiness` to fix the worst gaps in one pass."


def _open_context() -> tuple[Path, SQLiteStorage]:
    """Resolve the repo root and open an initialised storage handle.

    Mirrors the service's ``_load_context`` precondition checks so the failure
    messages match the rest of the CLI, without routing through the service hub.
    """
    try:
        repo_root = discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        raise typer.Exit(code=1) from None
    if not config_exists(repo_root):
        typer.echo("ONMC is not initialized. Run `onmc init` first.", err=True)
        raise typer.Exit(code=1)
    config = load_config(repo_root)
    create_state_dirs(config, repo_root)
    storage = SQLiteStorage(database_path(config, repo_root))
    storage.initialize()
    return repo_root, storage


def _render_plain(report: RoastReport) -> None:
    """Emit the roast card as plain text (no Rich dependency)."""
    lines = [
        "",
        f"  onmc roast — agent-readiness: {report.score}/100  (grade {report.grade})",
        f"  brain: {report.memory_count} memories  |  "
        f"uncovered hotspots: {report.uncovered_hotspots}  |  "
        f"audit grade: {report.audit_grade}",
        "",
    ]
    for quip in report.quips:
        lines.append(f"  “{quip}”")
    if report.findings:
        lines.append("")
        lines.append("  The roast:")
        for finding in report.findings:
            lines.append(f"   • {finding}")
    else:
        lines.append("")
        lines.append("  No roast — this repo is genuinely agent-ready. Rare.")
    lines.append("")
    lines.append(f"  {_UPSELL}")
    lines.append("")
    typer.echo("\n".join(lines))


def _render_rich(report: RoastReport) -> bool:
    """Render the roast as a Rich card; return False if Rich is unavailable."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        return False

    grade_color = {
        "A": "bold green",
        "B": "green",
        "C": "yellow",
        "D": "orange3",
        "F": "bold red",
    }.get(report.grade, "white")

    body = Text()
    body.append(f"{report.score}", style=f"bold {grade_color}")
    body.append("/100", style="dim")
    body.append(f"   grade {report.grade}\n", style=grade_color)
    body.append(
        f"brain: {report.memory_count} memories   "
        f"uncovered hotspots: {report.uncovered_hotspots}   "
        f"audit: {report.audit_grade}\n",
        style="dim",
    )
    for quip in report.quips:
        body.append(f"\n“{quip}”", style="italic")

    if report.findings:
        body.append("\n\nThe roast:", style="bold")
        for finding in report.findings:
            body.append(f"\n  • {finding}")
    else:
        body.append("\n\nNo roast — this repo is genuinely agent-ready. Rare.", style="green")

    body.append(f"\n\n{_UPSELL}", style="bold cyan")

    Console().print(
        Panel(body, title="onmc roast", subtitle="agent-readiness", border_style=grade_color)
    )
    return True


def register(app: typer.Typer) -> None:
    """Register the ``roast`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("roast")
    def roast_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the roast report as JSON."),
        ] = False,
    ) -> None:
        """Roast this repo's agent-readiness — a blunt 0-100 score + findings.

        Deterministic and offline: composes hotspot memory coverage, the
        agent-config audit grade, brain size, and conventions presence into a
        single shareable score. Same repo always yields the same roast.
        """
        _, storage = _open_context()
        report = compute_roast(storage, Path.cwd())
        if as_json:
            typer.echo(json.dumps(report.to_dict()))
            return
        if not _render_rich(report):
            _render_plain(report)
