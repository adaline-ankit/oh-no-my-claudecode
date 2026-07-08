"""CLI surface for ``onmc doctor`` — auto-discovered.

Follows the auto-discovery convention: a top-level :func:`register` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time, so ``onmc doctor`` ships with **zero edits** to
``cli.py`` or any other shared hub.

``onmc doctor`` is a **superset** that combines two health-check layers:

1. **Integration checks** — six Claude-Code-integration diagnostics (init,
   version, PATH, hooks, MCP, /onmc wrap command) implemented in
   :mod:`oh_no_my_claudecode.doctor.checks`.
2. **Repo health** — the legacy ``OnmcService.doctor()`` report (repo / memory
   / provider / sync / warnings), surfaced unchanged.

Both layers are rendered together.  Exit code 1 when any integration check
is ``fail`` **or** the legacy ``ok`` flag is ``False``.  If
``OnmcService.doctor()`` raises (e.g. repo not initialised), the repo-health
section degrades gracefully — integration checks are still shown.

Examples::

    onmc doctor          # human-readable Rich table + repo-health panel
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
    table = Table(title="onmc doctor — integration checks", show_header=True, header_style="bold")
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


def _build_json(
    results: list[CheckResult],
    repo_health_ok: bool | None,
    repo_health_report: dict[str, list[str]] | None,
) -> str:
    counts = {s: sum(1 for r in results if r.status == s) for s in ("ok", "warn", "fail")}

    repo_health: dict[str, object] | None = None
    if repo_health_report is not None:
        repo_health = {"ok": repo_health_ok, **repo_health_report}

    payload: dict[str, object] = {
        "kind": "doctor",
        "integration": [r.to_dict() for r in results],
        "repo_health": repo_health,
        "summary": counts,
    }
    return json.dumps(payload, indent=2)


def _run_repo_health(
    repo_root: Path,
) -> tuple[bool | None, dict[str, list[str]] | None]:
    """Call ``OnmcService.doctor()`` and return ``(ok, report)``.

    Returns ``(None, None)`` when the service raises for any reason (e.g.
    the repo is not yet initialised).  Never propagates exceptions.
    """
    try:
        from oh_no_my_claudecode.core.service import OnmcService

        service = OnmcService(repo_root)
        ok, report = service.doctor()
        return ok, report
    except Exception:  # noqa: BLE001
        return None, None


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
                    '{"kind":"doctor","integration":[...],"repo_health":{...},"summary":{...}}'
                    " for pipeline composition."
                ),
            ),
        ] = False,
    ) -> None:
        """Diagnose onmc integration with Claude Code — repo, memory, and provider health.

        Combines two check layers:

        **Integration checks** (six Claude Code diagnostics):

        1. **initialized**  — ``.onmc/memory.db`` present (onmc init was run).
        2. **version**      — installed package version.
        3. **on PATH**      — ``onmc`` binary visible on PATH.
        4. **hooks**        — Claude Code lifecycle hooks wired in settings.json.
        5. **MCP**          — onmc MCP server registered in ``.mcp.json``.
        6. **wrap**         — ``/onmc`` slash command installed + deep-wrap state.

        **Repo health** — git repo, memory records, provider config, sync state.

        Exit code 0 when no check fails and repo health is ok.
        Exit code 1 when any integration check fails or repo health reports errors.

        Examples:

            onmc doctor              # human-readable table + health panel

            onmc doctor --json       # machine-readable JSON
        """
        try:
            from oh_no_my_claudecode.core.repo import discover_repo_root

            repo_root: Path | None = discover_repo_root(Path.cwd())
        except Exception:  # noqa: BLE001
            repo_root = None

        # --- integration checks ---
        results = run_all_checks(repo_root)

        # --- repo health (legacy service.doctor()) ---
        repo_health_ok: bool | None = None
        repo_health_report: dict[str, list[str]] | None = None
        if repo_root is not None:
            repo_health_ok, repo_health_report = _run_repo_health(repo_root)

        if as_json:
            typer.echo(_build_json(results, repo_health_ok, repo_health_report))
        else:
            _render_table(results)
            if repo_health_report is not None:
                from oh_no_my_claudecode.rendering.console import render_doctor_report

                render_doctor_report(repo_health_ok or False, repo_health_report)
            elif repo_root is not None:
                # Repo exists but service.doctor() raised (not initialised yet).
                typer.echo(
                    "  [repo health unavailable — run `onmc init` to initialise]",
                )

        # Exit 1 if any integration check failed OR repo health reports errors.
        has_fail = any(r.status == "fail" for r in results)
        if has_fail or repo_health_ok is False:
            raise typer.Exit(code=1)
