"""CLI surface for the ``quest`` feature — auto-discovered.

Defines a top-level ``register(app)`` callable that the registry (see
:mod:`oh_no_my_claudecode.command_registry`) invokes at CLI build time, wiring
an ``onmc quest`` command group with **zero** edits to ``cli.py``.

Subcommands
-----------
``onmc quest log [--json]``           full quest log: level, XP, quests, loot
``onmc quest achievements [--json]``  unlocked achievements
``onmc quest stats [--json]``         level, XP, streak, counts
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.quest.engine import compute_quests
from oh_no_my_claudecode.utils.time import utc_now


def _resolve_repo_root() -> Path:
    """Discover the repo root, falling back to CWD if discovery fails."""
    from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root

    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        return Path.cwd().resolve()


def _load_receipts(repo_root: Path) -> list[dict[str, Any]]:
    """Load all run receipts from the repo; returns empty list on any failure."""
    try:
        from oh_no_my_claudecode.ledger.accounting import load_receipts

        return load_receipts(repo_root, scope="project")
    except Exception:  # noqa: BLE001
        return []


def _load_tasks(repo_root: Path) -> list[dict[str, Any]]:
    """Load ranked inbox items as task dicts; returns empty list on any failure."""
    try:
        from oh_no_my_claudecode.inbox.queue import gather_candidates
        from oh_no_my_claudecode.utils.time import utc_now as _utc_now

        items = gather_candidates(repo_root, None, now=_utc_now())
        return [
            {
                "text": item.text,
                "source": item.source,
                "score": item.score,
            }
            for item in items
        ]
    except Exception:  # noqa: BLE001
        return []


def register(app: typer.Typer) -> None:
    """Register the ``quest`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    quest_app = typer.Typer(
        help=(
            "Gamified RPG backlog: XP from verified runs, levels, bosses, loot."
        ),
        no_args_is_help=True,
    )

    @quest_app.command("log")
    def log_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the quest log as JSON."),
        ] = False,
    ) -> None:
        """Show the full quest log: level, XP, active quests, boss fights, loot.

        XP is earned from verified ``onmc loop`` / ``onmc swarm`` runs.
        Boss fights are high-risk open tasks. Recent loot is the last 10
        verified completions.
        """
        repo_root = _resolve_repo_root()
        receipts = _load_receipts(repo_root)
        tasks = _load_tasks(repo_root)
        now = utc_now()
        log = compute_quests(receipts, tasks, now=now)

        if as_json:
            typer.echo(json.dumps(log.to_dict(), indent=2))
            return

        # Human-readable output.
        typer.echo(
            f"Level {log.level}  |  {log.total_xp} XP total"
            f"  |  {log.xp_to_next} XP to next level"
            f"  |  streak {log.streak_days}d"
        )
        typer.echo(f"Runs: {log.verified_total}/{log.total_runs} verified")

        if log.boss_fights:
            typer.echo(f"\n[!] Boss fights ({len(log.boss_fights)}):")
            for b in log.boss_fights:
                typer.echo(f"    BOSS  [{b.source}] {b.text}")

        if log.active_quests:
            non_boss = [q for q in log.active_quests if not q.is_boss]
            if non_boss:
                typer.echo(f"\nActive quests ({len(non_boss)}):")
                for q in non_boss[:10]:
                    typer.echo(f"    [{q.source:>8}] {q.score:>7.2f}  {q.text}")

        if log.recent_loot:
            typer.echo(f"\nRecent loot ({len(log.recent_loot)}):")
            for lo in log.recent_loot:
                typer.echo(f"    +{lo.xp_earned} XP  {lo.name}")

        if log.achievements:
            typer.echo(f"\nAchievements ({len(log.achievements)}):")
            for a in log.achievements:
                typer.echo(f"    [{a.key}] {a.label} — {a.description}")
        else:
            typer.echo("\nNo achievements yet — keep running to earn XP!")

    @quest_app.command("achievements")
    def achievements_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit achievements as JSON."),
        ] = False,
    ) -> None:
        """List all unlocked achievements.

        Achievements are milestone markers based on verified-run counts,
        streak length, boss defeats, and level reached.
        """
        repo_root = _resolve_repo_root()
        receipts = _load_receipts(repo_root)
        tasks = _load_tasks(repo_root)
        now = utc_now()
        log = compute_quests(receipts, tasks, now=now)

        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "achievements": log.to_dict()["achievements"],
                        "count": len(log.achievements),
                    },
                    indent=2,
                )
            )
            return

        if not log.achievements:
            typer.echo(
                "No achievements unlocked yet — run `onmc loop` to earn your first XP!"
            )
            return
        typer.echo(f"Unlocked achievements ({len(log.achievements)}):")
        for a in log.achievements:
            typer.echo(f"  [{a.key}] {a.label}")
            typer.echo(f"    {a.description}")

    @quest_app.command("stats")
    def stats_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit stats as JSON."),
        ] = False,
    ) -> None:
        """Show level, total XP, streak, and run counts.

        A compact summary suitable for dashboards or status lines.
        """
        repo_root = _resolve_repo_root()
        receipts = _load_receipts(repo_root)
        tasks = _load_tasks(repo_root)
        now = utc_now()
        log = compute_quests(receipts, tasks, now=now)

        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "level": log.level,
                        "total_xp": log.total_xp,
                        "xp_to_next": log.xp_to_next,
                        "streak_days": log.streak_days,
                        "total_runs": log.total_runs,
                        "verified_total": log.verified_total,
                        "achievements": len(log.achievements),
                        "active_quests": len(log.active_quests),
                        "boss_fights": len(log.boss_fights),
                    },
                    indent=2,
                )
            )
            return

        typer.echo(f"Level:          {log.level}")
        typer.echo(f"Total XP:       {log.total_xp}")
        typer.echo(f"XP to next:     {log.xp_to_next}")
        typer.echo(f"Streak:         {log.streak_days} day(s)")
        typer.echo(f"Runs (verified):{log.verified_total}/{log.total_runs}")
        typer.echo(f"Achievements:   {len(log.achievements)}")
        typer.echo(f"Active quests:  {len(log.active_quests)}")
        typer.echo(f"Boss fights:    {len(log.boss_fights)}")

    app.add_typer(quest_app, name="quest")
