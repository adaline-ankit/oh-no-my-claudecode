"""CLI surface for the ``coach`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time.  All rendering is inline here — no shared hub is
touched.  Streak state is persisted to ``.onmc/coach/streak.json`` in the
current git repository.

``coach`` is a personality layer distinct from ``roast``
(which scores agent-readiness).  ``coach`` reacts to per-event session
activity with hype/roast/dry quips and tracks live streaks.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.coach.commentary import (
    StreakState,
    advance,
    quip,
)
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root

coach_app = typer.Typer(
    help=(
        "Live hype/roast session commentator + streaks. "
        "Reacts to coding-session events with personality-driven quips "
        "and tracks your green/red streak."
    ),
    no_args_is_help=True,
)

# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

_STREAK_FILE = Path(".onmc") / "coach" / "streak.json"


def _streak_path(repo_root: Path) -> Path:
    return repo_root / _STREAK_FILE


def _load_state(repo_root: Path) -> StreakState:
    """Load persisted streak state, or return a blank state."""
    path = _streak_path(repo_root)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return StreakState.from_dict(data)
        except Exception:  # noqa: BLE001, S110 - corrupt file → reset silently
            return StreakState()
    return StreakState()


def _save_state(repo_root: Path, state: StreakState) -> None:
    """Persist streak state to disk."""
    path = _streak_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2))


def _resolve_repo_root() -> Path:
    """Return the git repo root, or raise typer.Exit(1)."""
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("error: no git repository found from the current directory.", err=True)
        raise typer.Exit(code=1) from None


# ---------------------------------------------------------------------------
# Tone enum
# ---------------------------------------------------------------------------


class Tone(StrEnum):
    """Available commentary tones."""

    HYPE = "hype"
    ROAST = "roast"
    DRY = "dry"


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


@coach_app.command("react")
def react_command(
    event: Annotated[
        str,
        typer.Argument(
            help=(
                "Event kind to react to. "
                "Recognised: test_pass, test_fail, pr_merged, build_break, "
                "build_pass, commit, revert, lint_pass, lint_fail, "
                "deploy_pass, deploy_fail, review_approved, review_rejected."
            ),
        ),
    ],
    tone: Annotated[
        Tone,
        typer.Option(
            "--tone",
            help="Commentary personality: hype, roast, or dry.",
        ),
    ] = Tone.HYPE,
    from_file: Annotated[
        Path | None,
        typer.Option(
            "--from-file",
            help="Read the event kind from the last word of the first line of FILE.",
            metavar="FILE",
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the result as JSON."),
    ] = False,
) -> None:
    """React to a coding-session event with a quip + updated streak.

    The quip is deterministic: the same event, tone, and current event count
    always produce the same line.  Streak state is persisted across calls in
    ``.onmc/coach/streak.json``.

    Examples:

        onmc coach react test_pass

        onmc coach react pr_merged --tone roast

        onmc coach react build_break --tone dry --json
    """
    if from_file is not None:
        try:
            first_line = from_file.read_text().splitlines()[0]
            event = first_line.split()[-1]
        except (OSError, IndexError):
            typer.echo(f"error: could not read event from {from_file}", err=True)
            raise typer.Exit(code=1) from None

    repo_root = _resolve_repo_root()
    state = _load_state(repo_root)

    # Quip seed = total events BEFORE advancing (consistent: first event → seed 0)
    seed = state.total_events
    line = quip(event, str(tone), seed=seed)

    new_state = advance(state, event)
    _save_state(repo_root, new_state)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "kind": "coach_react",
                    "event": event,
                    "tone": str(tone),
                    "quip": line,
                    "streak": new_state.to_dict(),
                },
                indent=2,
            )
        )
        return

    # Plain text output
    streak_info = ""
    if new_state.current_streak >= 3:
        streak_info = f"  🔥 {new_state.current_streak}-event streak!"
    elif new_state.current_streak == 0 and event in {"test_fail", "build_break", "revert",
                                                       "lint_fail", "deploy_fail",
                                                       "review_rejected"}:
        streak_info = "  streak reset."

    typer.echo(f"\n  {line}{streak_info}\n")


@coach_app.command("streak")
def streak_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit streak data as JSON."),
    ] = False,
) -> None:
    """Show the current streak, best streak, combo meter, and recent events.

    Examples:

        onmc coach streak

        onmc coach streak --json
    """
    repo_root = _resolve_repo_root()
    state = _load_state(repo_root)

    if as_json:
        typer.echo(
            json.dumps(
                {"kind": "coach_streak", "streak": state.to_dict()},
                indent=2,
            )
        )
        return

    recent = list(state.recent_events[-10:])
    recent_str = " → ".join(recent) if recent else "(none)"

    typer.echo(
        f"\n"
        f"  current streak : {state.current_streak}\n"
        f"  best streak    : {state.best_streak}\n"
        f"  combo meter    : {state.combo} green events total\n"
        f"  total events   : {state.total_events}\n"
        f"  recent events  : {recent_str}\n"
    )


@coach_app.command("cheer")
def cheer_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the cheer as JSON."),
    ] = False,
) -> None:
    """A random-but-deterministic pep line seeded from your event count.

    The same event count always yields the same pep line — fully reproducible,
    no wallclock, no random module.

    Examples:

        onmc coach cheer

        onmc coach cheer --json
    """
    repo_root = _resolve_repo_root()
    state = _load_state(repo_root)

    # Deterministic: seed = total_events (even if 0)
    seed = state.total_events
    line = quip("commit", "hype", seed=seed)

    if as_json:
        typer.echo(
            json.dumps(
                {"kind": "coach_cheer", "quip": line, "seed": seed},
                indent=2,
            )
        )
        return

    typer.echo(f"\n  {line}\n")


# ---------------------------------------------------------------------------
# Auto-discovery entry point
# ---------------------------------------------------------------------------


def register(app: typer.Typer) -> None:
    """Register the ``onmc coach`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(coach_app, name="coach")
