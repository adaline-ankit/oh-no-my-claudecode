"""CLI surface for the ``vibe`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): this module exposes a top-level
``register(app)`` that the registry invokes at CLI build time, so ``onmc vibe``
ships with **zero edits** to ``cli.py`` or any other shared hub.

``onmc vibe`` is a read-only ambient status HUD.  It aggregates:

- **coach** streak (consecutive green events, from ``.onmc/coach/streak.json``)
- **whip** reward tally (treats vs cracks, from ``.onmc/whip/rewards.jsonl``)
- **quest** level + XP (from run receipts via ``quest.engine.compute_quests``)

and derives a single "mood" emoji + caption from the combination.  None of
the source stores are modified — this command is purely read-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.vibe.hud import VibeState, compute_mood, render, render_json

# ---------------------------------------------------------------------------
# Source readers (all defensive — degrade gracefully on missing data)
# ---------------------------------------------------------------------------


def _resolve_repo_root() -> Path:
    """Return the repo root, falling back to cwd on discovery failure."""
    from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root

    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        return Path.cwd().resolve()


def _read_coach_streak(repo_root: Path) -> int | None:
    """Return the current coach streak, or None if unavailable."""
    streak_path = repo_root / ".onmc" / "coach" / "streak.json"
    if not streak_path.exists():
        return None
    try:
        data: Any = json.loads(streak_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            raw = data.get("current_streak", None)
            if isinstance(raw, (int, float)):
                return int(raw)
    except Exception:  # noqa: BLE001, S110
        pass
    return None


def _read_whip_tally(repo_root: Path) -> tuple[int | None, int | None]:
    """Return (praises, corrections) from whip reward ledger, or (None, None)."""
    try:
        from oh_no_my_claudecode.whip.steer import WHIP_SUBDIR, tally

        whip_dir = repo_root / WHIP_SUBDIR
        result = tally(whip_dir=whip_dir)
        return result.get("treats"), result.get("cracks")
    except Exception:  # noqa: BLE001
        return None, None


def _read_quest_stats(
    repo_root: Path,
) -> tuple[int | None, int | None, int | None, int | None]:
    """Return (level, total_xp, xp_to_next, streak_days), or Nones on failure."""
    try:
        from oh_no_my_claudecode.ledger.accounting import load_receipts
        from oh_no_my_claudecode.quest.engine import compute_quests
        from oh_no_my_claudecode.utils.time import utc_now

        receipts = load_receipts(repo_root, scope="project")
        log = compute_quests(receipts, [], now=utc_now())
        return log.level, log.total_xp, log.xp_to_next, log.streak_days
    except Exception:  # noqa: BLE001
        return None, None, None, None


def _gather_vibe_state(repo_root: Path) -> VibeState:
    """Aggregate all source data into a :class:`VibeState`."""
    streak = _read_coach_streak(repo_root)
    praises, corrections = _read_whip_tally(repo_root)
    level, total_xp, xp_to_next, streak_days = _read_quest_stats(repo_root)
    return VibeState(
        streak=streak,
        praises=praises,
        corrections=corrections,
        level=level,
        total_xp=total_xp,
        xp_to_next=xp_to_next,
        streak_days=streak_days,
    )


# ---------------------------------------------------------------------------
# Auto-discovery entry point
# ---------------------------------------------------------------------------


def register(app: typer.Typer) -> None:
    """Register the ``onmc vibe`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    vibe_app = typer.Typer(
        help=(
            "Ambient agent-mood HUD: aggregates coach streak, whip rewards, "
            "and quest level into a single glanceable status. Read-only."
        ),
        invoke_without_command=True,
    )

    @vibe_app.callback()
    def _vibe_root(
        ctx: typer.Context,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the HUD as a JSON envelope."),
        ] = False,
    ) -> None:
        """Show the ambient agent-mood HUD.

        Aggregates coach streak, whip reward tally, and quest level/XP into a
        mood reading (on fire / cruising / meh / struggling) with a one-line
        vibe caption.

        Examples:

            onmc vibe

            onmc vibe --json
        """
        if ctx.invoked_subcommand is not None:
            return
        repo_root = _resolve_repo_root()
        state = _gather_vibe_state(repo_root)
        if as_json:
            typer.echo(json.dumps(render_json(state), indent=2))
            return
        typer.echo("\n" + render(state) + "\n")

    @vibe_app.command("mood")
    def mood_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit mood + score as JSON."),
        ] = False,
    ) -> None:
        """Show just the computed mood and score.

        A compact single-line output for use in status bars or pipelines.

        Examples:

            onmc vibe mood

            onmc vibe mood --json
        """
        repo_root = _resolve_repo_root()
        state = _gather_vibe_state(repo_root)
        mood, score = compute_mood(
            streak=state.streak,
            praises=state.praises,
            corrections=state.corrections,
            level=state.level,
        )
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "kind": "vibe_mood",
                        "mood": mood.value,
                        "emoji": mood.emoji,
                        "score": score,
                    },
                    indent=2,
                )
            )
            return
        typer.echo(f"{mood.emoji}  {mood.name.replace('_', ' ').title()}  (score {score:.2f})")

    app.add_typer(vibe_app, name="vibe")
