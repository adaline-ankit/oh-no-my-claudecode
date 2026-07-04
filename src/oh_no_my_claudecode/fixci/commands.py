"""CLI surface for the ``fix-ci`` feature — auto-discovered.

Defines a top-level ``register(app)`` callable that the registry (see
:mod:`oh_no_my_claudecode.command_registry`) invokes at CLI build time, wiring
the ``onmc fix-ci`` command with **zero** edits to ``cli.py`` or any other
shared hub. Rendering is done inline here (Rich with a plain-text fallback).

``onmc fix-ci <pr> [--log <file>] [--json]``
    Read a failed PR's CI log, extract the failing step + error, recall related
    past dead-ends, map to likely-fix files, and print a fix plan. Plan-only —
    nothing is spawned. ``--log`` feeds a log file (offline); otherwise the log
    is fetched via the ``gh`` CLI.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.fixci.autopilot import CiFailure, fetch_ci_log, plan_ci_fix
from oh_no_my_claudecode.storage import SQLiteStorage


def _resolve_repo_root() -> Path:
    """Discover the repo root, falling back to CWD if discovery fails."""
    from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root

    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        return Path.cwd().resolve()


def _open_storage() -> SQLiteStorage | None:
    """Best-effort handle on the repo's SQLite store.

    Returns ``None`` when onmc is not initialised in this repo, so the plan
    degrades gracefully (no recalled dead-ends). Never raises.
    """
    try:
        from oh_no_my_claudecode.cli import _service

        _repo_root, _config, storage = _service()._load_context()  # noqa: SLF001
    except Exception:  # noqa: BLE001 - missing init / any error → no recall source
        return None
    return storage


def _render_plain(failure: CiFailure) -> None:
    """Emit the plan as plain text (no Rich dependency)."""
    typer.echo("onmc fix-ci — plan (plan-only; nothing was spawned)")
    typer.echo(f"  failing step : {failure.failing_step or '(none found)'}")
    typer.echo("  error        :")
    for line in (failure.error_excerpt or "(none found)").splitlines() or ["(none found)"]:
        typer.echo(f"    {line}")
    typer.echo("  likely files :")
    if failure.likely_files:
        for path in failure.likely_files:
            typer.echo(f"    - {path}")
    else:
        typer.echo("    (no code-graph match)")
    typer.echo("  dead-ends    :")
    if failure.dead_ends:
        for dead_end in failure.dead_ends:
            typer.echo(f"    - {dead_end}")
    else:
        typer.echo("    (none recalled)")
    typer.echo(f"  suggested fix: {failure.suggested_fix}")
    if failure.swarm_unit:
        typer.echo(f"  swarm unit   : {failure.swarm_unit}")


def _render_rich(failure: CiFailure) -> bool:
    """Render the plan as a Rich table; return False if Rich is unavailable."""
    try:
        from rich.console import Console
        from rich.table import Table
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        return False

    table = Table(title="onmc fix-ci — plan (plan-only)", show_header=True)
    table.add_column("field", style="bold cyan", no_wrap=True)
    table.add_column("value", overflow="fold")
    table.add_row("failing step", failure.failing_step or "(none found)")
    table.add_row("error", failure.error_excerpt or "(none found)")
    table.add_row(
        "likely files",
        "\n".join(failure.likely_files) if failure.likely_files else "(no code-graph match)",
    )
    table.add_row(
        "dead-ends",
        "\n".join(failure.dead_ends) if failure.dead_ends else "(none recalled)",
    )
    table.add_row("suggested fix", failure.suggested_fix)
    if failure.swarm_unit:
        table.add_row("swarm unit", failure.swarm_unit)
    Console().print(table)
    return True


def register(app: typer.Typer) -> None:
    """Register the ``fix-ci`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("fix-ci")
    def fix_ci_command(
        pr: Annotated[
            str,
            typer.Argument(help="PR number or URL whose failed CI to plan a fix for."),
        ],
        log: Annotated[
            Path | None,
            typer.Option(
                "--log",
                help="Read the CI log from this file instead of fetching via gh (offline).",
                exists=False,
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the fix plan as JSON."),
        ] = False,
    ) -> None:
        """Read a failed PR's CI log and emit a deterministic fix plan.

        Plan-only by default: this command never spawns an agent or runs a
        swarm. Use ``--log <file>`` to plan offline from a captured log; without
        it the log is fetched via ``gh run view --log-failed``.
        """
        if log is not None:
            try:
                log_text = log.read_text(encoding="utf-8")
            except OSError as exc:
                typer.echo(f"onmc fix-ci: cannot read log file {log}: {exc}", err=True)
                raise typer.Exit(code=1) from exc
        else:
            log_text = fetch_ci_log(pr)

        repo_root = _resolve_repo_root()
        storage = _open_storage()
        if storage is None:
            # Plan without recall — still produces step/error/likely-files.
            storage = SQLiteStorage(repo_root / ".onmc" / "ephemeral-fixci.db")
            with contextlib.suppress(Exception):
                # Recall is optional; a store that can't open must not block planning.
                storage.initialize()

        failure = plan_ci_fix(storage, repo_root, log_text=log_text, pr=pr)

        if as_json:
            typer.echo(json.dumps(failure.to_dict()))
            return
        if not _render_rich(failure):
            _render_plain(failure)
