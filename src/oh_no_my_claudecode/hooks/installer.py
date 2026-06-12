from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRE_COMPACT_COMMAND = "onmc hooks pre-compact"
SESSION_START_COMMAND = "onmc hooks session-start"
LEGACY_POST_COMPACT_COMMAND = "onmc hooks post-compact"
MCP_SERVER_NAME = "onmc"

_ONMC_COMMANDS = frozenset(
    {PRE_COMPACT_COMMAND, SESSION_START_COMMAND, LEGACY_POST_COMPACT_COMMAND}
)
# "PostCompact" is not a real Claude Code event; earlier onmc versions registered it.
_HOOK_EVENTS = ("PreCompact", "PostCompact", "SessionStart")


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
    - ``SessionStart`` (matcher ``"compact"``) runs ``onmc hooks session-start``,
      which injects the continuation brief after compaction.

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
        matcher="compact",
        command=SESSION_START_COMMAND,
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


def hooks_installed(*, settings_path: Path) -> bool:
    """Return whether the project-scoped onmc hooks are present in settings.json."""
    settings = _load_json(settings_path)
    hooks = settings.get("hooks", {})
    return _has_command_hook(
        hooks,
        event_name="PreCompact",
        matcher="",
        command=PRE_COMPACT_COMMAND,
    ) and _has_command_hook(
        hooks,
        event_name="SessionStart",
        matcher="compact",
        command=SESSION_START_COMMAND,
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
    changed = False
    hooks = settings.get("hooks")
    if isinstance(hooks, dict):
        for event_name in _HOOK_EVENTS:
            changed = _remove_onmc_commands(hooks, event_name) or changed
        if changed and not hooks:
            settings.pop("hooks", None)
    servers = settings.get("mcpServers")
    if isinstance(servers, dict) and MCP_SERVER_NAME in servers:
        servers.pop(MCP_SERVER_NAME)
        changed = True
        if not servers:
            settings.pop("mcpServers", None)
    return changed


def _remove_onmc_commands(hooks: dict[str, Any], event_name: str) -> bool:
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
        onmc_items = _onmc_hook_items(hook_items)
        if not onmc_items:
            remaining_entries.append(entry)
            continue
        changed = True
        filtered = [item for item in hook_items if item not in onmc_items]
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
    if not isinstance(hook_items, list):
        return []
    return [
        item
        for item in hook_items
        if isinstance(item, dict)
        and item.get("type") == "command"
        and item.get("command") in _ONMC_COMMANDS
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
