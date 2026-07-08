"""CLI surface for ``onmc doctor`` — auto-discovered.

Follows the auto-discovery convention: a top-level :func:`register` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time, so ``onmc doctor`` ships with **zero edits** to
``cli.py`` or any other shared hub.

``onmc doctor`` diagnoses whether onmc is correctly integrated with Claude Code
and prints a Rich table of checks with actionable fixes — modelled after
``brew doctor``.

Examples::

    onmc doctor          # human-readable Rich table + summary
    onmc doctor --json   # machine-readable JSON envelope
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.doctor.checks import CHECK_LABELS, CheckResult, run_all_checks

# Status display strings and Rich markup colours.
_STATUS_LABEL: dict[str, str] = {
    "ok": "[green]ok[/green]",
    "warn": "[yellow]warn[/yellow]",
    "fail": "[red]fail[/red]",
}


def _render_table(results: list[CheckResult]) -> None:
    """Print a Rich table of check results plus a summary and fix list."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="onmc doctor", show_header=True, header_style="bold")
    table.add_column("Check", style="dim", no_wrap=True)
    table.add_column("Status", justify="center", no_wrap=True)
    table.add_column("Detail")

    for r in results:
        label = CHECK_LABELS.get(r.name, r.name)
        status_markup = _STATUS_LABEL.get(r.status, r.status)
        table.add_row(label, status_markup, r.detail)

    console.print(table)

    counts = {s: sum(1 for r in results if r.status == s) for s in ("ok", "warn", "fail")}
    summary_parts = []
    if counts["ok"]:
        summary_parts.append(f"[green]{counts['ok']} ok[/green]")
    if counts["warn"]:
        summary_parts.append(f"[yellow]{counts['warn']} warn[/yellow]")
    if counts["fail"]:
        summary_parts.append(f"[red]{counts['fail']} fail[/red]")
    console.print("  " + ", ".join(summary_parts))

    fixes = [(r.name, r.fix) for r in results if r.fix is not None]
    if fixes:
        console.print("\n[bold]Fixes:[/bold]")
        for name, fix in fixes:
            label = CHECK_LABELS.get(name, name)
            console.print(f"  [dim]{label}[/dim]: {fix}")
    console.print("")


def _build_json(results: list[CheckResult]) -> str:
    counts = {s: sum(1 for r in results if r.status == s) for s in ("ok", "warn", "fail")}
    payload = {
        "kind": "doctor",
        "checks": [r.to_dict() for r in results],
        "summary": counts,
    }
    return json.dumps(payload, indent=2)


def register(app: typer.Typer) -> None:
    """Register the ``onmc doctor`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("doctor")
    def doctor_command(
        as_json: Annotated[
            bool,
            typer.Option(
                "--json",
                help=(
                    "Emit a machine-readable JSON envelope "
                    '{"kind": "doctor", "checks": [...], "summary": {...}}'
                    " for pipeline composition."
                ),
            ),
        ] = False,
    ) -> None:
        """Diagnose onmc integration with Claude Code and print actionable fixes.

        Runs six checks and reports each as ok, warn, or fail:

        1. **initialized**  — ``.onmc/memory.db`` present (onmc init was run).
        2. **version**      — installed package version.
        3. **on PATH**      — ``onmc`` binary visible on PATH.
        4. **hooks**        — Claude Code lifecycle hooks wired in settings.json.
        5. **MCP**          — onmc MCP server registered in ``.mcp.json``.
        6. **wrap**         — ``/onmc`` slash command installed + deep-wrap state.

        Exit code 0 when no check fails, 1 when any check fails.

        Examples:

            onmc doctor              # human-readable table

            onmc doctor --json       # machine-readable JSON
        """
        try:
            from oh_no_my_claudecode.core.repo import discover_repo_root

            repo_root: Path | None = discover_repo_root(Path.cwd())
        except Exception:  # noqa: BLE001
            repo_root = None

        results = run_all_checks(repo_root)

        if as_json:
            typer.echo(_build_json(results))
        else:
            _render_table(results)

        if any(r.status == "fail" for r in results):
            raise typer.Exit(code=1)
