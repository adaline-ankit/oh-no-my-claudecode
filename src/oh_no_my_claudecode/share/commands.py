"""CLI surface for the ``share`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. No shared hub (``cli.py``) is touched.

``onmc share`` publishes a snapshot to a GitHub Gist so it can be handed to
someone who doesn't have the repo checked out. It is read-only with respect
to the repository — the only side effect anywhere in this feature is the
``gh gist create`` shell-out, and that only happens when neither
``--dry-run`` nor ``--json`` is passed.

Two content modes:

- default: the standalone dashboard HTML snapshot, reusing the existing
  exporter (:func:`oh_no_my_claudecode.ui.export_dashboard_snapshot`, the same
  one ``onmc ui --export`` calls).
- ``--scorecard``: the shareable Markdown scorecard
  (:func:`oh_no_my_claudecode.scorecard.build_scorecard` /
  :func:`oh_no_my_claudecode.scorecard.render_markdown`).

The file is always written to a temp path first (so ``--dry-run``/``--json``
can report a real, inspectable artifact); ``gh gist create`` is only invoked
against that path when actually publishing.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.scorecard.scorecard import build_scorecard, render_markdown
from oh_no_my_claudecode.share.share import ShareKind, gist_description, snapshot_filename
from oh_no_my_claudecode.ui import export_dashboard_snapshot


def _detect_repo_name() -> str | None:
    """Best-effort ``owner/name`` (or bare repo name) for the gist description.

    Tries ``gh repo view`` first, then falls back to the current directory
    name. Mirrors :mod:`oh_no_my_claudecode.prbadge.commands`'s
    ``_detect_repo``, but never returns ``None`` from the git-remote branch —
    the caller only needs something human-readable, not an exact identifier.
    """
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            capture_output=True,
            text=True,
            check=False,
        )
        name = result.stdout.strip()
        if result.returncode == 0 and name:
            return name
    except (OSError, ValueError):
        pass
    return Path.cwd().name or None


def _write_dashboard_snapshot(destination: Path) -> Path:
    """Render the standalone dashboard HTML via the existing exporter.

    Reuses :func:`oh_no_my_claudecode.ui.export_dashboard_snapshot` — the same
    function ``onmc ui --export`` calls — so the two commands never drift.
    Requires an initialised onmc repo (propagates ``FileNotFoundError`` as a
    CLI error, same as ``onmc ui``).
    """
    from oh_no_my_claudecode.core.service import OnmcService

    service = OnmcService(Path.cwd())
    return export_dashboard_snapshot(service, destination)


def _write_scorecard_snapshot(destination: Path) -> Path:
    """Render the shareable Markdown scorecard to *destination*."""
    from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root

    try:
        repo_root = discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        repo_root = Path.cwd()
    card = build_scorecard(repo_root)
    body = render_markdown(card)
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(body, encoding="utf-8")
    return destination


def _publish_gist(path: Path, *, description: str, public: bool) -> str:
    """Create a gist from *path* via ``gh gist create`` and return its URL.

    The only impure, side-effecting call in this entire feature. On failure,
    echoes the ``gh`` error and exits non-zero.
    """
    argv = ["gh", "gist", "create", str(path), "--desc", description]
    argv.append("--public" if public else "--secret")

    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv, capture_output=True, text=True, check=False
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Failed to invoke gh: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if result.returncode != 0:
        typer.echo(
            f"gh gist create failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}",
            err=True,
        )
        raise typer.Exit(code=1)

    url = result.stdout.strip()
    return url


def register(app: typer.Typer) -> None:
    """Register the ``share`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("share")
    def share_command(
        scorecard: Annotated[
            bool,
            typer.Option(
                "--scorecard", help="Publish the Markdown scorecard instead of the dashboard."
            ),
        ] = False,
        private: Annotated[
            bool,
            typer.Option("--private", help="Create a secret gist instead of a public one."),
        ] = False,
        dry_run: Annotated[
            bool,
            typer.Option(
                "--dry-run",
                help="Write the snapshot locally and print its path without publishing.",
            ),
        ] = False,
        as_json: Annotated[
            bool,
            typer.Option(
                "--json",
                help="Emit the snapshot path as JSON. Implies --dry-run; never publishes.",
            ),
        ] = False,
    ) -> None:
        """Publish a shareable snapshot of this repo's onmc state to a Gist.

        By default, publishes the standalone dashboard HTML (the same
        self-contained file ``onmc ui --export`` produces). With
        ``--scorecard``, publishes the shareable Markdown scorecard instead.

        Read-only with respect to the repository: the only side effect is the
        ``gh gist create`` call, and it only happens when neither
        ``--dry-run`` nor ``--json`` is passed. ``--private`` creates a secret
        gist instead of a public one.
        """
        kind = ShareKind.SCORECARD if scorecard else ShareKind.DASHBOARD
        filename = snapshot_filename(kind)
        destination = Path(tempfile.gettempdir()) / "onmc-share" / filename

        try:
            if kind is ShareKind.SCORECARD:
                written = _write_scorecard_snapshot(destination)
            else:
                written = _write_dashboard_snapshot(destination)
        except FileNotFoundError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

        effective_dry_run = dry_run or as_json

        if as_json:
            typer.echo(json.dumps({"path": str(written), "kind": kind.value, "published": False}))
            return

        if effective_dry_run:
            typer.echo(f"[dry-run] Snapshot written: {written}")
            typer.echo("Review repository memory before sharing this file.")
            return

        typer.echo("Review repository memory before sharing this file.")
        repo_name = _detect_repo_name()
        description = gist_description(kind, repo_name=repo_name)
        url = _publish_gist(written, description=description, public=not private)
        visibility = "secret" if private else "public"
        typer.echo(f"Published {visibility} gist: {url}")
