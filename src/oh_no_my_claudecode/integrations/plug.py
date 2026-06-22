"""onmc plug — one-shot wizard to wire onmc into a target coding agent.

Targets
-------
claude-code  Install Claude Code hooks + .mcp.json (delegates to the
             existing install_claude_hooks function — no new logic).
             Also installs slash-command markdown files into the repo's
             ``.claude/commands/`` directory so users get /onmc-why,
             /onmc-guard, /onmc-brief, and /onmc-statusline.
codex        Write/refresh an AGENTS.md stanza so Codex runs
             ``onmc brief`` and ``onmc guard`` at session start and
             knows how to reach the MCP server.
cursor       Write/refresh a ``.cursor/rules/onmc.md`` Cursor rules file
             (Cursor >=0.40 style; the older ``.cursorrules`` file is
             written as a fallback note in the docs).
omc          Write a copy-paste OMC adapter under docs/integrations/omc.md.
             (OMC's hook API is assumed/documented; we never write into
             OMC config directories we don't own.)
omx          Same approach as omc, targeting oh-my-codex.
all          Apply claude-code + codex + cursor (the "safe subset" that
             writes only well-understood config paths).

Idempotency
-----------
Every file write is guarded by a sentinel comment/marker.  Re-running
``onmc plug <target>`` is always safe.  The sentinel for text files is::

    <!-- onmc-plug: managed by onmc plug — do not remove this line -->

For JSON files (claude-code target) idempotency is handled by the
underlying install_claude_hooks function.

Slash commands (claude-code target)
------------------------------------
The canonical command files live in ``.claude-plugin/commands/`` in the
onmc package directory.  ``onmc plug claude-code`` copies them into the
target repo's ``.claude/commands/`` so they are available as project-scoped
slash commands even without the plugin installed.  The plugin's
``plugin.json`` also references ``.claude-plugin/commands`` so users who
install via the marketplace get the same commands automatically.

Spec reference: https://code.claude.com/docs/en/agent-sdk/slash-commands
"""

from __future__ import annotations

import shutil
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from oh_no_my_claudecode.hooks.installer import (
    HookInstallResult,
    install_claude_hooks,
    mcp_config_path,
    project_settings_path,
)

# ---------------------------------------------------------------------------
# Slash-command constants
# ---------------------------------------------------------------------------

# Canonical location of the command markdown files, relative to this module's
# package root (two levels up from integrations/plug.py → package root).
_PLUGIN_COMMANDS_DIR: Path = (
    Path(__file__).parent.parent.parent.parent  # repo root when installed from source
    / ".claude-plugin"
    / "commands"
)

# Names of the command files shipped by onmc (without .md extension).
SLASH_COMMAND_NAMES: tuple[str, ...] = (
    "onmc-why",
    "onmc-guard",
    "onmc-brief",
    "onmc-statusline",
)

# ---------------------------------------------------------------------------
# Sentinel embedded in every managed text block.
# ---------------------------------------------------------------------------

_SENTINEL = "<!-- onmc-plug: managed by onmc plug — do not remove this line -->"

TargetName = Literal["claude-code", "codex", "cursor", "omc", "omx", "all"]

SUPPORTED_TARGETS: list[str] = ["claude-code", "codex", "cursor", "omc", "omx", "all"]


@dataclass(slots=True)
class PlugResult:
    """Result of a ``plug_target`` call."""

    target: str
    files_written: list[str] = field(default_factory=list)
    files_skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def plug_target(target: str, *, repo_root: Path) -> PlugResult:
    """Wire onmc into *target* agent for the repo at *repo_root*.

    Returns a :class:`PlugResult` describing what was written.  Raises
    ``ValueError`` for unknown targets.
    """
    if target == "all":
        result = PlugResult(target="all")
        for sub in ("claude-code", "codex", "cursor"):
            sub_result = plug_target(sub, repo_root=repo_root)
            result.files_written.extend(sub_result.files_written)
            result.files_skipped.extend(sub_result.files_skipped)
            result.notes.extend(sub_result.notes)
        return result

    dispatch: dict[str, Callable[..., PlugResult]] = {
        "claude-code": _plug_claude_code,
        "codex": _plug_codex,
        "cursor": _plug_cursor,
        "omc": _plug_omc,
        "omx": _plug_omx,
    }
    fn = dispatch.get(target)
    if fn is None:
        known = ", ".join(SUPPORTED_TARGETS)
        msg = f"Unknown target {target!r}. Supported targets: {known}"
        raise ValueError(msg)
    return fn(repo_root=repo_root)


