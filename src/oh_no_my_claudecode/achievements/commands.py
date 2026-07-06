"""CLI surface for the ``achievements`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. No shared service hub is touched — receipts are
loaded directly via :func:`oh_no_my_claudecode.ledger.accounting.load_receipts`,
the same impure boundary ``onmc quest`` and ``onmc badge`` already use.

The pure engine lives in :mod:`oh_no_my_claudecode.achievements.achievements`;
this layer only resolves the repo root, loads receipts, and renders. Degrades
gracefully: zero receipts prints an honest "no verified runs yet" note and
exits 0.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.achievements.achievements import build_report, render_text
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root


def _resolve_repo_root() -> Path:
    """Discover the repo root, falling back to CWD if discovery fails.

    Mirrors ``onmc quest``'s resolution: achievements are a read-only report,
    so a missing ``onmc init`` should not hard-fail the command.
    """
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        return Path.cwd().resolve()


def _load_receipts(repo_root: Path) -> list[dict[str, Any]]:
    """Load all run receipts from the repo; returns empty list on any failure."""
    try:
        from oh_no_my_claudecode.ledger.accounting import load_receipts

        return load_receipts(repo_root, scope="project")
    except Exception:  # noqa: BLE001 - achievements must never crash on bad state
        return []


def register(app: typer.Typer) -> None:
    """Register the ``achievements`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("achievements")
    def achievements_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the achievements report as JSON."),
        ] = False,
    ) -> None:
        """Show your XP, level, streaks, and badges earned from verified runs.

        XP and streaks are earned only from *verified* ``onmc loop`` /
        ``onmc swarm`` receipts — unverified runs never inflate the score.
        Deterministic and offline: no LLM calls, no randomness. An empty
        receipt log prints an honest zero-state and exits 0.
        """
        repo_root = _resolve_repo_root()
        receipts = _load_receipts(repo_root)
        report = build_report(receipts)

        if as_json:
            typer.echo(json.dumps(report.to_dict(), indent=2))
            return

        typer.echo(render_text(report))
