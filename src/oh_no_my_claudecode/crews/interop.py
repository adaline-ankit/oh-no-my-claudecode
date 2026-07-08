"""Pure interop layer between onmc plans and CrewAI crew specifications.

Two public surfaces:

``plan_to_crew_spec(plan) -> dict``
    Pure, zero-dependency conversion.  Accepts an onmc mission plan dict
    (``MissionPlan.to_dict()`` shape) or a swarm manifest dict and returns
    a portable crew specification — a plain dict that describes agents and tasks
    in a shape mirroring CrewAI's ``Agent`` / ``Task`` constructor kwargs.
    **No crewai import required.**

``run_crew(spec, *, runner) -> CrewRunReceipt``
    Execute a crew specification.  The ``runner`` parameter is an INJECTABLE
    callable so tests never touch a real LLM: inject a fake runner that returns
    a canned result.  When ``runner`` is ``None`` (the default), the function
    falls through to the real crewai backend — which requires the ``[crewai]``
    extra.  A clear ``RuntimeError`` is raised (not a bare ``ImportError``) when
    crewai is absent and no runner was injected.

Design notes
------------
- ``plan_to_crew_spec`` is deterministic: two calls with the same input produce
  byte-identical output (agents / tasks are always in unit-index order).
- The spec format is intentionally simple — just dicts and strings — so it can
  be serialised to JSON and fed to any downstream tool, not just crewai.
- ``CrewRunReceipt`` is a plain dataclass (no crewai types) so it is importable
  even when crewai is absent.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Availability probe
# ---------------------------------------------------------------------------


def crewai_available() -> bool:
    """Return ``True`` when the optional ``crewai`` package is importable.

    Does NOT construct any agent or task — purely a fast import check.
    Mirror of ``fastembed_available`` in the embeddings module.
    """
    try:
        import crewai  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# Crew specification schema
# ---------------------------------------------------------------------------

_CREW_SPEC_KIND = "crew_spec"
_CREW_SPEC_VERSION = "1"


def _sha256_short(text: str) -> str:
    """Return the first 12 hex chars of the SHA-256 of *text*."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _agent_role(unit_id: str, goal: str) -> str:
    """Derive a stable CrewAI ``role`` string from a unit id and goal."""
    # Keep it human-readable and unique within a crew.
    short = goal[:60].rstrip().replace("\n", " ")
    return f"{unit_id}: {short}"


def _agent_backstory(unit_id: str) -> str:
    """Standard backstory text for an onmc-derived CrewAI agent."""
    return (
        f"onmc executor unit {unit_id}. "
        "Carries out the assigned task inside an accountable onmc loop, "
        "producing tamper-evident receipts for auditability."
    )


def _units_from_plan(plan: dict[str, Any]) -> list[dict[str, str]]:
    """Extract a normalised unit list from an onmc plan or swarm manifest.

    Accepts two shapes:

    MissionPlan dict (``MissionPlan.to_dict()``)::

        {"goal": "...", "swarm_units": ["goal-a", "goal-b", ...], ...}

    Swarm manifest dict (``plan_inline_swarm`` return value)::

        {"swarm_id": "...", "units": [{"id": "...", "goal": "..."}, ...]}

    Falls back to a single synthetic unit from ``plan["goal"]`` when neither
    ``swarm_units`` nor ``units`` is present, so the converter always returns
    at least one agent/task.
    """
    # Inline-swarm manifest: units is a list of {"id": ..., "goal": ...}
    raw_units = plan.get("units")
    if isinstance(raw_units, list) and raw_units:
        out: list[dict[str, str]] = []
        for idx, u in enumerate(raw_units):
            unit_id = str(u.get("id", f"unit-{idx:04d}"))
            goal = str(u.get("goal", ""))
            out.append({"id": unit_id, "goal": goal})
        return out

    # Inline-swarm manifest: units may also be a dict keyed by unit_id
    if isinstance(raw_units, dict) and raw_units:
        out = []
        for unit_id, u in raw_units.items():
            goal = str(u.get("goal", ""))
            out.append({"id": str(unit_id), "goal": goal})
        return out

    # MissionPlan: swarm_units is a list of goal strings
    swarm_units = plan.get("swarm_units")
    if isinstance(swarm_units, list) and swarm_units:
        return [
            {"id": f"unit-{i:04d}", "goal": str(g)}
            for i, g in enumerate(swarm_units)
        ]

    # Fallback: single unit from the top-level goal
    goal = str(plan.get("goal", ""))
    return [{"id": "unit-0000", "goal": goal or "complete the mission"}]