# ---------------------------------------------------------------------------
# claude-code
# ---------------------------------------------------------------------------

_CLAUDE_CODE_DOCS_PATH = "docs/integrations/claude-code.md"


def install_slash_commands(*, repo_root: Path) -> tuple[list[str], list[str]]:
    """Copy onmc slash-command markdown files into *repo_root*/.claude/commands/.

    Returns ``(files_written, files_skipped)`` — each entry is an absolute path
    string.  Writes are idempotent: if the destination file is already identical
    to the source, it is counted as skipped.

    The source files live in the onmc package tree under
    ``.claude-plugin/commands/``.  If that directory is not found (e.g. when
    running from an editable install in a non-standard layout), the function
    returns empty lists so callers degrade gracefully.
    """
    src_dir = _PLUGIN_COMMANDS_DIR
    if not src_dir.is_dir():
        return [], []

    dest_dir = repo_root / ".claude" / "commands"
    dest_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    skipped: list[str] = []

    for name in SLASH_COMMAND_NAMES:
        src = src_dir / f"{name}.md"
        if not src.exists():
            continue
        dest = dest_dir / f"{name}.md"
        src_content = src.read_bytes()
        if dest.exists() and dest.read_bytes() == src_content:
            skipped.append(str(dest))
        else:
            shutil.copy2(src, dest)
            written.append(str(dest))

    return written, skipped


def _plug_claude_code(*, repo_root: Path) -> PlugResult:
    """Install Claude Code hooks, .mcp.json, and project-scoped slash commands."""
    result = PlugResult(target="claude-code")

    settings_path = project_settings_path(repo_root)
    mcp_path = mcp_config_path(repo_root)

    install_result: HookInstallResult = install_claude_hooks(
        repo_root=repo_root,
        register_mcp=True,
    )

    if install_result.backup_created:
        result.files_written.append(str(install_result.backup_path))
    result.files_written.append(str(settings_path))
    result.files_written.append(str(mcp_path))

    # Install slash commands into .claude/commands/
    cmd_written, cmd_skipped = install_slash_commands(repo_root=repo_root)
    result.files_written.extend(cmd_written)
    result.files_skipped.extend(cmd_skipped)

    result.notes.append(
        "Claude Code hooks installed: PreCompact, SessionStart, UserPromptSubmit, SessionEnd."
    )
    result.notes.append("MCP server registered in .mcp.json as 'onmc'.")
    if cmd_written:
        names = ", ".join(f"/{n}" for n in SLASH_COMMAND_NAMES)
        result.notes.append(f"Slash commands installed: {names}")
    result.notes.append(
        "Tip: users can also install via plugin marketplace — "
        "see docs/integrations/claude-code.md for the /plugin command."
    )
    result.notes.append(f"See {_CLAUDE_CODE_DOCS_PATH} for details.")
    return result


# ---------------------------------------------------------------------------
# codex
# ---------------------------------------------------------------------------

_CODEX_MARKER = "<!-- onmc-plug:codex -->"
_CODEX_MARKER_END = "<!-- /onmc-plug:codex -->"

_CODEX_STANZA = textwrap.dedent("""\
    {marker_start}
    ## Using ONMC memory (managed by `onmc plug codex` — do not edit this block)

    {sentinel}

    ONMC ships repo-native memory. Run these commands at session start:

    ```bash
    # 1. Get a task-focused context brief (fast, no LLM)
    onmc brief --task "$TASK" --stdout

    # 2. Surface recorded dead-ends — never repeat a known failure
    onmc guard --task "$TASK"

    # 3. (Optional) MCP tools mid-session
    onmc serve --mcp &
    ```

    ### MCP server — Codex config.toml (copy-paste)

    Add to `~/.codex/config.toml` or `.codex/config.toml`:

    ```toml
    [mcp_servers.onmc]
    command = "onmc serve --mcp"
    enabled = true
    ```

    Or run: `codex mcp add onmc -- onmc serve --mcp`

    ### MCP tools (when `onmc serve --mcp` is running)

    | Tool | Purpose |
    |---|---|
    | `search_memory` | Semantic search over repo decisions, invariants, hotspots |
    | `guard_task` | Ranked list of recorded dead-ends for a task |
    | `get_brief` | Compile a task-focused brief on demand |

    ### Fresh clone / cloud container

    ```bash
    onmc init && onmc sync --restore
    onmc brief --task "..." --stdout
    ```

    See [docs/integrations/codex.md](docs/integrations/codex.md) for full instructions.
    {marker_end}
""").format(
    marker_start=_CODEX_MARKER,
    sentinel=_SENTINEL,
    marker_end=_CODEX_MARKER_END,
)


