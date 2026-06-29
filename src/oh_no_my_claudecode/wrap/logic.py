"""Pure, never-raising logic for the ``onmc wrap`` layer.

``onmc wrap`` makes onmc the *default* layer for a Claude Code session by
installing two hooks:

- **Task intercept** (``PreToolUse`` matcher ``"Task"``) — intercepts Claude
  Code's native agent-spawning ``Task`` tool and redirects it to ``onmc
  swarm`` so fan-out is accountable (planned + receipted) instead of opaque.
- **Prompt router** (``UserPromptSubmit``) — routes each user prompt through
  the deterministic :func:`~oh_no_my_claudecode.route.router.route_task` and
  the dead-end :func:`~oh_no_my_claudecode.guard.compiler.compile_guard`,
  injecting a terse "prefer onmc paths" nudge as additional context.

This module holds the *decision* logic only — it performs no I/O beyond the
filesystem probe used by :func:`swarm_active`, takes injectable ``now`` /
``env`` for testability, and is built to a single hard rule:

    **It must NEVER raise.** Any error path returns ``""`` (allow / no-op).

A wrapper that bricks Claude Code is unacceptable, so every branch fails open:
an empty string from either compile function means "do nothing, let Claude
Code proceed exactly as it would have unwrapped."
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from oh_no_my_claudecode.storage import SQLiteStorage

__all__ = [
    "compile_prompt_policy",
    "compile_task_intercept",
    "swarm_active",
]

# The native Claude Code tool that spawns subagents. This is the only tool the
# intercept acts on; every other tool is allowed through untouched.
_TASK_TOOL_NAME = "Task"

# Env var the user (or onmc's own fan-out) can set to bypass the intercept.
_ALLOW_TASK_ENV = "ONMC_ALLOW_TASK"

# A swarm marker older than this is considered stale and no longer exempts
# native Task spawns (the swarm has almost certainly finished or died).
_SWARM_MARKER_TTL_SECONDS = 30 * 60  # 30 minutes


def _truthy(value: str | None) -> bool:
    """Return whether an env-var string represents an explicit truthy value."""
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)


def compile_task_intercept(
    payload: dict[str, Any],
    repo_root: Path,
    *,
    strict: bool,
    now: datetime | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Decide how to handle a ``PreToolUse`` event for the ``Task`` tool.

    Returns a JSON string for Claude Code to parse on stdout, or ``""`` to
    allow the tool call through with no modification.

    Decision order:

    1. **Non-Task tool** → ``""`` (never touch anything but ``Task``).
    2. **Self-exemption** → ``""`` when ``ONMC_ALLOW_TASK`` is truthy in *env*
       OR an onmc swarm is currently active (see :func:`swarm_active`). This is
       what stops onmc's OWN inline-swarm fan-out from being blocked by its own
       wrapper — and lets a user opt out per-invocation.
    3. **strict** → a ``permissionDecision: "deny"`` payload redirecting the
       model to ``onmc swarm plan`` (the Task call is actually blocked).
    4. **soft** → an ``additionalContext`` warning payload (the Task call still
       runs; the model just sees a nudge toward ``onmc swarm``).

    Never raises: any unexpected error returns ``""`` (allow).
    """
    try:
        tool_name = payload.get("tool_name", "")
        if not isinstance(tool_name, str) or tool_name != _TASK_TOOL_NAME:
            return ""

        environ = env if env is not None else dict(os.environ)
        if _truthy(environ.get(_ALLOW_TASK_ENV)):
            return ""
        if swarm_active(repo_root, _now(now)):
            return ""

        if strict:
            reason = (
                "onmc is the active layer (strict). Native Task fan-out is "
                "intercepted so agent spawns stay accountable. Use "
                "`onmc swarm plan` to allocate a receipted swarm, then fan out "
                "subagents under it (each unit gets a tamper-evident receipt). "
                "To bypass for this one call, set ONMC_ALLOW_TASK=1."
            )
            return json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                }
            )

        warning = (
            "onmc is the active layer (soft). Prefer `onmc swarm plan` over a "
            "raw Task spawn so the fan-out is planned and receipted. Proceeding "
            "with the native Task call as requested."
        )
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": warning,
                }
            }
        )
    except Exception:  # noqa: BLE001 - never brick Claude Code; fail open.
        return ""


