"""CLI surface for the ``prbadge`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. No shared hub (``cli.py``) is touched.

Read-only w.r.t. the repo: it only loads receipts already on disk
(``.agent-memory/receipts/``, via :mod:`oh_no_my_claudecode.ledger`) and
renders a badge. The **only** side effect anywhere in this feature is posting
a PR comment via ``gh pr comment``, and that only happens when ``--dry-run``
is *not* passed. ``--json`` implies ``--dry-run`` — it never posts.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.ledger.accounting import load_receipts
from oh_no_my_claudecode.prbadge.prbadge import (
    BadgeContent,
    build_badge_from_receipts,
    render_markdown,
)


def _onmc_version() -> str:
    """Return the running onmc package version ("0+unknown" if unresolvable)."""
    from oh_no_my_claudecode import __version__

    return __version__


def _detect_repo() -> str | None:
    """Detect the ``owner/name`` of the current repo for ``gh``.

    Tries ``gh repo view --json nameWithOwner`` first, then falls back to the
    ``origin`` git remote URL. Returns ``None`` when neither resolves — the
    caller then lets ``gh`` infer the repo itself. Mirrors
    :mod:`oh_no_my_claudecode.badge.commands`'s ``_detect_repo``.
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

    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
        )
        url = result.stdout.strip()
        if result.returncode == 0 and url:
            return url
    except (OSError, ValueError):
        pass

    return None


def _post_comment(pr_number: int, body: str, *, repo: str | None) -> None:
    """Post *body* as a PR comment on *pr_number* via ``gh pr comment``.

    The only impure, side-effecting call in this entire feature. On failure,
    echoes the ``gh`` error and exits non-zero.
    """
    argv = ["gh", "pr", "comment", str(pr_number)]
    if repo:
        argv += ["--repo", repo]
    argv += ["--body", body]

    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv, capture_output=True, text=True, check=False
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Failed to invoke gh: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if result.returncode != 0:
        typer.echo(
            f"gh pr comment failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}",
            err=True,
        )
        raise typer.Exit(code=1)

    where = f" on {repo}" if repo else ""
    typer.echo(f"Posted onmc badge comment to PR #{pr_number}{where}.")
    posted = result.stdout.strip()
    if posted:
        typer.echo(posted)


def register(app: typer.Typer) -> None:
    """Register the ``prbadge`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("prbadge")
    def prbadge_command(
        pr_number: Annotated[
            int,
            typer.Argument(help="PR number to post the onmc verified-work badge to."),
        ],
        dry_run: Annotated[
            bool,
            typer.Option(
                "--dry-run",
                help="Build and print the comment without posting it (default when --json is set).",
            ),
        ] = False,
        repo: Annotated[
            str | None,
            typer.Option(
                "--repo",
                help="owner/name to post to (defaults to auto-detection via gh/git remote).",
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option(
                "--json",
                help="Emit the structured badge data as JSON. Implies --dry-run; never posts.",
            ),
        ] = False,
    ) -> None:
        """Post a "verified-work" onmc badge comment on a GitHub PR.

        Aggregates local run receipts (``.agent-memory/receipts/``, the same
        corpus ``onmc ledger`` reads) into a compact, honest Markdown badge —
        "N loops recorded, X% verified, built with onmc vY" — and posts it as
        a PR comment via ``gh pr comment``.

        Read-only with respect to the repository: the only side effect is the
        ``gh`` call, and it only happens when neither ``--dry-run`` nor
        ``--json`` is passed. With no verified receipts on disk, the badge
        honestly reports "no verified receipts yet" rather than a fabricated
        number.
        """
        repo_root = Path.cwd()
        receipts = load_receipts(repo_root, scope="project")
        content: BadgeContent = build_badge_from_receipts(
            receipts, onmc_version=_onmc_version()
        )
        body = render_markdown(content)

        effective_dry_run = dry_run or as_json

        if as_json:
            typer.echo(json.dumps(content.to_dict()))
            return

        if effective_dry_run:
            typer.echo(body)
            return

        resolved_repo = repo or _detect_repo()
        _post_comment(pr_number, body, repo=resolved_repo)
