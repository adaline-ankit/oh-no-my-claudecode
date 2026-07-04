"""CLI surface for the ``scorecard`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. No shared hub (``cli.py``, service layer) is edited —
rendering routes through the shared Rich console, with a plain-text fallback.

Unlike ``roast``/``orggraph``, ``scorecard`` is a defensive *aggregator*: it does
not hard-fail when onmc is uninitialised or a subsystem is missing. It resolves
the repo root best-effort (falling back to cwd, like ``registry``) and lets each
signal degrade to "n/a" — so ``onmc scorecard`` always produces a card and exits
0, even on a fresh repo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.scorecard.scorecard import (
    build_scorecard,
    render_markdown,
    render_summary,
)


def _repo_root() -> Path:
    """Best-effort repo root; falls back to cwd when discovery is unavailable.

    Like ``registry``, the scorecard never *requires* an initialised onmc repo —
    every signal degrades to "n/a" — so a discovery failure resolves against the
    current directory rather than aborting.
    """
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        return Path.cwd()


def _console() -> object:
    """Return the shared Rich console, or a minimal ``print``-only stub.

    Importing the shared console must never crash the command — if Rich or the
    rendering module is unavailable, fall back to a stub whose ``print`` routes
    through ``typer.echo``.
    """
    try:
        from oh_no_my_claudecode.rendering.console import console

        return console
    except Exception:  # noqa: BLE001 - rendering hub is optional; degrade to plain echo

        class _EchoConsole:
            def print(self, renderable: object) -> None:
                typer.echo(str(renderable))

        return _EchoConsole()


def register(app: typer.Typer) -> None:
    """Register the ``scorecard`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("scorecard")
    def scorecard_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the scorecard as a JSON object."),
        ] = False,
        as_markdown: Annotated[
            bool,
            typer.Option(
                "--markdown", help="Emit the shareable Markdown scorecard block."
            ),
        ] = False,
    ) -> None:
        """One shareable agent-readiness + trust scorecard for this repo.

        Aggregates four onmc signals — agent-readiness (roast), top-agent trust
        (registry), best-verified model (flywheel), and institutional-memory
        coverage (orggraph) — into a single card. Deterministic and offline. Any
        unavailable signal degrades to "n/a" with a note; the command always
        exits 0.
        """
        repo_root = _repo_root()
        card = build_scorecard(repo_root)

        if as_json:
            typer.echo(json.dumps(card.to_dict()))
            return
        if as_markdown:
            typer.echo(render_markdown(card))
            return
        render_summary(card, _console())