def plan_to_crew_spec(plan: dict[str, Any]) -> dict[str, Any]:
    """Convert an onmc mission plan or swarm manifest to a CrewAI crew spec.

    Pure function — no I/O, no crewai import, fully deterministic.

    Parameters
    ----------
    plan:
        An onmc plan dict.  Accepted shapes:

        - ``MissionPlan.to_dict()`` — has ``goal`` and ``swarm_units`` keys.
        - Swarm manifest from ``plan_inline_swarm`` — has ``swarm_id`` and
          ``units`` keys.
        - Any dict with a ``goal`` string — falls back to one synthetic unit.

    Returns
    -------
    dict
        A portable crew specification with keys::

            {
              "kind": "crew_spec",
              "version": "1",
              "source": "onmc_mission" | "onmc_swarm" | "onmc_plan",
              "goal": "...",
              "spec_hash": "<12-char sha256 fingerprint>",
              "agents": [
                {
                  "role": "<unit_id>: <goal excerpt>",
                  "goal": "<full unit goal>",
                  "backstory": "onmc executor unit <id>. ..."
                },
                ...
              ],
              "tasks": [
                {
                  "description": "<full unit goal>",
                  "expected_output": "A concise summary of the outcome.",
                  "agent_role": "<role of the agent assigned to this task>"
                },
                ...
              ]
            }

        ``agents`` and ``tasks`` are in stable unit-index order.
        ``spec_hash`` is a 12-char SHA-256 fingerprint of ``(goal, unit goals)``.
    """
    overall_goal = str(plan.get("goal", ""))

    # Determine source label for provenance.
    if "swarm_id" in plan or "swarm_units" in plan and plan.get("swarm_units"):
        source = "onmc_swarm" if "swarm_id" in plan else "onmc_mission"
    else:
        source = "onmc_plan"

    units = _units_from_plan(plan)

    agents: list[dict[str, str]] = []
    tasks: list[dict[str, str]] = []
    fingerprint_parts = [overall_goal]

    for unit in units:
        uid = unit["id"]
        goal = unit["goal"]
        role = _agent_role(uid, goal)
        backstory = _agent_backstory(uid)

        agents.append({"role": role, "goal": goal, "backstory": backstory})
        tasks.append(
            {
                "description": goal,
                "expected_output": "A concise summary of the outcome.",
                "agent_role": role,
            }
        )
        fingerprint_parts.append(f"{uid}:{goal}")

    spec_hash = _sha256_short("\n".join(fingerprint_parts))

    return {
        "kind": _CREW_SPEC_KIND,
        "version": _CREW_SPEC_VERSION,
        "source": source,
        "goal": overall_goal,
        "spec_hash": spec_hash,
        "agents": agents,
        "tasks": tasks,
    }


# ---------------------------------------------------------------------------
# Receipt type
# ---------------------------------------------------------------------------


@dataclass
class CrewRunReceipt:
    """Accountability receipt for a crewai run executed under onmc.

    This is a plain dataclass — importable even when crewai is absent.
    It mirrors the spirit of ``RunReceipt`` but is intentionally lightweight:
    no hash chain, no git SHAs, because a crewai run is not an onmc loop.

    Fields
    ------
    spec_hash:
        12-char SHA-256 fingerprint of the crew spec (from ``plan_to_crew_spec``).
    goal:
        Top-level goal from the crew spec.
    outcome:
        Short outcome string returned by the runner (truncated to 500 chars).
    agent_count:
        Number of agents in the crew spec.
    task_count:
        Number of tasks in the crew spec.
    runner:
        Which runner was used: ``"crewai"`` (real backend) or ``"injected"``
        (test/custom runner).
    started_at:
        ISO-8601 UTC timestamp when the run began.
    ended_at:
        ISO-8601 UTC timestamp when the run ended.
    onmc_version:
        Installed oh-no-my-claudecode version string (or ``"unknown"``).
    python_version:
        ``sys.version_info`` as ``"major.minor"``.
    platform:
        ``sys.platform`` value.
    extra:
        Any extra key/value pairs the runner returned; preserved for traceability.
    """

    spec_hash: str
    goal: str
    outcome: str
    agent_count: int
    task_count: int
    runner: str
    started_at: str
    ended_at: str
    onmc_version: str
    python_version: str
    platform: str
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "kind": "crew_run_receipt",
            "spec_hash": self.spec_hash,
            "goal": self.goal,
            "outcome": self.outcome,
            "agent_count": self.agent_count,
            "task_count": self.task_count,
            "runner": self.runner,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "onmc_version": self.onmc_version,
            "python_version": self.python_version,
            "platform": self.platform,
            "extra": self.extra,
        }


