"""CLI surface for the ``arena`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time.  No shared hub (``cli.py``, ``rendering/``, service
layer) is touched — this ships with **zero edits** to any existing file.

Persistence
-----------
Bouts are appended to ``<repo>/.onmc/arena/bouts.jsonl`` (one JSON object per
line, append-only).  Ratings are **always recomputed** from the full bouts log
via the pure :func:`oh_no_my_claudecode.arena.elo.build_ledger`, so the stored
ratings can never drift from the deterministic ELO formula (same pattern as
``registry``).  A derived snapshot is written to
``<repo>/.onmc/arena/ratings.json`` for fast look-ups.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.arena.elo import (
    Bout,
    ModelRecord,
    append_bout,
    build_ledger,
    load_bouts,
    rank_ledger,
    save_ratings,
)
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root

# ---------------------------------------------------------------------------
# Repo / path resolution
# ---------------------------------------------------------------------------

_ARENA_DIR = Path(".onmc") / "arena"
_BOUTS_FILE = _ARENA_DIR / "bouts.jsonl"
_RATINGS_FILE = _ARENA_DIR / "ratings.json"


def _repo_root() -> Path:
    """Best-effort repo root; falls back to cwd when discovery unavailable."""
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        return Path.cwd()


def _bouts_path(repo_root: Path) -> Path:
    return repo_root / _BOUTS_FILE


def _ratings_path(repo_root: Path) -> Path:
    return repo_root / _RATINGS_FILE


# ---------------------------------------------------------------------------
# Rendering (inline; Rich with plain-text fallback)
# ---------------------------------------------------------------------------


def _render_leaderboard_plain(ranked: list[ModelRecord]) -> None:
    """Emit the leaderboard as plain text."""
    if not ranked:
        typer.echo(
            "\n  onmc arena — no bouts recorded yet.\n"
            "  Record one with `onmc arena bout <modelA> <modelB> --winner A`.\n"
        )
        return
    header = (
        f"  {'#':<3} {'model':<28} {'rating':>8} {'W':>5} {'L':>5} {'D':>5} {'bouts':>6}"
    )
    lines = ["", "  onmc arena — ELO leaderboard", "", header]
    for idx, rec in enumerate(ranked, start=1):
        lines.append(
            f"  {idx:<3} {rec.model[:28]:<28} {rec.rating:>8.1f} "
            f"{rec.wins:>5} {rec.losses:>5} {rec.draws:>5} {rec.bouts:>6}"
        )
    lines.append("")
    typer.echo("\n".join(lines))


def _render_leaderboard_rich(ranked: list[ModelRecord]) -> bool:
    """Render the leaderboard as a Rich table; return False if Rich absent."""
    try:
        from rich.console import Console
        from rich.table import Table
    except Exception:  # noqa: BLE001 - Rich optional
        return False

    table = Table(title="onmc arena — ELO leaderboard")
    table.add_column("#", justify="right", style="dim")
    table.add_column("model", style="bold")
    table.add_column("rating", justify="right")
    table.add_column("W", justify="right", style="green")
    table.add_column("L", justify="right", style="red")
    table.add_column("D", justify="right", style="yellow")
    table.add_column("bouts", justify="right")

    for idx, rec in enumerate(ranked, start=1):
        table.add_row(
            str(idx),
            rec.model,
            f"{rec.rating:.1f}",
            str(rec.wins),
            str(rec.losses),
            str(rec.draws),
            str(rec.bouts),
        )

    Console().print(table)
    return True


def _render_standings_plain(rec: ModelRecord) -> None:
    """Emit one model's standings as plain text."""
    lines = [
        "",
        f"  onmc arena — standings for {rec.model!r}",
        f"  rating:   {rec.rating:.4f}",
        f"  wins:     {rec.wins}",
        f"  losses:   {rec.losses}",
        f"  draws:    {rec.draws}",
        f"  bouts:    {rec.bouts}",
    ]
    if rec.rating_history:
        history_str = "  →  ".join(f"{r:.1f}" for r in rec.rating_history[-10:])
        suffix = " (last 10)" if len(rec.rating_history) > 10 else ""
        lines.append(f"  history{suffix}: {history_str}")
    lines.append("")
    typer.echo("\n".join(lines))


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------


