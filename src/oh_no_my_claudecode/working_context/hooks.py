"""Advisory working-context delivery at supported Claude Code hook boundaries."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from oh_no_my_claudecode.core.service import OnmcService

if TYPE_CHECKING:
    from oh_no_my_claudecode.working_context.engine import WorkingContext

_UNAVAILABLE = (
    "Working context unavailable; previously recalled memory may be stale. "
    "Re-read sources; inspect `onmc working status`."
)


def load_working_context(cwd: Path) -> tuple[Path, WorkingContext]:
    """Use the repository's existing configuration and SQLite store."""
    from oh_no_my_claudecode.working_context.engine import WorkingContext

    root, _, storage = OnmcService(cwd)._load_context()  # noqa: SLF001
    return root, WorkingContext(root, storage)


def _tool_files(payload: dict[str, object], cwd: Path) -> list[str]:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    files = []
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            files.append(str(cwd / value))
    return files


def working_hook_output(event: str, payload: dict[str, object]) -> tuple[bool, str]:
    """Return a bounded packet, or nothing; never block a Claude session.

    Only real main-session ids are used. Child-agent hooks cannot consume the
    parent's delivery state. Tool inputs identify paths, not trusted instructions;
    the engine validates their repository boundaries and refreshes source hashes.
    """
    enabled = False
    engine = None
    session_id = payload.get("session_id")
    try:
        if not isinstance(session_id, str) or not session_id.strip():
            return False, ""
        if payload.get("agent_id"):
            return False, ""
        raw_cwd = payload.get("cwd")
        cwd = Path(raw_cwd) if isinstance(raw_cwd, str) and raw_cwd else Path.cwd()
        _, engine = load_working_context(cwd)
        # A malformed or unreadable config must not re-enable legacy recall.
        # A missing config safely defaults to disabled in engine.config().
        enabled = True
        if not engine.config().enabled:
            return False, ""
        session = engine.session(session_id)
        if event == "UserPromptSubmit":
            prompt = payload.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                return True, ""
            if session is None:
                engine.start(session_id, prompt)
            return True, engine.context(session_id, focus=prompt).injection
        if session is None:
            return True, ""
        if event == "SessionStart":
            return True, engine.context(session_id, force=True).injection
        if event in {"PreToolUse", "PostToolUse"}:
            return True, engine.context(
                session_id, files=_tool_files(payload, cwd) or None
            ).injection
        return True, ""
    except Exception:  # noqa: BLE001 - advisory hooks must never block the session.
        # Once enabled, an error must not fall back to legacy stale recall.
        if enabled and engine is not None and isinstance(session_id, str):
            # Preserve corrupt state and still emit the unavailable advisory.
            with suppress(Exception):
                engine.invalidate_delivery(session_id)
        return enabled, _UNAVAILABLE if enabled else ""


def working_hook_context(event: str, payload: dict[str, object]) -> str:
    """Convenience interface for callers that only need the advisory text."""
    return working_hook_output(event, payload)[1]
