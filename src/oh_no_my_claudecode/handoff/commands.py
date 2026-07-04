"""CLI surface for the ``handoff`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. Rendering uses a local Rich console with a plain-text
fallback — no shared rendering/console hub is touched. Storage is opened directly
here, mirroring the roast feature's ``_open_context``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.config import (
    config_exists,
    create_state_dirs,
    database_path,
    load_config,
)
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.handoff.handoff import (
    HandoffBundle,
    build_handoff,
    read_bundle,
    render_resume,
    summarize,
    write_bundle,
)
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

_SLUG_KEEP = "-_"
_SLUG_MAX = 48


def _open_context() -> tuple[Path, SQLiteStorage]:
    """Resolve the repo root and open an initialised storage handle.

    Mirrors the roast feature's precondition checks so failure messages match the
    rest of the CLI, without routing through the service hub.
    """
    try:
        repo_root = discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("Not inside a repository. Run `onmc handoff` from a repo.", err=True)
        raise typer.Exit(code=1) from None
    if not config_exists(repo_root):
        typer.echo("ONMC is not initialized. Run `onmc init` first.", err=True)
        raise typer.Exit(code=1)
    config = load_config(repo_root)
    create_state_dirs(config, repo_root)
    storage = SQLiteStorage(database_path(config, repo_root))
    storage.initialize()
    return repo_root, storage


def _slugify(goal: str) -> str:
    """Turn a free-text goal into a filesystem-safe slug (bounded, non-empty)."""
    out: list[str] = []
    for ch in goal.strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "\t") or ch in _SLUG_KEEP:
            out.append("-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug[:_SLUG_MAX].strip("-")
    return slug or "task"


class _PlainConsole:
    """Minimal ``print(str)`` shim used when Rich is unavailable."""

    def print(self, text: str = "") -> None:  # noqa: A003 - mirror Rich API
        typer.echo(text)


def _console() -> Any:
    """Return a Rich console when available, else a plain-text shim."""
    try:
        from rich.console import Console

        return Console()
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        return _PlainConsole()


def register(app: typer.Typer) -> None:
    """Register the ``handoff`` sub-app onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    handoff_app = typer.Typer(
        no_args_is_help=True,
        help="Package / resume portable cross-session task context.",
    )

    @handoff_app.command("create")
    def create_command(
        goal: Annotated[str, typer.Argument(help="The task goal to package context for.")],
        out: Annotated[
            Path | None,
            typer.Option("--out", help="Where to write the bundle JSON."),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the bundle JSON to stdout instead of a file."),
        ] = False,
    ) -> None:
        """Build a portable handoff bundle for GOAL and write it (or print it).

        Assembles the context pack, goal-relevant decisions, recorded dead-ends,
        and recent run receipts into one JSON bundle. Missing sources degrade to
        empty sections with explanatory notes — the command never crashes.
        """
        repo_root, storage = _open_context()
        bundle = build_handoff(storage, repo_root, goal, now=utc_now().isoformat())

        if as_json:
            typer.echo(json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False))
            return

        dest = out if out is not None else repo_root / ".onmc" / f"handoff-{_slugify(goal)}.json"
        written = write_bundle(bundle, dest)
        typer.echo(f"Wrote handoff bundle: {written}")
        typer.echo(f"  {summarize(bundle)}")
        if bundle.notes:
            typer.echo(f"  ({len(bundle.notes)} note(s) on partial sources — see `resume`)")

    @handoff_app.command("resume")
    def resume_command(
        file: Annotated[Path, typer.Argument(help="Path to a handoff bundle JSON.")],
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the parsed bundle as JSON instead of a briefing."),
        ] = False,
    ) -> None:
        """Read a handoff bundle FILE and render a resume briefing."""
        try:
            bundle: HandoffBundle = read_bundle(file)
        except FileNotFoundError:
            typer.echo(f"Handoff bundle not found: {file}", err=True)
            raise typer.Exit(code=1) from None
        except ValueError as exc:
            typer.echo(f"Could not read handoff bundle: {exc}", err=True)
            raise typer.Exit(code=1) from None

        if as_json:
            typer.echo(json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False))
            return

        render_resume(bundle, _console())

    app.add_typer(handoff_app, name="handoff")
