"""CLI surface for the ``drift`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time.  Rendering is inline (a local Rich table with a
plain-text fallback) — no shared rendering/console/service hub is touched.
Storage is opened directly, mirroring the ``roast`` command's ``_open_context``.
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
from oh_no_my_claudecode.drift.drift import (
    DriftReport,
    check_drift,
    default_file_text_provider,
)
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage


def _open_context() -> tuple[Path, SQLiteStorage]:
    """Resolve the repo root and open an initialised storage handle.

    Mirrors the ``roast`` command's context loader so failure messages match the
    rest of the CLI, without routing through the service hub.
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


def _render_plain(report: DriftReport) -> None:
    """Emit the drift report as plain text (no Rich dependency)."""
    lines = [
        "",
        f"  onmc drift — checked {report.checked} directive(s), "
        f"{len(report.findings)} candidate violation(s)",
        "",
    ]
    if report.findings:
        for f in report.findings:
            lines.append(f"  • [{f.confidence:.2f}] {f.statement}")
            lines.append(f"      signal:   {f.signal}")
            lines.append(f"      evidence: {f.evidence}")
            lines.append("")
    for note in report.notes:
        lines.append(f"  ({note})")
    lines.append("")
    lines.append("  Candidates for review — heuristic, not a proof. Confirm before acting.")
    lines.append("")
    typer.echo("\n".join(lines))


def _render_rich(report: DriftReport) -> bool:
    """Render the drift report as a Rich table; return False if Rich is absent."""
    try:
        from rich.console import Console
        from rich.table import Table
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        return False

    console = Console()
    title = (
        f"onmc drift — {len(report.findings)} candidate violation(s) "
        f"across {report.checked} directive(s)"
    )
    if report.findings:
        table = Table(title=title, header_style="bold", border_style="yellow")
        table.add_column("statement", overflow="fold", max_width=40)
        table.add_column("signal", overflow="fold", max_width=30)
        table.add_column("conf", justify="right")
        table.add_column("evidence", overflow="fold", max_width=44)
        for f in report.findings:
            conf_style = "bold red" if f.confidence >= 0.7 else "yellow"
            table.add_row(
                f.statement,
                f.signal,
                f"[{conf_style}]{f.confidence:.2f}[/{conf_style}]",
                f.evidence,
            )
        console.print(table)
    else:
        console.print(f"[green]{title}[/green]")

    for note in report.notes:
        console.print(f"[dim]({note})[/dim]")
    console.print(
        "[dim]Candidates for review — heuristic, not a proof. Confirm before acting.[/dim]"
    )
    return True


def register(app: typer.Typer) -> None:
    """Register the ``drift`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    drift_app = typer.Typer(
        help="Enforce institutional memory — flag CANDIDATE code violations of "
        "recorded decisions/invariants for review (heuristic, not a proof).",
        no_args_is_help=True,
    )

    @drift_app.command("check")
    def check_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the drift report as JSON."),
        ] = False,
        min_confidence: Annotated[
            float,
            typer.Option(
                "--min-confidence",
                min=0.0,
                max=1.0,
                help="Drop findings below this confidence (0.0-1.0).",
            ),
        ] = 0.0,
    ) -> None:
        """Scan code for CANDIDATE violations of recorded memory.

        For each decision/invariant/convention that carries a checkable
        directive ("never use X", "always use Y", "adopt Z", "prefer A over B"),
        scan the repo's Python files for contradicting evidence.  Findings are
        HEURISTIC candidates for human review — never a certainty. Deterministic
        and offline; degrades gracefully (empty brain → nothing to check).
        """
        repo_root, storage = _open_context()
        memories = storage.list_memories()
        provider = default_file_text_provider(repo_root)
        report = check_drift(memories, provider, min_confidence=min_confidence)
        if as_json:
            typer.echo(json.dumps(report.to_dict()))
            return
        if not _render_rich(report):
            _render_plain(report)

    app.add_typer(drift_app, name="drift")
