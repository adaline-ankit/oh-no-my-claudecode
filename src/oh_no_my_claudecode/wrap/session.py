"""Session-active state for the ``onmc wrap`` deep-wrap switch.

Controls whether the deep-wrap lifecycle hooks engage for the current session.
Unlike the wrap installation (which writes hook commands into settings.json),
the session switch is a lightweight file toggle that hooks read at hot-path
speed:

    .onmc/wrap/active   — "1" → session active; "0" → inactive; absent → use default

When the wrap layer is not installed (``.onmc/wrap.json`` absent), hooks behave
unconditionally — existing ``onmc hooks install`` users see no change.

When the wrap layer IS installed, the session switch is consulted:

- Marker present: the value (``"1"``/``"0"``) determines active/inactive.
- Marker absent: ``default_active`` from ``.onmc/wrap.json`` is used
  (``False`` unless the user explicitly enabled it with
  ``onmc wrap --default-active``).

The ``/onmc`` Claude Code slash command calls ``onmc wrap toggle``, which writes
this marker, giving a one-keystroke way to flip the control plane on or off
without leaving the editor.
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = [
    "is_active",
    "read_default_active",
    "session_active_path",
    "set_active",
]

_ACTIVE_SUBDIR = Path(".onmc") / "wrap"
_ACTIVE_FILENAME = "active"


def session_active_path(repo_root: Path) -> Path:
    """Return the session-active marker file path for *repo_root*."""
    return repo_root / _ACTIVE_SUBDIR / _ACTIVE_FILENAME


def is_active(repo_root: Path) -> bool:
    """Return whether the deep-wrap control plane is active for *repo_root*.

    Returns ``True`` unconditionally when the wrap layer is not installed
    (``.onmc/wrap.json`` absent) so that base ``onmc hooks install`` behaviour
    is preserved for users who have not yet installed the wrap layer.

    When wrap IS installed:

    - If ``.onmc/wrap/active`` exists, its content (``"1"``/``"0"``) wins.
    - Otherwise, falls back to ``default_active`` in ``.onmc/wrap.json``
      (default ``False``).

    Never raises — any unexpected error returns ``True`` (fail open) so that
    a gate failure never silently breaks Claude Code hooks.
    """
    try:
        wrap_json = repo_root / ".onmc" / "wrap.json"
        if not wrap_json.exists():
            # Wrap layer not installed; hooks are unconditional (old behaviour).
            return True

        marker = session_active_path(repo_root)
        if marker.is_file():
            raw = marker.read_text(encoding="utf-8").strip()
            return raw != "0"

        return _read_default_active(repo_root)
    except Exception:  # noqa: BLE001
        return True  # fail open — a gate failure must never block Claude Code


def set_active(repo_root: Path, *, on: bool) -> None:
    """Write the session-active marker for *repo_root*.

    Creates ``.onmc/wrap/active`` with ``"1"`` (on) or ``"0"`` (off).
    Parent directories are created as needed.  Never raises.
    """
    try:
        marker = session_active_path(repo_root)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1" if on else "0", encoding="utf-8")
    except Exception:  # noqa: BLE001, S110 - marker write failure must never raise.
        pass


def read_default_active(repo_root: Path) -> bool:
    """Return the ``default_active`` setting from ``.onmc/wrap.json``.

    ``True`` only when the field is explicitly set to ``True`` in the state
    file.  Defaults to ``False`` when the state file is absent or the field
    is missing/non-boolean.  Never raises.
    """
    return _read_default_active(repo_root)


def _read_default_active(repo_root: Path) -> bool:
    """Return the ``default_active`` flag from ``.onmc/wrap.json``."""
    path = repo_root / ".onmc" / "wrap.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if isinstance(data, dict):
        val = data.get("default_active")
        if isinstance(val, bool):
            return val
    return False
