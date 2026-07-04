"""CLI surface for the ``badge`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. No shared hub (``cli.py``, ``rendering/``, service
layer) is touched — rendering is a plain ``typer.echo`` of the pure functions in
:mod:`oh_no_my_claudecode.badge.badge`, and receipt reading reuses that module's
pure loader.

The ``--post`` flag is the only impure path: it shells out to ``gh pr comment``
to publish the proof-of-work comment on a PR. Repo detection prefers
``gh repo view`` and falls back to parsing the ``origin`` git remote.
"""

from __future__ import annotations

import json
import subprocess
from typing import Annotated

import typer

from oh_no_my_claudecode.badge.badge import (
    comment_body,
    endpoint_payload,
    load_receipt,
    render_markdown_badge,
)


def _detect_repo() -> str | None:
    """Detect the ``owner/name`` (or full URL) of the current repo for ``gh``.

    Tries ``gh repo view --json nameWithOwner`` first (authoritative for the gh
    CLI), then falls back to the ``origin`` remote URL. Returns ``None`` when
    neither resolves — the caller then lets ``gh`` infer the repo itself.
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


def _post_comment(pr_number: int, body: str) -> None:
    """Post *body* as a PR comment on *pr_number* via ``gh pr comment``.

    Adds ``--repo`` when the repo is detectable so the command works from a
    worktree whose default repo inference might differ. On failure, echoes the
    ``gh`` error and exits non-zero.
    """
    argv = ["gh", "pr", "comment", str(pr_number)]
    repo = _detect_repo()
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
    """Register the ``badge`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("badge")
    def badge_command(
        receipt_or_swarm_id: Annotated[
            str,
            typer.Argument(
                help="Path to a receipt JSON, or a swarm id (resolved via its manifest)."
            ),
        ],
        unit_id: Annotated[
            str | None,
            typer.Option("--unit", help="Unit id to select when a swarm id is given."),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the shields.io endpoint payload as JSON."),
        ] = False,
        post: Annotated[
            int | None,
            typer.Option(
                "--post",
                help="PR number to post the proof-of-work comment to (via gh pr comment).",
            ),
        ] = None,
    ) -> None:
        """Render a "No-Slop verified" proof-of-work badge from an onmc receipt.

        onmc's swarm/loop receipts already prove work is real + verified
        (``git_tree_sha``, ``diff_sha``, ``verified``, ``receipt_hash``). This
        turns one receipt into a shareable shields.io badge: pass a receipt path
        or a swarm id (``--unit`` to pick a unit).

        With no flags, prints the Markdown badge + PR-comment body. ``--json``
        emits the shields.io endpoint payload. ``--post N`` publishes the comment
        on PR #N via ``gh``.
        """
        receipt = load_receipt(receipt_or_swarm_id, unit_id=unit_id)
        if receipt is None:
            typer.echo(
                f"No readable receipt for {receipt_or_swarm_id!r}"
                + (f" (unit {unit_id!r})" if unit_id else "")
                + ". Pass a receipt JSON path or a swarm id with a manifest.",
                err=True,
            )
            raise typer.Exit(code=1)

        if as_json:
            typer.echo(json.dumps(endpoint_payload(receipt)))
            return

        body = comment_body(receipt)

        if post is not None:
            _post_comment(post, body)
            return

        typer.echo(render_markdown_badge(receipt))
        typer.echo("")
        typer.echo(body)
