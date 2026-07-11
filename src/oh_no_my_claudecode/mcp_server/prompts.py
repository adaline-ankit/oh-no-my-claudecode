"""MCP prompts — surface onmc's commands as Claude Code slash commands.

Claude Code renders every MCP-server prompt as a slash command named
``/mcp__<server>__<prompt>`` (so onmc's prompts appear as
``/mcp__onmc__why`` …).  Unlike the ``onmc slash`` command-file route, this
needs NO file copying and NO reload of a startup command dir — the moment the
``onmc`` MCP server advertises the ``prompts`` capability, the commands appear
for anyone who already wired ``onmc serve --mcp``.

The command list is discovered from the SAME built Typer app that ``onmc
slash`` and the cli-reference generator use, so a new self-registering feature
becomes an MCP prompt automatically — one source of truth, no drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import GetPromptResult, Prompt, PromptArgument, PromptMessage, TextContent

if TYPE_CHECKING:
    from oh_no_my_claudecode.slash.generator import SlashCommand

_ARGS = "args"


def _discover() -> list[SlashCommand]:
    # Imported lazily: slash.generator builds the Typer app (via cli), and cli
    # imports this MCP package — a module-level import would be circular.
    from oh_no_my_claudecode.slash.generator import discover_slash_commands

    return discover_slash_commands()


def _prompt_for(cmd: SlashCommand) -> Prompt:
    """Build an MCP Prompt descriptor for one onmc command."""
    arguments = (
        [
            PromptArgument(
                name=_ARGS,
                description=f"Arguments passed through to `onmc {cmd.name}` (e.g. flags, a path).",
                required=False,
            )
        ]
        if cmd.takes_args
        else []
    )
    return Prompt(
        name=cmd.name,
        description=cmd.help or f"Run onmc {cmd.name}.",
        arguments=arguments,
    )


def list_onmc_prompts() -> list[Prompt]:
    """List every top-level onmc command as an MCP prompt (sorted, deterministic)."""
    return [_prompt_for(cmd) for cmd in _discover()]


def _command_index() -> dict[str, SlashCommand]:
    return {cmd.name: cmd for cmd in _discover()}


def render_prompt_text(cmd: SlashCommand, args: str) -> str:
    """The instruction text Claude receives when the prompt is invoked."""
    invocation = f"onmc {cmd.name}" + (f" {args}".rstrip() if args else "")
    return (
        f"Run the shell command `{invocation}` and present its output to the user "
        f"concisely. This is the onmc `{cmd.name}` command: {cmd.help or ''}\n\n"
        "If the command is not found, tell the user to install onmc "
        "(`uv tool install oh-no-my-claudecode`) and run `onmc init` in this repo."
    ).strip()


def get_onmc_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
    """Resolve a prompt invocation into a message instructing the onmc call.

    Unknown prompt names raise ``ValueError`` (the MCP layer maps this to a
    protocol error), matching how the tool handler rejects unknown tools.
    """
    cmd = _command_index().get(name)
    if cmd is None:
        raise ValueError(f"unknown onmc prompt: {name}")
    args = (arguments or {}).get(_ARGS, "") if cmd.takes_args else ""
    text = render_prompt_text(cmd, args)
    return GetPromptResult(
        description=cmd.help or f"onmc {cmd.name}",
        messages=[PromptMessage(role="user", content=TextContent(type="text", text=text))],
    )