# ---------------------------------------------------------------------------
# Runner type alias
# ---------------------------------------------------------------------------

#: Injectable crew runner.  Signature: ``(spec: dict) -> dict``.
#: The returned dict must contain an ``"output"`` key (str).
#: Additional keys are preserved in ``CrewRunReceipt.extra``.
CrewRunner = Callable[[dict[str, Any]], dict[str, Any]]


# ---------------------------------------------------------------------------
# Real crewai backend (imported lazily — only when crewai is present)
# ---------------------------------------------------------------------------


def _run_via_crewai(spec: dict[str, Any]) -> dict[str, Any]:
    """Execute the crew spec using the real crewai library.

    Raises ``RuntimeError`` (not bare ``ImportError``) when crewai is absent
    so callers get a single, predictable exception type.

    The crewai import is wrapped in ``try/except ImportError`` with a
    ``# noqa: PLC0415`` suppressor (non-top-level import is intentional here).
    """
    try:
        from crewai import Agent, Crew, Task  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "crewai is not installed. "
            "Install the optional extra: pip install 'oh-no-my-claudecode[crewai]'"
        ) from exc

    agents_cfg = spec.get("agents", [])
    tasks_cfg = spec.get("tasks", [])

    # Build Agent instances (role → Agent lookup for task wiring).
    role_to_agent: dict[str, Any] = {}
    for a in agents_cfg:
        agent = Agent(
            role=a["role"],
            goal=a["goal"],
            backstory=a["backstory"],
            verbose=False,
        )
        role_to_agent[a["role"]] = agent

    # Build Task instances wired to their agents.
    task_objs: list[Any] = []
    for t in tasks_cfg:
        assigned = role_to_agent.get(t["agent_role"])
        task = Task(
            description=t["description"],
            expected_output=t["expected_output"],
            agent=assigned,
        )
        task_objs.append(task)

    crew = Crew(agents=list(role_to_agent.values()), tasks=task_objs, verbose=False)
    result = crew.kickoff()

    # crewai's result object has a .raw or .output attribute depending on version.
    raw = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    return {"output": str(raw)}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_crew(
    spec: dict[str, Any],
    *,
    runner: CrewRunner | None = None,
) -> CrewRunReceipt:
    """Execute a crew spec and return an onmc accountability receipt.

    Parameters
    ----------
    spec:
        A crew specification dict as returned by ``plan_to_crew_spec``.
    runner:
        Injectable callable ``(spec: dict) -> dict``.  The returned dict must
        contain an ``"output"`` key (str).  When ``None``, the real crewai
        backend is used (requires the ``[crewai]`` extra).

    Returns
    -------
    CrewRunReceipt
        Tamper-light accountability record of the run.

    Raises
    ------
    RuntimeError
        When ``runner`` is ``None`` and crewai is not installed.
    """
    try:
        from oh_no_my_claudecode import __version__ as _ver  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        _ver = "unknown"

    ts_start = datetime.now(UTC).isoformat()
    effective_runner = "injected" if runner is not None else "crewai"
    run_fn = runner if runner is not None else _run_via_crewai

    raw_result = run_fn(spec)

    ts_end = datetime.now(UTC).isoformat()

    outcome = str(raw_result.get("output", ""))[:500]
    extra = {k: v for k, v in raw_result.items() if k != "output"}

    return CrewRunReceipt(
        spec_hash=spec.get("spec_hash", ""),
        goal=str(spec.get("goal", ""))[:500],
        outcome=outcome,
        agent_count=len(spec.get("agents", [])),
        task_count=len(spec.get("tasks", [])),
        runner=effective_runner,
        started_at=ts_start,
        ended_at=ts_end,
        onmc_version=_ver,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        platform=sys.platform,
        extra=extra,
    )