def _plug_codex(*, repo_root: Path) -> PlugResult:
    """Write/refresh the AGENTS.md onmc stanza."""
    result = PlugResult(target="codex")
    agents_md = repo_root / "AGENTS.md"

    existing = agents_md.read_text(encoding="utf-8") if agents_md.exists() else ""

    if _CODEX_MARKER in existing:
        if _SENTINEL in existing:
            # Stanza already present and up to date — nothing to do.
            result.files_skipped.append(str(agents_md))
            return result
        # Markers present but sentinel missing (stanza is stale) — replace.
        new_content = _replace_between_markers(
            existing, _CODEX_MARKER, _CODEX_MARKER_END, _CODEX_STANZA
        )
        agents_md.write_text(new_content, encoding="utf-8")
        result.files_written.append(str(agents_md))
        result.notes.append("Refreshed onmc stanza in AGENTS.md.")
        return result

    # Append the stanza.
    separator = "\n" if existing.endswith("\n") else "\n\n"
    agents_md.write_text(existing + separator + _CODEX_STANZA, encoding="utf-8")
    result.files_written.append(str(agents_md))
    result.notes.append("Added onmc stanza to AGENTS.md.")
    return result


# ---------------------------------------------------------------------------
# cursor
# ---------------------------------------------------------------------------

_CURSOR_MARKER = "<!-- onmc-plug:cursor -->"
_CURSOR_MARKER_END = "<!-- /onmc-plug:cursor -->"

_CURSOR_STANZA = textwrap.dedent("""\
    {marker_start}
    ## ONMC memory context (managed by `onmc plug cursor` — do not edit this block)

    {sentinel}

    Before starting any task, run in the terminal:

    ```bash
    onmc brief --task "DESCRIBE YOUR TASK" --stdout
    onmc guard --task "DESCRIBE YOUR TASK"
    ```

    `onmc brief` returns the most relevant repo memories, hotspots, and
    architectural decisions for your task.  `onmc guard` lists recorded
    dead-ends so you never retry a known failure.

    ### MCP server (optional, for tool access)

    ```bash
    onmc serve --mcp
    ```

    Available tools: `search_memory`, `guard_task`, `get_brief`.

    See [docs/integrations/cursor.md](docs/integrations/cursor.md) for full instructions.
    {marker_end}
""").format(
    marker_start=_CURSOR_MARKER,
    sentinel=_SENTINEL,
    marker_end=_CURSOR_MARKER_END,
)


def _plug_cursor(*, repo_root: Path) -> PlugResult:
    """Write/refresh .cursor/rules/onmc.md (Cursor >=0.40 format)."""
    result = PlugResult(target="cursor")
    rules_file = repo_root / ".cursor" / "rules" / "onmc.md"

    existing = rules_file.read_text(encoding="utf-8") if rules_file.exists() else ""

    if _CURSOR_MARKER in existing:
        if _SENTINEL in existing:
            # Stanza already present and up to date — nothing to do.
            result.files_skipped.append(str(rules_file))
            return result
        # Markers present but sentinel missing (stanza is stale) — replace.
        new_content = _replace_between_markers(
            existing, _CURSOR_MARKER, _CURSOR_MARKER_END, _CURSOR_STANZA
        )
        rules_file.write_text(new_content, encoding="utf-8")
        result.files_written.append(str(rules_file))
        result.notes.append("Refreshed onmc stanza in .cursor/rules/onmc.md.")
        return result

    rules_file.parent.mkdir(parents=True, exist_ok=True)
    content = existing + ("\n" if existing else "") + _CURSOR_STANZA
    rules_file.write_text(content, encoding="utf-8")
    result.files_written.append(str(rules_file))
    result.notes.append("Wrote .cursor/rules/onmc.md (Cursor >=0.40 rules format).")
    result.notes.append(
        "Older Cursor versions use .cursorrules — see docs/integrations/cursor.md."
    )
    return result


