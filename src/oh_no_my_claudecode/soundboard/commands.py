"""CLI surface for the ``soundboard`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc soundboard`` ships with
**zero edits** to ``cli.py`` or any other shared hub.

``onmc soundboard`` maps session events to fun inline terminal reactions
(emoji / ASCII / optional terminal bell ``\\a``).  State is stored in
``.onmc/soundboard/`` under the repository root:

- ``bindings.json`` — user override map of ``{event: reaction_text}``.

This feature is **distinct from** ``onmc notify`` (which routes events to
external sinks such as Discord or Slack).  Soundboard is purely inline:
it prints a string directly to the terminal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.soundboard.board import (
    SOUNDBOARD_SUBDIR,
    Reaction,
    load_bindings,
    merged_bindings,
    react,
    save_bindings,
)

soundboard_app = typer.Typer(
    help=(
        "Fun inline terminal reactions for session events "
        "(emoji / ASCII / optional terminal bell)."
    ),
    no_args_is_help=True,
)


def _resolve_soundboard_dir() -> Path:
    """Resolve ``.onmc/soundboard`` from cwd, falling back to ``$HOME/.onmc/soundboard``."""
    cwd = Path.cwd()
    # Walk up looking for a .onmc directory (repo root heuristic).
    for parent in [cwd, *cwd.parents]:
        candidate = parent / ".onmc"
        if candidate.is_dir():
            return candidate / "soundboard"
    # No repo root found — fall back to home directory.
    return Path.home() / SOUNDBOARD_SUBDIR


def register(app: typer.Typer) -> None:
    """Register the ``onmc soundboard`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(soundboard_app, name="soundboard")


# ---------------------------------------------------------------------------
# react
# ---------------------------------------------------------------------------


@soundboard_app.command("react")
def react_command(
    event: Annotated[str, typer.Argument(help="Event name to react to (e.g. test_pass).")],
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the reaction as a JSON envelope."),
    ] = False,
) -> None:
    """Emit the reaction for a session event.

    The reaction is looked up from the default map plus any user overrides
    stored in ``.onmc/soundboard/bindings.json``.  Unknown events emit a safe
    default ``"…"`` reaction rather than erroring.

    Examples:

        onmc soundboard react test_pass

        onmc soundboard react build_break --json

        onmc soundboard react pr_merged
    """
    sb_dir = _resolve_soundboard_dir()
    user = load_bindings(sb_dir)
    bindings = merged_bindings(user)
    reaction: Reaction = react(event, bindings)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "kind": "soundboard_reaction",
                    "event": reaction.event,
                    "text": reaction.text,
                    "has_bell": reaction.has_bell,
                },
                indent=2,
            )
        )
        return
    typer.echo(reaction.emit())


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@soundboard_app.command("list")
def list_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit all bindings as a JSON envelope."),
    ] = False,
) -> None:
    """List all event→reaction bindings (defaults merged with user overrides).

    User overrides (set with ``onmc soundboard bind``) are marked with an
    asterisk ``*`` in the plain-text output.

    Examples:

        onmc soundboard list

        onmc soundboard list --json
    """
    sb_dir = _resolve_soundboard_dir()
    user = load_bindings(sb_dir)
    all_bindings = merged_bindings(user)

    if as_json:
        payload = {
            event: {"text": text, "user_override": event in user}
            for event, text in sorted(all_bindings.items())
        }
        typer.echo(
            json.dumps(
                {"kind": "soundboard_list", "bindings": payload},
                indent=2,
            )
        )
        return

    typer.echo("Soundboard event reactions (* = user override):\n")
    for event_name, text in sorted(all_bindings.items()):
        marker = "* " if event_name in user else "  "
        typer.echo(f"{marker}{event_name:<30s}  {text}")


# ---------------------------------------------------------------------------
# bind
# ---------------------------------------------------------------------------


@soundboard_app.command("bind")
def bind_command(
    event: Annotated[str, typer.Argument(help="Event name to bind (e.g. test_pass).")],
    reaction_text: Annotated[str, typer.Argument(help='Reaction string (e.g. "🎉 nice!").')],
    bell: Annotated[
        bool,
        typer.Option(
            "--bell",
            help="Append a terminal bell (\\a) to the reaction.",
        ),
    ] = False,
) -> None:
    """Set or override the reaction for an event.

    The binding is persisted to ``.onmc/soundboard/bindings.json``.
    Pass ``--bell`` to also sound a terminal bell when the reaction fires.

    Examples:

        onmc soundboard bind test_pass "✅ all green!"

        onmc soundboard bind build_break "💀 rip" --bell

        onmc soundboard bind deploy_done "🚢 sailing!"
    """
    sb_dir = _resolve_soundboard_dir()
    user = load_bindings(sb_dir)
    stored = reaction_text + "\a" if bell else reaction_text
    user[event] = stored
    save_bindings(user, sb_dir)
    bell_note = " (with bell)" if bell else ""
    typer.echo(f"Bound {event!r} → {reaction_text!r}{bell_note}")


# ---------------------------------------------------------------------------
# unbind
# ---------------------------------------------------------------------------


@soundboard_app.command("unbind")
def unbind_command(
    event: Annotated[str, typer.Argument(help="Event name to remove the override for.")],
) -> None:
    """Remove a user override, restoring the default reaction.

    If the event has no user override, the command exits cleanly without error.

    Examples:

        onmc soundboard unbind test_pass

        onmc soundboard unbind build_break
    """
    sb_dir = _resolve_soundboard_dir()
    user = load_bindings(sb_dir)
    if event not in user:
        typer.echo(f"No user override for {event!r} — nothing to remove.")
        return
    del user[event]
    save_bindings(user, sb_dir)
    typer.echo(f"Removed override for {event!r} — default reaction restored.")