def compile_prompt_policy(
    prompt: str,
    storage: SQLiteStorage | None,
    *,
    strict: bool,
    now: datetime | None = None,
) -> str:
    """Build the ``UserPromptSubmit`` additional-context nudge for *prompt*.

    Routes the prompt through the deterministic router and (when *storage* is
    available) the dead-end guard, then emits a terse ``additionalContext``
    JSON payload pointing the model at the onmc path best suited to the work.

    Returns ``""`` for an empty prompt or any error (the prompt proceeds with
    no injected context). Never raises.
    """
    try:
        if not prompt or not prompt.strip():
            return ""

        from oh_no_my_claudecode.route.router import route_task

        decision = route_task(prompt)

        # Map the routed strategy to the onmc subcommand the model should reach
        # for. "swarm" → `onmc swarm`, "loop" → `onmc loop`, else → `onmc recall`
        # (single/default still benefits from recalling prior context first).
        command_for_strategy = {
            "swarm": "onmc swarm",
            "loop": "onmc loop",
        }.get(decision.strategy, "onmc recall")

        dead_ends = _top_dead_ends(prompt, storage, now=now)

        mode = "strict" if strict else "soft"
        parts = [
            f"onmc active ({mode}). Suggested: {decision.strategy} → "
            f"`{command_for_strategy}`."
        ]
        if dead_ends:
            parts.append("Dead-ends: " + "; ".join(dead_ends) + ".")
        parts.append("Default to onmc paths; preflight before done.")
        context = " ".join(parts)

        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            }
        )
    except Exception:  # noqa: BLE001 - never brick Claude Code; fail open.
        return ""


def _top_dead_ends(
    prompt: str,
    storage: SQLiteStorage | None,
    *,
    now: datetime | None,
    limit: int = 2,
) -> list[str]:
    """Return up to *limit* short dead-end titles relevant to *prompt*.

    Best-effort: a missing storage handle or any guard error yields ``[]`` so
    the prompt policy degrades to a routing-only nudge instead of failing.
    """
    if storage is None:
        return []
    try:
        from oh_no_my_claudecode.guard.compiler import compile_guard

        result = compile_guard(storage, prompt, limit=limit)
    except Exception:  # noqa: BLE001
        return []
    return [entry.title for entry in result.entries[:limit] if entry.title]


def swarm_active(repo_root: Path, now: datetime) -> bool:
    """Return whether an onmc swarm is currently active for *repo_root*.

    "Active" means: at least one ``.onmc/swarm/<id>/ACTIVE`` marker is *fresh*
    (written less than :data:`_SWARM_MARKER_TTL_SECONDS` ago) AND the swarm's
    manifest still has at least one un-recorded unit (status ``"pending"``).

    This is the self-exemption probe: while onmc's own inline swarm is fanning
    out subagents, the Task intercept must let those spawns through. Once every
    unit is recorded (or the marker goes stale), the exemption lifts.

    Never raises: any filesystem or parse error returns ``False`` (no
    exemption) — the conservative default is to apply the wrap policy.
    """
    try:
        swarm_base = repo_root / ".onmc" / "swarm"
        if not swarm_base.is_dir():
            return False
        cutoff = now.timestamp() - _SWARM_MARKER_TTL_SECONDS
        for swarm_dir in swarm_base.iterdir():
            if not swarm_dir.is_dir():
                continue
            marker = swarm_dir / "ACTIVE"
            if not _marker_fresh(marker, cutoff):
                continue
            if _has_pending_units(swarm_dir / "manifest.json"):
                return True
        return False
    except Exception:  # noqa: BLE001 - probe must never raise.
        return False


def _marker_fresh(marker: Path, cutoff: float) -> bool:
    """Return whether *marker* exists and its recorded timestamp is past cutoff.

    The marker file holds an ISO-8601 timestamp written by
    ``plan_inline_swarm``. If the content can't be parsed, fall back to the
    file's mtime so a present-but-malformed marker still reads as fresh while
    young.
    """
    if not marker.is_file():
        return False
    try:
        raw = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    ts = _parse_iso_timestamp(raw)
    if ts is None:
        try:
            ts = marker.stat().st_mtime
        except OSError:
            return False
    return ts >= cutoff


def _parse_iso_timestamp(raw: str) -> float | None:
    """Parse an ISO-8601 string to a POSIX timestamp, or ``None`` on failure."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _has_pending_units(manifest_path: Path) -> bool:
    """Return whether *manifest_path* lists at least one ``pending`` unit."""
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(manifest, dict):
        return False
    units = manifest.get("units")
    if not isinstance(units, dict):
        return False
    return any(
        isinstance(unit, dict) and unit.get("status") == "pending"
        for unit in units.values()
    )
