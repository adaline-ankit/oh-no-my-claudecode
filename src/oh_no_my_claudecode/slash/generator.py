"""Discover onmc's commands and render Claude Code command files.

Pure + deterministic: no filesystem writes happen here (see
:mod:`.installer`).  Command discovery reuses the built Typer ``app`` exactly
like ``scripts/generate-cli-reference.py`` — there is deliberately NO hardcoded
command list, so a new self-registering feature appears as a slash command
automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import typer.main

from oh_no_my_claudecode.cli import app

# A marker line embedded in every generated file so ``list``/``uninstall`` only
# ever touch onmc-generated command files, never a user's hand-authored ones.
GENERATED_MARKER = (
    "<!-- generated-by: onmc slash (do not edit; regenerate with `onmc slash install`) -->"
)

# Top-level commands that are internal plumbing / not useful as a user slash
# command.  Everything else the Typer app exposes becomes a slash command.
_SKIP_COMMANDS = frozenset({"serve", "slash"})


@dataclass(frozen=True)
class SlashCommand:
    """One onmc command surfaced as a Claude Code slash command.

    ``name`` is the onmc command (e.g. ``"why"``); the slash command is
    ``/onmc-why`` and the backing file is ``onmc-why.md``.
    """

    name: str
    help: str
    takes_args: bool

    @property
    def slash(self) -> str:
        return f"/onmc-{self.name}"

    @property
    def filename(self) -> str:
        return f"onmc-{self.name}.md"


def _clean(text: str | None) -> str:
    """Collapse a Typer help blurb to a single tidy line."""
    if not text:
        return ""
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)  # strip ANSI
    first = text.strip().splitlines()[0] if text.strip() else ""
    return " ".join(first.split())


def discover_slash_commands(root_app: typer.Typer | None = None) -> list[SlashCommand]:
    """Enumerate every top-level onmc command as a :class:`SlashCommand`.

    Only top-level commands are surfaced (one ``/onmc-<cmd>`` each); subcommands
    are reached by passing arguments (``/onmc-swarm plan ...``).  Deterministic,
    sorted, with internal plumbing commands filtered out.
    """
    command: Any = typer.main.get_command(root_app if root_app is not None else app)
    subcommands = getattr(command, "commands", None) or {}
    out: list[SlashCommand] = []
    for name in sorted(subcommands):
        if name in _SKIP_COMMANDS:
            continue
        node = subcommands[name]
        help_text = _clean(getattr(node, "help", None) or getattr(node, "short_help", None))
        # A group (has its own subcommands) or a leaf with params both accept
        # trailing arguments; only a truly param-less leaf does not.
        has_sub = bool(getattr(node, "commands", None))
        params = [p for p in getattr(node, "params", []) if getattr(p, "name", None) != "help"]
        out.append(SlashCommand(name=name, help=help_text, takes_args=has_sub or bool(params)))
    return out


def render_command_file(cmd: SlashCommand) -> str:
    """Render the Claude Code command-file markdown for one onmc command.

    The file wraps the onmc CLI call: it injects the command's output as context
    (via a ``!`` shell line) and instructs Claude to present it.  Matches the
    format of onmc's existing hand-authored plugin command files.
    """
    arg_hint = "\nargument-hint: <args>" if cmd.takes_args else ""
    desc = cmd.help or f"Run onmc {cmd.name}"
    # allowed-tools scopes auto-approval to just this onmc subcommand.
    args_token = " $ARGUMENTS" if cmd.takes_args else ""
    return f"""---
description: {desc}{arg_hint}
allowed-tools: Bash(onmc {cmd.name}:*)
---

{GENERATED_MARKER}

Run `onmc {cmd.name}` and present the result to the user.

## Context

!`onmc {cmd.name}{args_token} 2>&1 || echo "onmc failed — is onmc installed and 'onmc init' run?"`

## Task

Review the `onmc {cmd.name}` output above and present the key findings to the user
concisely. {desc}.
"""
