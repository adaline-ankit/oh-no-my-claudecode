"""Pure AutoGen interop: onmc plan → team spec + injectable-runner receipt wrap.

Two layers
----------
- ``plan_to_team_spec(plan)`` — PURE, no autogen dependency, always importable.
  Converts the JSON-serialisable dict from ``MissionPlan.to_dict()`` (or any
  swarm plan JSON) into a portable AutoGen GroupChat specification dict.

- ``run_team(spec, *, runner)`` — wraps a team execution so onmc records a
  tamper-evident receipt.  The *runner* is INJECTABLE: pass a fake callable
  in tests (zero network, zero autogen); pass ``autogen_runner`` in production.

- ``autogen_runner(spec)`` — the real AutoGen execution path.  Imported lazily;
  never call this when ``autogen_available()`` is False.

- ``autogen_available()`` — availability probe, always safe to call.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Optional autogen detection
# ---------------------------------------------------------------------------

_AUTOGEN_AVAILABLE: bool | None = None  # cached after first probe


def autogen_available() -> bool:
    """Return True iff pyautogen or ag2 is importable.

    The result is cached after the first call; restart the interpreter to
    invalidate it (relevant only in tests that mock the import system).
    """
    global _AUTOGEN_AVAILABLE  # noqa: PLW0603 — intentional module-level cache
    if _AUTOGEN_AVAILABLE is not None:
        return _AUTOGEN_AVAILABLE
    try:
        import autogen  # noqa: F401

        _AUTOGEN_AVAILABLE = True
        return True
    except ImportError:
        pass
    try:
        import ag2  # noqa: F401

        _AUTOGEN_AVAILABLE = True
        return True
    except ImportError:
        pass
    _AUTOGEN_AVAILABLE = False
    return False


# ---------------------------------------------------------------------------
# Export: plan dict → AutoGen team spec  (PURE)
# ---------------------------------------------------------------------------

_SPEC_KIND = "onmc-autogen-team-v1"


def plan_to_team_spec(plan: dict[str, Any]) -> dict[str, Any]:
    """Convert an onmc mission/swarm plan dict to a portable AutoGen team spec.

    The returned dict is JSON-serialisable and contains enough information to
    bootstrap a pyautogen / ag2 ``GroupChat``.

    Parameters
    ----------
    plan:
        JSON-safe dict from ``MissionPlan.to_dict()`` or a swarm plan JSON.
        Required key: ``"goal"`` (str).  Optional: ``"swarm_units"`` (list of
        str), ``"dead_ends"`` (list of str), ``"blast_radius"`` (list of str).

    Returns
    -------
    dict
        ``{"kind": "onmc-autogen-team-v1", "goal": ..., "agents": [...],
        "manager": {...}, "orchestration": "group_chat", "metadata": {...}}``
    """
    goal: str = str(plan.get("goal", "")).strip()
    swarm_units: list[str] = [str(u) for u in plan.get("swarm_units", [])]
    dead_ends: list[str] = [str(d) for d in plan.get("dead_ends", [])]
    blast_radius: list[str] = [str(f) for f in plan.get("blast_radius", [])]

    # One assistant agent per swarm unit; single fallback when units absent.
    agents: list[dict[str, Any]] = []
    if swarm_units:
        for idx, unit_goal in enumerate(swarm_units):
            agents.append(
                {
                    "name": f"worker_{idx}",
                    "role": "assistant",
                    "goal": unit_goal,
                    "system_message": (
                        f"You are worker_{idx}.  Complete the following task:\n"
                        f"{unit_goal}"
                    ),
                }
            )
    else:
        agents.append(
            {
                "name": "worker_0",
                "role": "assistant",
                "goal": goal,
                "system_message": (
                    f"You are a coding assistant.  Complete:\n{goal}"
                ),
            }
        )

    manager: dict[str, Any] = {
        "name": "onmc_manager",
        "role": "orchestrator",
        "system_message": (
            "You are an onmc team manager.  Coordinate the workers to "
            f"accomplish the mission goal:\n{goal}"
        ),
    }

    return {
        "kind": _SPEC_KIND,
        "goal": goal,
        "agents": agents,
        "manager": manager,
        "orchestration": "group_chat",
        "metadata": {
            "generated_by": "onmc",
            "dead_ends": dead_ends,
            "blast_radius": blast_radius,
        },
    }


# ---------------------------------------------------------------------------
# Run: injectable runner + receipt
# ---------------------------------------------------------------------------

#: Callable that accepts a team spec dict and returns a result dict.
TeamRunner = Callable[[dict[str, Any]], dict[str, Any]]


def _write_team_receipt(
    spec: dict[str, Any],
    result: dict[str, Any],
    *,
    repo_root: Path,
    started_at: str,
    ended_at: str,
) -> Path:
    """Write a team-run receipt to ``.agent-memory/receipts/`` and return path."""
    content: dict[str, Any] = {
        "schema_version": "team-1",
        "kind": "team-run-receipt",
        "spec_goal": spec.get("goal", ""),
        "agent_count": len(spec.get("agents", [])),
        "orchestration": spec.get("orchestration", "group_chat"),
        "started_at": started_at,
        "ended_at": ended_at,
        "result": result,
    }
    receipt_hash = hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    content["receipt_hash"] = receipt_hash

    receipts_dir = repo_root / ".agent-memory" / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)

    goal_short = hashlib.sha256(
        spec.get("goal", "").encode()
    ).hexdigest()[:8]
    hash_short = receipt_hash[:8]
    dest = receipts_dir / f"team-{goal_short}-{hash_short}.json"
    dest.write_text(
        json.dumps(content, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return dest


def run_team(
    spec: dict[str, Any],
    *,
    runner: TeamRunner,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Execute an AutoGen team spec and record an onmc receipt.

    Parameters
    ----------
    spec:
        Team spec dict as produced by ``plan_to_team_spec``.
    runner:
        Injectable team runner.  Signature:
        ``(spec: dict[str, Any]) -> dict[str, Any]``.
        Use ``autogen_runner`` for real execution or a fake callable in tests.
    repo_root:
        Where to write the receipt (default: ``Path.cwd()``).

    Returns
    -------
    dict
        ``{"status": "ok", "result": {...}, "receipt_path": "<abs-path>"}``
    """
    if repo_root is None:
        repo_root = Path.cwd()

    started_at = datetime.now(UTC).isoformat()
    result = runner(spec)
    ended_at = datetime.now(UTC).isoformat()

    receipt_path = _write_team_receipt(
        spec,
        result,
        repo_root=repo_root,
        started_at=started_at,
        ended_at=ended_at,
    )

    return {
        "status": "ok",
        "result": result,
        "receipt_path": str(receipt_path),
    }


