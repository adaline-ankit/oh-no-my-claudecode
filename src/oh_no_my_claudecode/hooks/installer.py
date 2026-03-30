from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def claude_settings_path(home: Path | None = None) -> Path:
    """Return the Claude Code settings.json path."""
    base = (home or Path.home()) / ".claude"
    return base / "settings.json"


def claude_settings_backup_path(home: Path | None = None) -> Path:
    """Return the ONMC backup path for Claude Code settings."""
    return Path(f"{claude_settings_path(home).as_posix()}.onmc-backup")


def install_claude_hooks(
    *,
    settings_path: Path,
    backup_path: Path,
    add_mcp_server: bool = False,
) -> None:
    """Merge ONMC Claude hooks into settings.json without clobbering other settings."""
    settings = _load_settings(settings_path)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(
        json.dumps(settings, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    hooks = settings.setdefault("hooks", {})
    _merge_command_hook(hooks, event_name="PreCompact", command="onmc hooks pre-compact")
    _merge_command_hook(hooks, event_name="PostCompact", command="onmc hooks post-compact")
    if add_mcp_server:
        mcp_servers = settings.setdefault("mcpServers", {})
        mcp_servers.setdefault(
            "onmc",
            {
                "command": "onmc",
                "args": ["serve", "--mcp"],
            },
        )
    _write_settings(settings_path, settings)


def uninstall_claude_hooks(*, settings_path: Path, backup_path: Path) -> None:
    """Remove ONMC Claude hooks and restore from backup when available."""
    if backup_path.exists():
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
        return

    settings = _load_settings(settings_path)
    hooks = settings.get("hooks", {})
    _remove_command_hook(hooks, event_name="PreCompact", command="onmc hooks pre-compact")
    _remove_command_hook(hooks, event_name="PostCompact", command="onmc hooks post-compact")
    mcp_servers = settings.get("mcpServers", {})
    if isinstance(mcp_servers, dict):
        mcp_servers.pop("onmc", None)
        if not mcp_servers:
            settings.pop("mcpServers", None)
    _write_settings(settings_path, settings)


def hooks_installed(*, settings_path: Path) -> bool:
    """Return whether the ONMC Claude hooks are present in settings.json."""
    settings = _load_settings(settings_path)
    hooks = settings.get("hooks", {})
    return _has_command_hook(hooks, "PreCompact", "onmc hooks pre-compact") and _has_command_hook(
        hooks,
        "PostCompact",
        "onmc hooks post-compact",
    )


def _load_settings(settings_path: Path) -> dict[str, Any]:
    if not settings_path.exists():
        return {}
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return dict(payload)
    return {}


def _write_settings(settings_path: Path, settings: dict[str, Any]) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _merge_command_hook(hooks: object, *, event_name: str, command: str) -> None:
    if not isinstance(hooks, dict):
        return
    event_entries = hooks.setdefault(event_name, [])
    if not isinstance(event_entries, list):
        hooks[event_name] = event_entries = []
    for entry in event_entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("matcher", "") == "":
            hook_items = entry.setdefault("hooks", [])
            if not isinstance(hook_items, list):
                entry["hooks"] = hook_items = []
            if any(
                isinstance(item, dict)
                and item.get("type") == "command"
                and item.get("command") == command
                for item in hook_items
            ):
                return
            hook_items.append({"type": "command", "command": command})
            return
    event_entries.append(
        {
            "matcher": "",
            "hooks": [{"type": "command", "command": command}],
        }
    )


def _remove_command_hook(hooks: object, *, event_name: str, command: str) -> None:
    if not isinstance(hooks, dict):
        return
    event_entries = hooks.get(event_name)
    if not isinstance(event_entries, list):
        return
    remaining_entries = []
    for entry in event_entries:
        if not isinstance(entry, dict):
            remaining_entries.append(entry)
            continue
        hook_items = entry.get("hooks", [])
        if not isinstance(hook_items, list):
            remaining_entries.append(entry)
            continue
        filtered = [
            item
            for item in hook_items
            if not (
                isinstance(item, dict)
                and item.get("type") == "command"
                and item.get("command") == command
            )
        ]
        if filtered:
            entry["hooks"] = filtered
            remaining_entries.append(entry)
    if remaining_entries:
        hooks[event_name] = remaining_entries
    else:
        hooks.pop(event_name, None)
    if not hooks:
        return


def _has_command_hook(hooks: object, event_name: str, command: str) -> bool:
    if not isinstance(hooks, dict):
        return False
    entries = hooks.get(event_name)
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict):
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