# ---------------------------------------------------------------------------
# omc (oh-my-claudecode)
# ---------------------------------------------------------------------------


def _plug_omc(*, repo_root: Path) -> PlugResult:
    """Write docs/integrations/omc.md with a copy-paste OMC adapter."""
    result = PlugResult(target="omc")
    docs_dir = repo_root / "docs" / "integrations"
    docs_dir.mkdir(parents=True, exist_ok=True)
    omc_doc = docs_dir / "omc.md"

    if omc_doc.exists() and _SENTINEL in omc_doc.read_text(encoding="utf-8"):
        result.files_skipped.append(str(omc_doc))
        result.notes.append("docs/integrations/omc.md already up to date.")
        return result

    omc_doc.write_text(_OMC_ADAPTER_DOC, encoding="utf-8")
    result.files_written.append(str(omc_doc))
    result.notes.append(
        "Wrote docs/integrations/omc.md with copy-paste OMC adapter instructions."
    )
    result.notes.append(
        "NOTE: OMC's hook API is assumed based on its documented skill/hook model. "
        "Verify hook point names against your installed OMC version."
    )
    return result


_OMC_ADAPTER_DOC = textwrap.dedent(f"""\
    # Using onmc with oh-my-claudecode (OMC)

    {_SENTINEL}

    > **Assumption notice**: OMC's exact plugin/hook API is inferred from its
    > documented skill and hook model.  Verify the hook-point names
    > (`pre_task`, `post_task`) against your installed OMC version.  The
    > adapter commands (`onmc brief`, `onmc guard`) are stable.

    ## What this gives you

    - `onmc brief --task "$TASK"` — surfaces the most relevant repo memories,
      hotspots, and architectural decisions before OMC dispatches an agent.
    - `onmc guard --task "$TASK"` — lists recorded dead-ends so the dispatched
      agent skips known failures.
    - `onmc serve --mcp` — exposes `search_memory`, `guard_task`, `get_brief`
      as MCP tools that the agent can call mid-session.

    ## Prerequisites

    ```bash
    pip install oh-no-my-claudecode
    cd your-repo
    onmc init && onmc ingest    # build the memory store once
    ```

    ## Copy-paste adapter

    Add this block to your OMC skill file (e.g. `.omc/skills/onmc-memory.md`
    or your OMC project config):

    ```markdown
    ## onmc memory integration

    **Pre-task hook** — run before dispatching any agent:

    ```bash
    onmc brief --task "$TASK" --stdout
    onmc guard --task "$TASK"
    ```

    **Post-task hook** (optional) — record outcomes:

    ```bash
    # After the agent finishes, mine its transcript for new memories:
    onmc mine
    ```

    **MCP server** — start once at session begin so agents get tool access:

    ```bash
    onmc serve --mcp &
    ```
    ```

    ## Shell snippet (direct invocation)

    If OMC exposes a `pre_task` environment variable or hook command, wire it
    like this:

    ```bash
    # In your OMC config or shell rc:
    export OMC_PRE_TASK_HOOK="onmc brief --task \\"$TASK\\" --stdout"
    export OMC_PRE_TASK_HOOK="$OMC_PRE_TASK_HOOK && onmc guard --task \\"$TASK\\""
    export OMC_POST_TASK_HOOK="onmc mine --no-llm"
    ```

    ## Assumed OMC hook points

    | Hook point | When it fires | Recommended command |
    |---|---|---|
    | `pre_task` | Before agent dispatch | `onmc brief --task "$TASK" --stdout` |
    | `pre_task` | Before agent dispatch | `onmc guard --task "$TASK"` |
    | `post_task` | After agent completes | `onmc mine --no-llm` |
    | Session start | When OMC starts | `onmc serve --mcp &` |

    ## MCP tool reference

    | Tool | Description |
    |---|---|
    | `search_memory` | Search repo decisions, invariants, and hotspots |
    | `guard_task` | Return ranked dead-ends for a task description |
    | `get_brief` | Compile a task-focused brief on demand |

    ## Further reading

    - [onmc CLI reference](../cli-reference.md)
    - [Agent-native workflows](../agent-native-workflows.md)
    - [omx adapter](omx.md)
""")


# ---------------------------------------------------------------------------
# omx (oh-my-codex)
# ---------------------------------------------------------------------------


