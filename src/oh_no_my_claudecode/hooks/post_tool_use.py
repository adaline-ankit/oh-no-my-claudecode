"""PostToolUse / SubagentStop / Stop hook handlers for live telemetry.

These handlers read the Claude Code hook JSON payload from stdin and emit
events to ``.onmc/live/events.jsonl`` via the telemetry bus.

Design contract (identical to all onmc hooks)
---------------------------------------------
- Always exit 0 — never block Claude Code under any circumstance.
- Any exception is swallowed silently; stdout stays clean on error.
- No-op gracefully when ``.onmc/`` is absent (hooks install not run).
- Fast: no network, no heavy imports on the hot path.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def _read_payload() -> dict[str, object]:
    """Read the Claude Code hook JSON payload from stdin."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _live_dir_for(payload: dict[str, object]) -> Path:
    """Resolve ``.onmc/live/`` relative to the cwd reported in the hook payload."""
    raw_cwd = payload.get("cwd")
    base = Path(raw_cwd) if isinstance(raw_cwd, str) and raw_cwd else Path.cwd()
    return base / ".onmc" / "live"


def handle_post_tool_use(payload: dict[str, object] | None = None) -> None:
    """Emit a ``tool_call`` event from a PostToolUse hook payload.

    Called by ``onmc hooks post-tool-use``; also importable for testing
    (pass a synthetic *payload* dict to bypass stdin).

    Silently no-ops when:
    - ``.onmc/`` directory is absent (hooks not installed).
    - The payload carries no recognisable tool name.
    - Any unexpected error occurs (exception is swallowed).
    """
    try:
        p: dict[str, object] = payload if payload is not None else _read_payload()
        live_dir = _live_dir_for(p)
        # No-op if .onmc/ is absent — user hasn't run `onmc hooks install`.
        if not live_dir.parent.exists():
            return

        from oh_no_my_claudecode.telemetry.bus import Event, emit

        tool_name = p.get("tool_name")
        if not isinstance(tool_name, str):
            tool_name = None

        tool_input = p.get("tool_input")
        detail: str | None = None
        if isinstance(tool_input, dict):
            # Pick the most meaningful field as a brief target string.
            for key in ("command", "file_path", "path", "url", "query"):
                val = tool_input.get(key)
                if isinstance(val, str) and val:
                    detail = f"{key}={val[:120]}"
                    break

        session_id = p.get("session_id")
        if not isinstance(session_id, str):
            session_id = None

        emit(
            Event(
                ts=time.time(),
                kind="tool_call",
                tool=tool_name,
                detail=detail,
                session_id=session_id,
            ),
            live_dir=live_dir,
        )
    except Exception:  # noqa: BLE001, S110 - hook commands must never block the session.
        pass


def handle_subagent_stop(payload: dict[str, object] | None = None) -> None:
    """Emit a ``subagent_stop`` event from a SubagentStop or Stop hook payload.

    Called by ``onmc hooks subagent-stop``; also importable for testing.
    The same handler covers both ``SubagentStop`` and ``Stop`` events since
    their payloads have the same shape.
    """
    try:
        p: dict[str, object] = payload if payload is not None else _read_payload()
        live_dir = _live_dir_for(p)
        if not live_dir.parent.exists():
            return

        from oh_no_my_claudecode.telemetry.bus import Event, emit

        session_id = p.get("session_id")
        if not isinstance(session_id, str):
            session_id = None

        stop_reason = p.get("stop_reason")
        detail = str(stop_reason) if stop_reason is not None else None

        emit(
            Event(
                ts=time.time(),
                kind="subagent_stop",
                detail=detail,
                session_id=session_id,
            ),
            live_dir=live_dir,
        )
    except Exception:  # noqa: BLE001, S110 - hook commands must never block the session.
        pass
