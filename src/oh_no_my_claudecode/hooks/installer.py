from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRE_COMPACT_COMMAND = "onmc hooks pre-compact"
SESSION_START_COMMAND = "onmc hooks session-start"
SESSION_END_COMMAND = "onmc hooks session-end"
PROMPT_RECALL_COMMAND = "onmc hooks prompt-recall"
PRE_TOOL_USE_COMMAND = "onmc hooks pre-tool-use"
LEGACY_POST_COMPACT_COMMAND = "onmc hooks post-compact"
# ``onmc wrap`` layer — make onmc the default layer for Claude Code.
TASK_INTERCEPT_COMMAND = "onmc hooks task-intercept"
PROMPT_ROUTER_COMMAND = "onmc hooks prompt-router"
DECISION_INTERCEPT_COMMAND = "onmc hooks decision-intercept"
RUNTIME_STOP_COMMAND = "onmc hooks runtime-stop"
# Telemetry live event capture — PostToolUse + SubagentStop/Stop.
POST_TOOL_USE_COMMAND = "onmc hooks post-tool-use"
SUBAGENT_STOP_COMMAND = "onmc hooks subagent-stop"
MCP_SERVER_NAME = "onmc"

# Matcher for PreToolUse: fires on file-editing tools only.
_PRE_TOOL_USE_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"
# Matcher for the ``onmc wrap`` Task intercept: the native agent-spawning tool.
_TASK_INTERCEPT_MATCHER = "Task"
_DECISION_INTERCEPT_MATCHER = "AskUserQuestion"

# Commands ``onmc wrap`` installs (and ``onmc unwrap`` removes, exactly).
_WRAP_COMMANDS = frozenset(
    {
        TASK_INTERCEPT_COMMAND,
        PROMPT_ROUTER_COMMAND,
        DECISION_INTERCEPT_COMMAND,
        RUNTIME_STOP_COMMAND,
    }
)

_ONMC_COMMANDS = frozenset(
    {
        PRE_COMPACT_COMMAND,
        SESSION_START_COMMAND,
        SESSION_END_COMMAND,
        PROMPT_RECALL_COMMAND,
        PRE_TOOL_USE_COMMAND,
        LEGACY_POST_COMPACT_COMMAND,
        TASK_INTERCEPT_COMMAND,
        PROMPT_ROUTER_COMMAND,
        DECISION_INTERCEPT_COMMAND,
        RUNTIME_STOP_COMMAND,
        POST_TOOL_USE_COMMAND,
        SUBAGENT_STOP_COMMAND,
    }
)
# "PostCompact" is not a real Claude Code event; earlier onmc versions registered it.
_HOOK_EVENTS = (
    "PreCompact",
    "PostCompact",
    "PreToolUse",
    "PostToolUse",
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "SubagentStop",
    "Stop",
)


def project_settings_path(repo_root: Path) -> Path:
    """Return the project-scoped Claude Code settings.json path."""
    return repo_root / ".claude" / "settings.json"


def project_settings_backup_path(repo_root: Path) -> Path:
    """Return the onmc backup path for the project-scoped settings.json."""
    settings = project_settings_path(repo_root)
    return settings.with_name(f"{settings.name}.onmc-backup")


def mcp_config_path(repo_root: Path) -> Path:
    """Return the project-scoped Claude Code MCP config path (.mcp.json)."""
    return repo_root / ".mcp.json"


def user_settings_path(home: Path | None = None) -> Path:
    """Return the user-level (global) Claude Code settings.json path."""
    return (home or Path.home()) / ".claude" / "settings.json"


@dataclass(slots=True)
class HookInstallResult:
    """Outcome of an install/uninstall pass over the Claude Code config files."""

    settings_path: Path
    backup_path: Path
    mcp_path: Path
    backup_created: bool
    mcp_registered: bool
    legacy_global_cleaned: bool
    # Set when the pre-existing settings.json was unparseable JSON: its raw
    # bytes were copied here before onmc wrote a fresh, valid file, so the
    # user's (broken) content is never silently discarded.
    corrupt_backup_path: Path | None = None