def _plug_omx(*, repo_root: Path) -> PlugResult:
    """Write docs/integrations/omx.md with a copy-paste OMX adapter."""
    result = PlugResult(target="omx")
    docs_dir = repo_root / "docs" / "integrations"
    docs_dir.mkdir(parents=True, exist_ok=True)
    omx_doc = docs_dir / "omx.md"

    if omx_doc.exists() and _SENTINEL in omx_doc.read_text(encoding="utf-8"):
        result.files_skipped.append(str(omx_doc))
        result.notes.append("docs/integrations/omx.md already up to date.")
        return result

    omx_doc.write_text(_OMX_ADAPTER_DOC, encoding="utf-8")
    result.files_written.append(str(omx_doc))
    result.notes.append(
        "Wrote docs/integrations/omx.md with copy-paste OMX adapter instructions."
    )
    result.notes.append(
        "NOTE: OMX's exact hook API is assumed based on Codex AGENTS.md conventions. "
        "Verify hook point names against your installed OMX version."
    )
    return result


_OMX_ADAPTER_DOC = textwrap.dedent(f"""\
    # Using onmc with oh-my-codex (OMX)

    {_SENTINEL}

    > **Assumption notice**: OMX is assumed to follow Codex AGENTS.md conventions
    > and expose pre/post task hooks similar to OMC.  Verify hook-point names
    > against your installed OMX version.

    ## What this gives you

    - `onmc brief --task "$TASK"` — surfaces repo memories and architectural
      context before OMX dispatches Codex.
    - `onmc guard --task "$TASK"` — lists recorded dead-ends so Codex skips
      known failures.
    - `onmc serve --mcp` — exposes `search_memory`, `guard_task`, `get_brief`
      as MCP tools that Codex can call mid-session.

    ## Prerequisites

    ```bash
    pip install oh-no-my-claudecode
    cd your-repo
    onmc init && onmc ingest    # build the memory store once
    onmc plug codex             # write AGENTS.md stanza Codex reads at start
    ```

    ## Copy-paste adapter

    Add this block to your OMX config or project skill file:

    ```markdown
    ## onmc memory integration

    **Pre-task hook** — run before dispatching Codex:

    ```bash
    onmc brief --task "$TASK" --stdout
    onmc guard --task "$TASK"
    ```

    **Post-task hook** (optional):

    ```bash
    onmc mine --no-llm    # extract new memories from the Codex session
    ```

    **MCP server** — start at session begin:

    ```bash
    onmc serve --mcp &
    ```
    ```

    ## AGENTS.md stanza (Codex reads this automatically)

    Run `onmc plug codex` to write the AGENTS.md stanza that Codex reads at
    the start of every session.  OMX passes this file to Codex automatically
    when it launches.

    ## Assumed OMX hook points

    | Hook point | When it fires | Recommended command |
    |---|---|---|
    | `pre_task` | Before Codex dispatch | `onmc brief --task "$TASK" --stdout` |
    | `pre_task` | Before Codex dispatch | `onmc guard --task "$TASK"` |
    | `post_task` | After Codex completes | `onmc mine --no-llm` |
    | Session start | When OMX starts | `onmc serve --mcp &` |

    ## MCP tool reference

    | Tool | Description |
    |---|---|
    | `search_memory` | Search repo decisions, invariants, and hotspots |
    | `guard_task` | Return ranked dead-ends for a task description |
    | `get_brief` | Compile a task-focused brief on demand |

    ## Further reading

    - [onmc CLI reference](../cli-reference.md)
    - [Agent-native workflows](../agent-native-workflows.md)
    - [omc adapter](omc.md)
""")


# ---------------------------------------------------------------------------
# Helper: replace content between markers
# ---------------------------------------------------------------------------


def _replace_between_markers(
    text: str, start_marker: str, end_marker: str, replacement: str
) -> str:
    """Replace the block between *start_marker* and *end_marker* with *replacement*.

    If *end_marker* is not found after *start_marker*, replaces from
    *start_marker* to end of string.
    """
    start_idx = text.find(start_marker)
    if start_idx == -1:
        return text
    end_idx = text.find(end_marker, start_idx)
    if end_idx == -1:
        return text[:start_idx] + replacement
    after_end = text[end_idx + len(end_marker) :]
    return text[:start_idx] + replacement + after_end
