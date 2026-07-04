"""CLI surface for the ``twin`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc twin`` ships with **zero
edits** to ``cli.py`` or any other shared hub.  Rendering is done inline here
(a local Rich console with a plain-text fallback).

``onmc twin plan <paths...>``      — tabulate the blast radius of a change.
``onmc twin rehearse <paths...>``  — the same table plus a before-you-edit
                                     advisory summary.

This is **analysis only**: ``twin`` never executes code and never edits files.
It reads the offline structural code graph to predict *what would break*.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.twin.twin import RehearsalPlan, build_rehearsal

twin_app = typer.Typer(
    help=(
        "Rehearse a code change offline: predict blast radius, surface covering "
        "tests, flag high-risk touches. Analysis only — never runs or edits code."
    ),
    no_args_is_help=True,
)


def _resolve_repo_root() -> Path:
    """Resolve the repo root from the current working directory.

    Mirrors the other feature commands' resolution + failure message so the CLI
    behaves consistently, without routing through a shared service hub.
    """
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _suggested_test_command(plan: RehearsalPlan) -> str | None:
    """Return a runnable pytest command for the suggested tests, if any."""
    if not plan.suggested_tests:
        return None
    return "pytest " + " ".join(plan.suggested_tests)


def _render_plain(plan: RehearsalPlan, *, advisory: bool) -> None:
    """Emit the rehearsal as plain text (no Rich dependency)."""
    lines = ["", "  onmc twin — change rehearsal (analysis only, nothing executed)", ""]
    if plan.note:
        lines.append(f"  note: {plan.note}")
        lines.append("")
    for tf in plan.touched:
        lines.append(
            f"  {tf.path}  [{tf.risk}]  "
            f"{len(tf.dependents)} dependents, {len(tf.covering_tests)} covering tests"
        )
    lines.append("")
    lines.append(f"  total blast radius: {plan.total_blast} file(s)")
    if plan.high_risk:
        lines.append(f"  HIGH RISK: {', '.join(plan.high_risk)}")
    test_cmd = _suggested_test_command(plan)
    if test_cmd:
        lines.append(f"  suggested tests: {test_cmd}")
    if advisory:
        lines.append("")
        lines.extend(f"  {line}" for line in _advisory_lines(plan))
    lines.append("")
    typer.echo("\n".join(lines))


def _advisory_lines(plan: RehearsalPlan) -> list[str]:
    """Build the 'before you edit' advisory bullet list."""
    out = ["Before you edit:"]
    test_cmd = _suggested_test_command(plan)
    if test_cmd:
        out.append(f" • run these tests first: {test_cmd}")
    else:
        out.append(" • no covering tests found — consider adding one before editing.")
    if plan.total_blast:
        out.append(f" • watch {plan.total_blast} dependent file(s) for breakage.")
    else:
        out.append(" • no dependents in the graph — blast radius is contained.")
    if plan.high_risk:
        out.append(f" • HIGH RISK (hub files, many dependents): {', '.join(plan.high_risk)}")
    return out


def _render_rich(plan: RehearsalPlan, *, advisory: bool) -> bool:
    """Render the rehearsal as a Rich table; return False if Rich is missing."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        return False

    console = Console()
    table = Table(title="onmc twin — change rehearsal (analysis only)")
    table.add_column("touched file", style="bold")
    table.add_column("#dependents", justify="right")
    table.add_column("risk")
    table.add_column("covering tests")

    for tf in plan.touched:
        risk_style = "bold red" if tf.risk == "high" else "green"
        covering = "\n".join(tf.covering_tests) if tf.covering_tests else "—"
        table.add_row(
            tf.path,
            str(len(tf.dependents)),
            Text(tf.risk, style=risk_style),
            covering,
        )
    console.print(table)

    if plan.note:
        console.print(Text(plan.note, style="yellow"))
    console.print(f"total blast radius: [bold]{plan.total_blast}[/bold] file(s)")
    test_cmd = _suggested_test_command(plan)
    if test_cmd:
        console.print(f"suggested tests: [cyan]{test_cmd}[/cyan]")

    if advisory:
        body = Text()
        for line in _advisory_lines(plan):
            body.append(f"{line}\n")
        try:
            from rich.panel import Panel

            console.print(Panel(body, title="advisory", border_style="cyan"))
        except Exception:  # noqa: BLE001 - Panel is optional; plain print is fine
            console.print(body)
    return True


def _run(paths: list[str], *, as_json: bool, advisory: bool) -> None:
    """Shared body for ``plan`` and ``rehearse``."""
    repo_root = _resolve_repo_root()
    plan = build_rehearsal(repo_root, paths)
    if as_json:
        typer.echo(json.dumps(plan.to_dict()))
        return
    if not _render_rich(plan, advisory=advisory):
        _render_plain(plan, advisory=advisory)


def register(app: typer.Typer) -> None:
    """Register the ``onmc twin`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(twin_app, name="twin")


@twin_app.command("plan")
def twin_plan_command(
    paths: Annotated[
        list[str],
        typer.Argument(help="Repo-relative (or absolute) files you intend to edit."),
    ],
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the rehearsal plan as JSON."),
    ] = False,
) -> None:
    """Predict the blast radius of touching PATHS — before you edit.

    Offline analysis against the structural code graph: per file, shows how many
    files depend on it, its risk level, and the tests that cover it, plus a
    suggested test command.  Never runs or edits any code.  If the graph is
    empty, run `onmc codegraph` first.
    """
    _run(paths, as_json=as_json, advisory=False)


@twin_app.command("rehearse")
def twin_rehearse_command(
    paths: Annotated[
        list[str],
        typer.Argument(help="Repo-relative (or absolute) files you intend to edit."),
    ],
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the rehearsal plan as JSON."),
    ] = False,
) -> None:
    """Rehearse touching PATHS with an explicit before-you-edit advisory.

    Same blast-radius table as `twin plan`, plus a spelled-out summary: which
    tests to run first, how many dependents to watch, and any HIGH-RISK hub
    files.  Pure analysis — nothing is executed or edited.  If the graph is
    empty, run `onmc codegraph` first.
    """
    _run(paths, as_json=as_json, advisory=True)