def _preserve_corrupt_settings(settings_path: Path) -> Path | None:
    """Copy a malformed ``settings.json`` aside before it is overwritten.

    Claude Code (and onmc's own readers) treat an unparseable settings.json as
    empty, so writing onmc hooks over it would silently discard whatever the
    user had.  When the file exists and is non-empty but does NOT parse as
    JSON, its raw bytes are copied to ``settings.json.onmc-corrupt`` (once —
    an existing corrupt-backup is never clobbered) and that path is returned.
    Returns ``None`` when the file is absent, empty, or already valid JSON.
    """
    if not settings_path.exists():
        return None
    try:
        raw = settings_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        json.loads(raw)
    except json.JSONDecodeError:
        corrupt_path = settings_path.with_name(f"{settings_path.name}.onmc-corrupt")
        if not corrupt_path.exists():
            corrupt_path.parent.mkdir(parents=True, exist_ok=True)
            corrupt_path.write_text(raw, encoding="utf-8")
        return corrupt_path
    return None


def install_claude_hooks(
    *,
    repo_root: Path,
    register_mcp: bool = True,
    settings_path: Path | None = None,
    backup_path: Path | None = None,
    mcp_path: Path | None = None,
    global_settings_path: Path | None = None,
) -> HookInstallResult:
    """Install project-scoped onmc hooks and (optionally) MCP registration.

    Hooks are merged into ``<repo>/.claude/settings.json``:

    - ``PreCompact`` (matcher ``""``) runs ``onmc hooks pre-compact``.
    - ``SessionStart`` (matcher ``""``) runs ``onmc hooks session-start`` on
      every session start (startup, resume, clear, and compact). The command
      branches internally on the ``source`` field of the stdin payload: it
      injects a boot digest for startup/resume/clear and the continuation brief
      for post-compaction sessions.
    - ``UserPromptSubmit`` (matcher ``""``) runs ``onmc hooks prompt-recall``
      on every user prompt, injecting only the memories most relevant to that
      specific prompt.
    - ``PreToolUse`` (matcher ``"Edit|Write|MultiEdit|NotebookEdit"``) runs
      ``onmc hooks pre-tool-use`` before every file edit, injecting hotspot /
      invariant / failed-approach warnings for the target file.

    MCP registration is merged into ``<repo>/.mcp.json`` (Claude Code does not
    read MCP servers from settings.json). A backup of the pre-install settings
    is written next to settings.json only if no backup exists yet, so a
    reinstall never overwrites the pristine backup. Legacy global entries in
    the user-level ``~/.claude/settings.json`` (from earlier onmc versions,
    including the fabricated ``PostCompact`` event) are removed when found.
    """
    settings_path = settings_path or project_settings_path(repo_root)
    backup_path = backup_path or project_settings_backup_path(repo_root)
    mcp_path = mcp_path or mcp_config_path(repo_root)
    corrupt_backup_path = _preserve_corrupt_settings(settings_path)
    settings = _load_json(settings_path)
    backup_created = False
    if not backup_path.exists():
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(
            json.dumps(settings, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        backup_created = True
    # Migrate any legacy project-level entries (e.g. PostCompact) before merging.
    _strip_onmc_entries(settings)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks
    _merge_command_hook(hooks, event_name="PreCompact", matcher="", command=PRE_COMPACT_COMMAND)
    _merge_command_hook(
        hooks,
        event_name="SessionStart",
        matcher="",
        command=SESSION_START_COMMAND,
    )
    _merge_command_hook(
        hooks,
        event_name="UserPromptSubmit",
        matcher="",
        command=PROMPT_RECALL_COMMAND,
    )
    _merge_command_hook(
        hooks,
        event_name="SessionEnd",
        matcher="",
        command=SESSION_END_COMMAND,
    )
    _merge_command_hook(
        hooks,
        event_name="PreToolUse",
        matcher=_PRE_TOOL_USE_MATCHER,
        command=PRE_TOOL_USE_COMMAND,
    )
    _merge_command_hook(
        hooks,
        event_name="PostToolUse",
        matcher="",
        command=POST_TOOL_USE_COMMAND,
    )
    _merge_command_hook(
        hooks,
        event_name="SubagentStop",
        matcher="",
        command=SUBAGENT_STOP_COMMAND,
    )
    _merge_command_hook(
        hooks,
        event_name="Stop",
        matcher="",
        command=SUBAGENT_STOP_COMMAND,
    )
    _write_json(settings_path, settings)
    if register_mcp:
        _register_mcp_server(mcp_path)
    legacy_global_cleaned = _clean_legacy_global_settings(
        global_settings_path or user_settings_path()
    )
    return HookInstallResult(
        settings_path=settings_path,
        backup_path=backup_path,
        mcp_path=mcp_path,
        backup_created=backup_created,
        mcp_registered=register_mcp,
        legacy_global_cleaned=legacy_global_cleaned,
        corrupt_backup_path=corrupt_backup_path,
    )


def uninstall_claude_hooks(
    *,
    repo_root: Path,
    settings_path: Path | None = None,
    mcp_path: Path | None = None,
    global_settings_path: Path | None = None,
) -> bool:
    """Surgically remove onmc entries from the project Claude Code config files.

    Removes both the current hooks (PreCompact / SessionStart) and any legacy
    entries (PostCompact, ``onmc hooks post-compact``, settings-level
    ``mcpServers.onmc``) while leaving every other hook and server untouched.
    The ``.onmc-backup`` file is kept as a safety artifact and never restored
    wholesale. Also cleans legacy onmc entries from the user-level settings.

    Returns whether legacy global entries were cleaned.
    """
    settings_path = settings_path or project_settings_path(repo_root)
    mcp_path = mcp_path or mcp_config_path(repo_root)
    if settings_path.exists():
        settings = _load_json(settings_path)
        if _strip_onmc_entries(settings):
            _write_json(settings_path, settings)
    _unregister_mcp_server(mcp_path)
    return _clean_legacy_global_settings(global_settings_path or user_settings_path())


def install_wrap_hooks(
    *,
    repo_root: Path,
    strict: bool,
    settings_path: Path | None = None,
    backup_path: Path | None = None,
) -> HookInstallResult:
    """Install the ``onmc wrap`` layer hooks into ``settings.json``.

    Merges four command hooks (idempotently) alongside any existing hooks:

    - ``PreToolUse`` (matcher ``"Task"``) → ``onmc hooks task-intercept`` —
      intercepts native agent-spawning and redirects it to ``onmc swarm``.
    - ``UserPromptSubmit`` (matcher ``""``) → ``onmc hooks prompt-router`` —
      routes each prompt and injects a "prefer onmc paths" nudge.
    - ``PreToolUse`` (matcher ``"AskUserQuestion"``) → ``onmc hooks
      decision-intercept`` — resolves low-risk implementation choices.
    - ``Stop`` (matcher ``""``) → ``onmc hooks runtime-stop`` — refuses
      premature completion while a strict mission contract remains unverified.

    A pristine backup of the pre-wrap settings is written exactly once (never
    overwriting an earlier onmc backup). ``strict`` is conveyed to the running
    hooks via the wrap-state file (see :func:`write_wrap_state`), not the
    settings.json command text, so the installed commands are mode-agnostic and
    ``unwrap`` can remove them verbatim.

    Does NOT touch the base onmc hooks or the MCP registration — wrap is a
    strictly additive layer on top of (or independent of) ``onmc hooks
    install``.
    """
    settings_path = settings_path or project_settings_path(repo_root)
    backup_path = backup_path or project_settings_backup_path(repo_root)
    corrupt_backup_path = _preserve_corrupt_settings(settings_path)
    settings = _load_json(settings_path)
    backup_created = False
    if not backup_path.exists():
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(
            json.dumps(settings, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        backup_created = True
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks
    _merge_command_hook(
        hooks,
        event_name="PreToolUse",
        matcher=_TASK_INTERCEPT_MATCHER,
        command=TASK_INTERCEPT_COMMAND,
    )
    _merge_command_hook(
        hooks,
        event_name="UserPromptSubmit",
        matcher="",
        command=PROMPT_ROUTER_COMMAND,
    )
    _merge_command_hook(
        hooks,
        event_name="PreToolUse",
        matcher=_DECISION_INTERCEPT_MATCHER,
        command=DECISION_INTERCEPT_COMMAND,
    )
    _merge_command_hook(
        hooks,
        event_name="Stop",
        matcher="",
        command=RUNTIME_STOP_COMMAND,
    )
    _write_json(settings_path, settings)
    return HookInstallResult(
        settings_path=settings_path,
        backup_path=backup_path,
        mcp_path=mcp_config_path(repo_root),
        backup_created=backup_created,
        mcp_registered=False,
        legacy_global_cleaned=False,
        corrupt_backup_path=corrupt_backup_path,
    )


def uninstall_wrap_hooks(
    *,
    repo_root: Path,
    settings_path: Path | None = None,
) -> bool:
    """Remove exactly the ``onmc wrap`` hooks — the perfect inverse of install.

    Strips only ``onmc hooks task-intercept`` and ``onmc hooks prompt-router``
    from ``settings.json``, leaving every other hook (including the base onmc
    hooks installed by ``onmc hooks install``) untouched. Returns whether
    anything was removed.
    """
    settings_path = settings_path or project_settings_path(repo_root)
    if not settings_path.exists():
        return False
    settings = _load_json(settings_path)
    if not _strip_commands(settings, _WRAP_COMMANDS):
        return False
    _write_json(settings_path, settings)
    return True


def wrap_hooks_installed(*, settings_path: Path) -> bool:
    """Return whether both ``onmc wrap`` hooks are present in settings.json."""
    settings = _load_json(settings_path)
    hooks = settings.get("hooks", {})
    return _has_command_hook(
        hooks,
        event_name="PreToolUse",
        matcher=_TASK_INTERCEPT_MATCHER,
        command=TASK_INTERCEPT_COMMAND,
    ) and _has_command_hook(
        hooks,
        event_name="UserPromptSubmit",
        matcher="",
        command=PROMPT_ROUTER_COMMAND,
    ) and _has_command_hook(
        hooks,
        event_name="PreToolUse",
        matcher=_DECISION_INTERCEPT_MATCHER,
        command=DECISION_INTERCEPT_COMMAND,
    ) and _has_command_hook(
        hooks,
        event_name="Stop",
        matcher="",
        command=RUNTIME_STOP_COMMAND,
    )


def hooks_installed(*, settings_path: Path) -> bool:
    """Return whether the project-scoped onmc hooks are present in settings.json."""
    settings = _load_json(settings_path)
    hooks = settings.get("hooks", {})
    return (
        _has_command_hook(
            hooks,
            event_name="PreCompact",
            matcher="",
            command=PRE_COMPACT_COMMAND,
        )
        and _has_command_hook(
            hooks,
            event_name="SessionStart",
            matcher="",
            command=SESSION_START_COMMAND,
        )
        and _has_command_hook(
            hooks,
            event_name="UserPromptSubmit",
            matcher="",
            command=PROMPT_RECALL_COMMAND,
        )
        and _has_command_hook(
            hooks,
            event_name="SessionEnd",
            matcher="",
            command=SESSION_END_COMMAND,
        )
        and _has_command_hook(
            hooks,
            event_name="PreToolUse",
            matcher=_PRE_TOOL_USE_MATCHER,
            command=PRE_TOOL_USE_COMMAND,
        )
        and _has_command_hook(
            hooks,
            event_name="PostToolUse",
            matcher="",
            command=POST_TOOL_USE_COMMAND,
        )
        and _has_command_hook(
            hooks,
            event_name="SubagentStop",
            matcher="",
            command=SUBAGENT_STOP_COMMAND,
        )
    )


def mcp_registered(*, mcp_path: Path) -> bool:
    """Return whether the onmc MCP server is registered in .mcp.json."""
    payload = _load_json(mcp_path)
    servers = payload.get("mcpServers")
    return isinstance(servers, dict) and MCP_SERVER_NAME in servers


def legacy_global_hooks_present(*, settings_path: Path) -> bool:
    """Return whether legacy onmc entries remain in a user-level settings.json."""
    settings = _load_json(settings_path)
    hooks = settings.get("hooks")
    if isinstance(hooks, dict):
        for event_name in _HOOK_EVENTS:
            entries = hooks.get(event_name)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict) and _onmc_hook_items(entry.get("hooks", [])):
                    return True
    servers = settings.get("mcpServers")
    return isinstance(servers, dict) and MCP_SERVER_NAME in servers


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return dict(payload)
    return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _register_mcp_server(mcp_path: Path) -> None:
    payload = _load_json(mcp_path)
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        payload["mcpServers"] = servers
    servers.setdefault(
        MCP_SERVER_NAME,
        {
            "command": "onmc",
            "args": ["serve", "--mcp"],
        },
    )
    _write_json(mcp_path, payload)


def _unregister_mcp_server(mcp_path: Path) -> None:
    if not mcp_path.exists():
        return
    payload = _load_json(mcp_path)
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict) or MCP_SERVER_NAME not in servers:
        return
    servers.pop(MCP_SERVER_NAME)
    if not servers:
        payload.pop("mcpServers", None)
    if payload:
        _write_json(mcp_path, payload)
    else:
        mcp_path.unlink()


def _clean_legacy_global_settings(settings_path: Path) -> bool:
    """Remove legacy onmc entries from a user-level settings.json if present."""
    if not settings_path.exists():
        return False
    settings = _load_json(settings_path)
    if not _strip_onmc_entries(settings):
        return False
    _write_json(settings_path, settings)
    return True


def _strip_onmc_entries(settings: dict[str, Any]) -> bool:
    """Remove every onmc hook command and the onmc MCP key from a settings dict."""
    changed = _strip_commands(settings, _ONMC_COMMANDS, strip_mcp=True)
    return changed


def _strip_commands(
    settings: dict[str, Any],
    commands: frozenset[str],
    *,
    strip_mcp: bool = False,
) -> bool:
    """Remove every hook whose command is in *commands* from a settings dict.

    When *strip_mcp* is set, also remove the onmc MCP server key. Empty event
    lists and an empty ``hooks`` map are pruned so removal is a clean inverse of
    insertion. Returns whether anything changed.
    """
    changed = False
    hooks = settings.get("hooks")
    if isinstance(hooks, dict):
        for event_name in _HOOK_EVENTS:
            changed = _remove_commands(hooks, event_name, commands) or changed
        if changed and not hooks:
            settings.pop("hooks", None)
    if strip_mcp:
        servers = settings.get("mcpServers")
        if isinstance(servers, dict) and MCP_SERVER_NAME in servers:
            servers.pop(MCP_SERVER_NAME)
            changed = True
            if not servers:
                settings.pop("mcpServers", None)
    return changed


def _remove_commands(hooks: dict[str, Any], event_name: str, commands: frozenset[str]) -> bool:
    entries = hooks.get(event_name)
    if not isinstance(entries, list):
        return False
    changed = False
    remaining_entries: list[Any] = []
    for entry in entries:
        if not isinstance(entry, dict):
            remaining_entries.append(entry)
            continue
        hook_items = entry.get("hooks", [])
        if not isinstance(hook_items, list):
            remaining_entries.append(entry)
            continue
        target_items = _matching_hook_items(hook_items, commands)
        if not target_items:
            remaining_entries.append(entry)
            continue
        changed = True
        filtered = [item for item in hook_items if item not in target_items]
        if filtered:
            entry["hooks"] = filtered
            remaining_entries.append(entry)
    if remaining_entries:
        hooks[event_name] = remaining_entries
    else:
        if event_name in hooks:
            changed = True
        hooks.pop(event_name, None)
    return changed


def _onmc_hook_items(hook_items: object) -> list[Any]:
    return _matching_hook_items(hook_items, _ONMC_COMMANDS)


def _matching_hook_items(hook_items: object, commands: frozenset[str]) -> list[Any]:
    if not isinstance(hook_items, list):
        return []
    return [
        item
        for item in hook_items
        if isinstance(item, dict)
        and item.get("type") == "command"
        and item.get("command") in commands
    ]


def _merge_command_hook(
    hooks: dict[str, Any],
    *,
    event_name: str,
    matcher: str,
    command: str,
) -> None:
    entries = hooks.get(event_name)
    if not isinstance(entries, list):
        entries = []
        hooks[event_name] = entries
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("matcher", "") != matcher:
            continue
        hook_items = entry.get("hooks")
        if not isinstance(hook_items, list):
            hook_items = []
            entry["hooks"] = hook_items
        if any(
            isinstance(item, dict)
            and item.get("type") == "command"
            and item.get("command") == command
            for item in hook_items
        ):
            return
        hook_items.append({"type": "command", "command": command})
        return
    entries.append(
        {
            "matcher": matcher,
            "hooks": [{"type": "command", "command": command}],
        }
    )


def _has_command_hook(hooks: object, *, event_name: str, matcher: str, command: str) -> bool:
    if not isinstance(hooks, dict):
        return False
    entries = hooks.get(event_name)
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("matcher", "") != matcher:
            continue
        hook_items = entry.get("hooks", [])
        if not isinstance(hook_items, list):
            continue
        if any(
            isinstance(item, dict)
            and item.get("type") == "command"
            and item.get("command") == command
            for item in hook_items
        ):
            return True
    return False
