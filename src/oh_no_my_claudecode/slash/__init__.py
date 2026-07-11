"""onmc slash — expose onmc's commands as Claude Code slash commands.

Claude Code's ``/`` menu is fed by command files (``.claude/commands/*.md``),
skills, plugin commands, and MCP prompts — NOT by an external binary's
subcommands.  So ``onmc why`` never appears as ``/onmc-why`` on its own.

This module closes that gap: it auto-discovers every top-level onmc command
from the built Typer app (the same discovery the cli-reference generator uses,
so a new self-registering feature shows up automatically) and renders a Claude
Code command file per command that wraps the CLI call.  ``onmc slash install``
writes them into ``~/.claude/commands`` (user) or ``./.claude/commands``
(project); ``list`` and ``uninstall`` manage only the files onmc generated
(tracked by a marker line), never hand-authored ones.
"""

from __future__ import annotations

from oh_no_my_claudecode.slash.generator import (
    GENERATED_MARKER,
    SlashCommand,
    discover_slash_commands,
    render_command_file,
)
from oh_no_my_claudecode.slash.installer import (
    InstallResult,
    commands_dir,
    install_slash_commands,
    list_installed,
    uninstall_slash_commands,
)

__all__ = [
    "GENERATED_MARKER",
    "SlashCommand",
    "discover_slash_commands",
    "render_command_file",
    "InstallResult",
    "commands_dir",
    "install_slash_commands",
    "list_installed",
    "uninstall_slash_commands",
]
