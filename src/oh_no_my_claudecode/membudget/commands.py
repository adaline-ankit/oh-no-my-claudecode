"""CLI surface for the ``membudget`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc membudget`` ships with **zero
edits** to ``cli.py`` or any other shared hub.

``onmc membudget`` inspects the onmc memory store, reports total byte size with
a per-kind breakdown, flags when the store exceeds a configurable budget, and
SUGGESTS concrete consolidation actions (merge near-duplicates, move verbose
entries to topic files, drop stale entries).

Pure stdlib — advisory only, never deletes, deterministic, offline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.membudget.analyzer import DEFAULT_LIMIT_BYTES, BudgetReport, analyze

if TYPE_CHECKING:
    from oh_no_my_claudecode.storage import SQLiteStorage

membudget_app = typer.Typer(
    help=(
        "Memory-budget guard: report store size, flag over-budget, suggest consolidations."
    ),
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Register the ``onmc membudget`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(membudget_app, name="membudget")


def _load_storage(repo_root: Path) -> SQLiteStorage:
    """Load the SQLite storage for *repo_root*.

    Raises :class:`typer.Exit` with code 1 when onmc is not initialised.
    """
    from oh_no_my_claudecode.config import config_exists, database_path, load_config
    from oh_no_my_claudecode.storage import SQLiteStorage

    if not config_exists(repo_root):
        typer.echo("error: onmc is not initialized in this repo. Run `onmc init` first.", err=True)
        raise typer.Exit(code=1)

    config = load_config(repo_root)
    storage = SQLiteStorage(database_path(config, repo_root))
    storage.initialize()
    return storage


def _fmt_bytes(n: int) -> str:
    """Human-readable byte size (KiB / MiB / B)."""
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MiB"
    if n >= 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n} B"


def _render_plain(report: BudgetReport) -> None:
    """Render *report* as human-readable plain text to stdout."""
    status = "OVER BUDGET" if report.over_budget else "OK"
    typer.echo(f"\n  onmc membudget  [{status}]\n")
    typer.echo(f"  total size   : {_fmt_bytes(report.total_bytes)} ({report.total_bytes} bytes)")
    typer.echo(f"  budget limit : {_fmt_bytes(report.limit_bytes)} ({report.limit_bytes} bytes)")
    typer.echo(f"  budget used  : {report.budget_used_pct}%")
    typer.echo(f"  entries      : {report.entry_count}")

    if report.breakdown:
        typer.echo("\n  Per-kind breakdown:")
        for bd in report.breakdown:
            typer.echo(
                f"    {bd.kind:<20}  {bd.entry_count:>4} entries  "
                f"{_fmt_bytes(bd.byte_size):>10}"
            )

    if not report.suggestions:
        typer.echo("\n  No consolidation suggestions.\n")
        return

    typer.echo(f"\n  Consolidation suggestions ({len(report.suggestions)} total):")
    typer.echo(
        f"    {report.drop_count} drop-stale  "
        f"  {report.merge_count} merge-duplicates  "
        f"  {report.move_count} move-to-topic"
    )
    typer.echo("")
    for sug in report.suggestions:
        typer.echo(f"  [{sug.kind.value.upper():<18}]  {sug.description}")
    typer.echo("")


def _report_to_dict(report: BudgetReport) -> dict[str, object]:
    """Serialise *report* to a plain JSON-safe dict."""
    return {
        "total_bytes": report.total_bytes,
        "limit_bytes": report.limit_bytes,
        "budget_used_pct": report.budget_used_pct,
        "over_budget": report.over_budget,
        "entry_count": report.entry_count,
        "breakdown": [
            {
                "kind": bd.kind,
                "entry_count": bd.entry_count,
                "byte_size": bd.byte_size,
            }
            for bd in report.breakdown
        ],
        "suggestions": [
            {
                "kind": sug.kind.value,
                "entry_ids": list(sug.entry_ids),
                "description": sug.description,
            }
            for sug in report.suggestions
        ],
        "merge_count": report.merge_count,
        "move_count": report.move_count,
        "drop_count": report.drop_count,
    }


@membudget_app.command("check")
def check_command(
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit a JSON envelope "
                '{"kind": "membudget", "report": {...}} for pipeline composition.'
            ),
        ),
    ] = False,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            help="Budget ceiling in bytes (default: 262144 = 256 KiB).",
            metavar="BYTES",
        ),
    ] = DEFAULT_LIMIT_BYTES,
    fail_on_over: Annotated[
        bool,
        typer.Option(
            "--fail-on-over",
            help="Exit 1 when the store is over budget (useful in CI).",
        ),
    ] = False,
) -> None:
    """Report memory-store size and suggest consolidation actions.

    Reads every memory entry and computes total UTF-8 byte size across
    title + summary + details.  Flags when the total exceeds --limit (default
    256 KiB) and emits advisory suggestions:

    \\b
    - DROP_STALE    — entries with staleness=stale/orphaned
    - MERGE_DUPLICATES — near-duplicate pairs (≥55% token overlap, same kind)
    - MOVE_TO_TOPIC — entries with details > 4 KiB (store a reference instead)

    Advisory only — never deletes or mutates the store.

    Examples:

        onmc membudget check               # human-readable report

        onmc membudget check --json        # JSON envelope for pipelines

        onmc membudget check --limit 131072          # 128 KiB budget

        onmc membudget check --fail-on-over          # exit 1 when over budget
    """
    try:
        repo_root = discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("error: no git repository found from the current directory.", err=True)
        raise typer.Exit(code=1) from None

    storage = _load_storage(repo_root)
    memories = storage.list_memories()

    report = analyze(memories, limit=limit)  # type: ignore[arg-type]

    if as_json:
        typer.echo(
            json.dumps(
                {"kind": "membudget", "report": _report_to_dict(report)},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _render_plain(report)

    if fail_on_over and report.over_budget:
        raise typer.Exit(code=1)