# ---------------------------------------------------------------------------
# Real AutoGen runner (only works when [autogen] extra is installed)
# ---------------------------------------------------------------------------

def autogen_runner(spec: dict[str, Any]) -> dict[str, Any]:
    """Run a team spec with the real pyautogen / ag2 GroupChat backend.

    This function requires the ``[autogen]`` optional extra.  Guard calls with
    ``autogen_available()`` or be prepared to catch ``ImportError``.

    Raises
    ------
    ImportError
        When neither ``autogen`` nor ``ag2`` is installed.
    """
    _ag_mod: Any = None
    for _pkg in ("autogen", "ag2"):
        try:
            _ag_mod = importlib.import_module(_pkg)
            break
        except ImportError:
            continue
    if _ag_mod is None:
        raise ImportError(
            "pyautogen or ag2 is required.  "
            "Install with: pip install 'oh-no-my-claudecode[autogen]'"
        )

    agent_cfgs: list[dict[str, Any]] = spec.get("agents", [])
    agents = [
        _ag_mod.AssistantAgent(
            name=cfg["name"],
            system_message=cfg.get("system_message", ""),
        )
        for cfg in agent_cfgs
    ]

    manager_cfg: dict[str, Any] = spec.get("manager", {})
    group_chat = _ag_mod.GroupChat(agents=agents, messages=[], max_round=5)
    manager = _ag_mod.GroupChatManager(
        groupchat=group_chat,
        name=manager_cfg.get("name", "onmc_manager"),
    )

    if agents:
        agents[0].initiate_chat(manager, message=spec.get("goal", ""))

    return {
        "chat_history": [str(m) for m in group_chat.messages],
        "agent_count": len(agents),
    }