def register(app: typer.Typer) -> None:
    """Register the ``arena`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    arena_app = typer.Typer(
        no_args_is_help=True,
        help=(
            "Model gladiator: head-to-head ELO scoreboard — record bouts between "
            "models and track their ratings over time."
        ),
    )

    @arena_app.command("bout")
    def bout_command(
        model_a: Annotated[
            str,
            typer.Argument(help="Name / identifier of the first model."),
        ],
        model_b: Annotated[
            str,
            typer.Argument(help="Name / identifier of the second model."),
        ],
        winner: Annotated[
            str,
            typer.Option(
                "--winner",
                help="Bout outcome: A (model_a won), B (model_b won), or draw.",
            ),
        ],
        task: Annotated[
            str,
            typer.Option(
                "--task",
                help="Optional free-text task description for context.",
            ),
        ] = "",
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the updated ratings as JSON."),
        ] = False,
    ) -> None:
        """Record a head-to-head bout result and update ELO ratings.

        MODEL_A and MODEL_B are model names (e.g. ``gpt-4o``, ``claude-3-7``).
        ``--winner`` must be ``A``, ``B``, or ``draw``.

        The bout is appended to ``.onmc/arena/bouts.jsonl`` and ratings are
        recomputed from scratch via the deterministic ELO formula, then
        snapshotted to ``.onmc/arena/ratings.json``.
        """
        winner_norm = winner.strip()
        if winner_norm not in ("A", "B", "draw"):
            typer.echo(
                f"Invalid --winner {winner_norm!r}. Must be 'A', 'B', or 'draw'.",
                err=True,
            )
            raise typer.Exit(code=1)

        bout = Bout(model_a=model_a, model_b=model_b, winner=winner_norm, task=task)
        repo_root = _repo_root()
        bouts_path = _bouts_path(repo_root)
        ratings_path = _ratings_path(repo_root)

        append_bout(bouts_path, bout)
        bouts = load_bouts(bouts_path)
        ledger = build_ledger(bouts)
        save_ratings(ratings_path, ledger)

        rec_a = ledger.models.get(model_a)
        rec_b = ledger.models.get(model_b)

        if as_json:
            result: dict[str, Any] = {
                "bout": bout.to_dict(),
                "ratings": {
                    model_a: rec_a.to_dict() if rec_a else None,
                    model_b: rec_b.to_dict() if rec_b else None,
                },
            }
            typer.echo(json.dumps(result))
            return

        outcome_label = (
            f"{model_a} wins" if winner_norm == "A"
            else (f"{model_b} wins" if winner_norm == "B" else "draw")
        )
        typer.echo(f"\n  Bout recorded: {model_a} vs {model_b} — {outcome_label}")
        if rec_a:
            rec_a_line = f"W{rec_a.wins}/L{rec_a.losses}/D{rec_a.draws}"
            typer.echo(f"  {model_a}: {rec_a.rating:.1f}  ({rec_a_line})")
        if rec_b:
            rec_b_line = f"W{rec_b.wins}/L{rec_b.losses}/D{rec_b.draws}"
            typer.echo(f"  {model_b}: {rec_b.rating:.1f}  ({rec_b_line})")
        typer.echo("")

    @arena_app.command("leaderboard")
    def leaderboard_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the leaderboard as JSON."),
        ] = False,
    ) -> None:
        """Show the ELO leaderboard — models ranked by rating.

        Ratings are recomputed from the persisted bouts log on every call so
        they always reflect the deterministic ELO formula.
        """
        repo_root = _repo_root()
        bouts = load_bouts(_bouts_path(repo_root))
        ledger = build_ledger(bouts)
        ranked = rank_ledger(ledger)

        if as_json:
            typer.echo(json.dumps([rec.to_dict() for rec in ranked]))
            return

        if not _render_leaderboard_rich(ranked):
            _render_leaderboard_plain(ranked)

    @arena_app.command("standings")
    def standings_command(
        model: Annotated[
            str,
            typer.Argument(help="The model name to look up."),
        ],
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the model's standings as JSON."),
        ] = False,
    ) -> None:
        """Show one model's ELO record + rating history.

        Exits non-zero when the model has no bouts recorded.
        """
        repo_root = _repo_root()
        bouts = load_bouts(_bouts_path(repo_root))
        ledger = build_ledger(bouts)
        rec = ledger.models.get(model)

        if rec is None:
            typer.echo(
                f"\n  onmc arena — no bouts recorded for {model!r}.\n"
                "  Record one with `onmc arena bout <modelA> <modelB> --winner A`.\n",
                err=True,
            )
            raise typer.Exit(code=1)

        if as_json:
            typer.echo(json.dumps(rec.to_dict()))
            return

        _render_standings_plain(rec)

    app.add_typer(arena_app, name="arena")
