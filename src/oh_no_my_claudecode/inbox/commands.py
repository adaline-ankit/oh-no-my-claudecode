"""CLI surface for the ``inbox`` feature — auto-discovered.

Defines a top-level ``register(app)`` callable that the registry (see
:mod:`oh_no_my_claudecode.command_registry`) invokes at CLI build time, wiring
an ``onmc inbox`` command group with **zero** edits to ``cli.py``.

Subcommands
-----------
``onmc inbox add "<task>"``  persist a manual work item
``onmc inbox list``          show persisted manual items
``onmc inbox rank``          show the full ranked queue (all sources)
``onmc inbox run --top N``   emit a plan for the top N items (no execution)

Each subcommand renders its own output inline (no shared rendering hub) and
supports ``--json`` for machine consumption. Output is deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.inbox.queue import (
    InboxItem,
    add_item,
    gather_candidates,
    list_items,
)
from oh_no_my_claudecode.utils.time import utc_now


def _resolve_repo_root() -> Path:
    """Discover the repo root, falling back to CWD if discovery fails."""
    from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root

    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        return Path.cwd().resolve()


def _try_storage() -> object | None:
    """Best-effort handle on the repo's SQLite store.

    Returns ``None`` when onmc is not initialised in this repo, so the inbox
    degrades gracefully (manual + TODO sources still work). Never raises.
    """
    try:
        from oh_no_my_claudecode.cli import _service

        _repo_root, _config, storage = _service()._load_context()  # noqa: SLF001
    except Exception:  # noqa: BLE001 - missing init / any error → no storage source
        return None
    return storage


def _item_payload(item: InboxItem) -> dict[str, object]:
    """JSON-serialisable view of an inbox item."""
    return {
        "id": item.id,
        "text": item.text,
        "source": item.source,
        "score": item.score,
        "created_at": item.created_at,
    }


def register(app: typer.Typer) -> None:
    """Register the ``inbox`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    inbox_app = typer.Typer(
        help="Ranked work queue: manual adds + TODO/FIXME + coverage gaps + memory.",
        no_args_is_help=True,
    )

    @inbox_app.command("add")
    def add_command(
        text: Annotated[
            str,
            typer.Argument(help="The task description to enqueue."),
        ],
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the stored item as JSON."),
        ] = False,
    ) -> None:
        """Add a manual work item to the inbox (idempotent on text)."""
        repo_root = _resolve_repo_root()
        try:
            item = add_item(repo_root, text, now=utc_now())
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        if as_json:
            typer.echo(json.dumps(_item_payload(item)))
            return
        typer.echo(f"added [{item.source}] {item.text}")

    @inbox_app.command("list")
    def list_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the manual items as JSON."),
        ] = False,
    ) -> None:
        """List persisted manual items (insertion order, unranked)."""
        repo_root = _resolve_repo_root()
        items = list_items(repo_root)
        if as_json:
            typer.echo(json.dumps([_item_payload(i) for i in items]))
            return
        if not items:
            typer.echo("inbox is empty — add one with: onmc inbox add \"<task>\"")
            return
        for item in items:
            typer.echo(f"- {item.text}")

    @inbox_app.command("rank")
    def rank_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the ranked queue as JSON."),
        ] = False,
    ) -> None:
        """Show the full ranked queue (manual + TODO/FIXME + coverage + memory)."""
        repo_root = _resolve_repo_root()
        storage = _try_storage()
        ranked = gather_candidates(repo_root, storage, now=utc_now())  # type: ignore[arg-type]
        if as_json:
            typer.echo(json.dumps([_item_payload(i) for i in ranked]))
            return
        if not ranked:
            typer.echo("inbox is empty — nothing to rank.")
            return
        for idx, item in enumerate(ranked, start=1):
            typer.echo(f"{idx:>3}. [{item.source:>8}] {item.score:>7.2f}  {item.text}")

    @inbox_app.command("run")
    def run_command(
        top: Annotated[
            int,
            typer.Option("--top", help="How many top-ranked items to plan.", min=1),
        ] = 3,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the plan as JSON."),
        ] = False,
    ) -> None:
        """Emit a plan for the top N ranked items (no execution).

        ``run`` is intentionally side-effect-free: it surfaces *what* it would
        work on next, ranked, so a human or an outer loop can decide. It never
        spawns work itself.
        """
        repo_root = _resolve_repo_root()
        storage = _try_storage()
        ranked = gather_candidates(repo_root, storage, now=utc_now())  # type: ignore[arg-type]
        plan = ranked[: max(top, 0)]
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "plan": [_item_payload(i) for i in plan],
                        "count": len(plan),
                        "executed": False,
                    }
                )
            )
            return
        if not plan:
            typer.echo("nothing to plan — inbox is empty.")
            return
        typer.echo(f"plan ({len(plan)} item(s), no execution):")
        for idx, item in enumerate(plan, start=1):
            typer.echo(f"{idx}. [{item.source}] {item.text}")

    app.add_typer(inbox_app, name="inbox")
