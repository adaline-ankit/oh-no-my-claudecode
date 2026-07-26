"""Org hard-lock enforcement via Claude Code managed-settings.

``onmc wrap --managed`` installs the onmc wrap hooks into Claude Code's
OS-level managed-settings.json so users CANNOT override or disable them.

Per-OS default managed paths:
  macOS:   /Library/Application Support/ClaudeCode/managed-settings.json
  Linux:   /etc/claude-code/managed-settings.json
  Windows: C:\\ProgramData\\ClaudeCode\\managed-settings.json

Writing the system path requires admin/root. When the path is not writable
onmc prints the exact JSON to install manually instead of crashing.

All merge/strip functions are **pure** (no file I/O). File I/O happens only
in the caller (commands.py) so tests can exercise the logic with temp files
and never touch real system paths.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.hooks.installer import (
    DECISION_INTERCEPT_COMMAND,
    PROMPT_ROUTER_COMMAND,
    RUNTIME_STOP_COMMAND,
    TASK_INTERCEPT_COMMAND,
)

__all__ = [
    "default_managed_path",
    "managed_hooks_present",
    "manual_install_json",
    "merge_managed_hooks",
    "strip_managed_hooks",
]

# Matcher used by the Task intercept hook.
_TASK_MATCHER = "Task"
_QUESTION_MATCHER = "AskUserQuestion"
_WRAP_COMMANDS = frozenset(
    {
        TASK_INTERCEPT_COMMAND,
        PROMPT_ROUTER_COMMAND,
        DECISION_INTERCEPT_COMMAND,
        RUNTIME_STOP_COMMAND,
    }
)


def default_managed_path() -> Path:
    """Return the OS-appropriate Claude Code managed-settings.json path.

    macOS:   /Library/Application Support/ClaudeCode/managed-settings.json
    Linux:   /etc/claude-code/managed-settings.json
    Windows: C:\\ProgramData\\ClaudeCode\\managed-settings.json
    """
    if sys.platform == "darwin":
        return Path("/Library/Application Support/ClaudeCode/managed-settings.json")
    if sys.platform == "win32":
        return Path(r"C:\ProgramData\ClaudeCode\managed-settings.json")
    # Linux and other POSIX.
    return Path("/etc/claude-code/managed-settings.json")


def merge_managed_hooks(existing: dict[str, Any]) -> dict[str, Any]:
    """Return *existing* with the onmc wrap hooks merged in.

    Idempotent — calling twice produces the same result as once.
    Preserves every key that onmc does not own.
    Does NOT perform any file I/O; the caller is responsible for
    reading and writing the managed-settings file.
    """
    settings: dict[str, Any] = copy.deepcopy(existing)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks
    _merge_hook(
        hooks, event_name="PreToolUse", matcher=_TASK_MATCHER, command=TASK_INTERCEPT_COMMAND
    )
    _merge_hook(
        hooks,
        event_name="PreToolUse",
        matcher=_QUESTION_MATCHER,
        command=DECISION_INTERCEPT_COMMAND,
    )
    _merge_hook(hooks, event_name="UserPromptSubmit", matcher="", command=PROMPT_ROUTER_COMMAND)
    _merge_hook(hooks, event_name="Stop", matcher="", command=RUNTIME_STOP_COMMAND)
    return settings


def strip_managed_hooks(existing: dict[str, Any]) -> dict[str, Any]:
    """Return *existing* with only the onmc wrap hooks removed.

    Preserves every other managed key untouched.  Empty hook lists are
    pruned so removal is a clean inverse of insertion.
    Does NOT perform any file I/O.
    """
    settings: dict[str, Any] = copy.deepcopy(existing)
    _strip_commands(settings, _WRAP_COMMANDS)
    return settings


def managed_hooks_present(settings: dict[str, Any]) -> bool:
    """Return whether both onmc wrap hooks are present in *settings*."""
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return False
    return _has_hook(
        hooks, event_name="PreToolUse", matcher=_TASK_MATCHER, command=TASK_INTERCEPT_COMMAND
    ) and _has_hook(
        hooks,
        event_name="PreToolUse",
        matcher=_QUESTION_MATCHER,
        command=DECISION_INTERCEPT_COMMAND,
    ) and _has_hook(
        hooks, event_name="UserPromptSubmit", matcher="", command=PROMPT_ROUTER_COMMAND
    ) and _has_hook(hooks, event_name="Stop", matcher="", command=RUNTIME_STOP_COMMAND)


def manual_install_json() -> str:
    """Return the minimal JSON fragment a human can paste into managed-settings.

    This is the exact content that ``merge_managed_hooks({})`` would produce —
    pretty-printed for copy-paste into a managed-settings.json file.
    """
    payload = merge_managed_hooks({})
    return json.dumps(payload, indent=2, sort_keys=True)


def load_managed_settings(path: Path) -> dict[str, Any]:
    """Load the managed-settings JSON from *path*, returning ``{}`` on any error."""
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict):
        return dict(data)
    return {}


def write_managed_settings(path: Path, settings: dict[str, Any]) -> None:
    """Write *settings* to *path* as pretty JSON.

    Raises :exc:`PermissionError` if the path is not writable (caller must
    handle and print the manual-install message instead of crashing).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Private helpers — pure dict operations, no I/O
# ---------------------------------------------------------------------------

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


def _merge_hook(
    hooks: dict[str, Any],
    *,
    event_name: str,
    matcher: str,
    command: str,
) -> None:
    """Idempotently add *command* under *event_name*/*matcher* in *hooks* (mutates)."""
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
            return  # already present
        hook_items.append({"type": "command", "command": command})
        return
    entries.append({"matcher": matcher, "hooks": [{"type": "command", "command": command}]})


def _strip_commands(settings: dict[str, Any], commands: frozenset[str]) -> None:
    """Remove every hook whose command is in *commands* from *settings* (mutates)."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event_name in _HOOK_EVENTS:
        entries = hooks.get(event_name)
        if not isinstance(entries, list):
            continue
        new_entries: list[Any] = []
        for entry in entries:
            if not isinstance(entry, dict):
                new_entries.append(entry)
                continue
            hook_items = entry.get("hooks", [])
            if not isinstance(hook_items, list):
                new_entries.append(entry)
                continue
            filtered = [
                item
                for item in hook_items
                if not (
                    isinstance(item, dict)
                    and item.get("type") == "command"
                    and item.get("command") in commands
                )
            ]
            if filtered:
                entry = dict(entry)
                entry["hooks"] = filtered
                new_entries.append(entry)
            # else: entry is empty after stripping — drop it
        if new_entries:
            hooks[event_name] = new_entries
        else:
            hooks.pop(event_name, None)
    if not hooks:
        settings.pop("hooks", None)


def _has_hook(
    hooks: dict[str, Any],
    *,
    event_name: str,
    matcher: str,
    command: str,
) -> bool:
    """Return whether *command* exists under *event_name*/*matcher* in *hooks*."""
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
