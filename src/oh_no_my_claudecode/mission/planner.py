"""Compose onmc's shipped primitives into a single grounded mission plan.

``compile_mission`` is the "one outcome, not 20 commands" composer: given a goal
it assembles a :class:`MissionPlan` by calling the existing, offline primitives
and reshaping their outputs — it reimplements none of them.

Composition
-----------
- :func:`oh_no_my_claudecode.pack.builder.build_pack` already composes
  guard (dead-ends), recall (decisions), reuse hints, and codegraph context
  files, degrading each to empty on a fresh brain / empty repo. We lean on it
  for the *grounding* of the mission (dead-ends + context files + a one-line
  brief assembled from its decisions).
- :func:`oh_no_my_claudecode.route.router.route_task` recommends an
  agent/model/strategy deterministically.
- a suggested swarm unit breakdown is derived from the context files (the
  concrete surfaces the work will touch), and rendered into the exact
  ``onmc swarm plan --task ...`` command to run next.

Determinism & safety
---------------------
Every composed piece is deterministic and offline, and ``build_pack`` is wrapped
graceful-empty internally, so :func:`compile_mission` never spawns an agent,
never makes a network/LLM call, and never crashes on an empty brain — it just
returns a thinner plan. Two calls with the same ``(storage, repo_root, goal,
budget)`` produce an equal :class:`MissionPlan`.
"""

from __future__ import annotations

import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path

from oh_no_my_claudecode.pack.builder import (
    DEFAULT_BUDGET,
    ContextPack,
    build_pack,
)
from oh_no_my_claudecode.route.router import RouteDecision, route_task
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import shorten

__all__ = ["MissionPlan", "compile_mission"]

# Upper bound on suggested swarm units — keep the fan-out advisory and small so
# the emitted plan stays legible and within Claude Code's ~10-subagent cap.
_MAX_UNITS = 6
# Floor so even a context-less mission yields one runnable unit (the goal).
_MIN_UNITS = 1


@dataclass(frozen=True, slots=True)
class MissionPlan:
    """A single grounded plan for a goal, composed from shipped primitives.

    Attributes
    ----------
    goal:
        The mission goal (stripped).
    brief:
        A one-line grounded summary of the mission (goal + prior-decision count).
    dead_ends:
        Recorded dead-ends to avoid, as ``(title, why)`` pairs (from guard via
        the context pack). May be empty.
    context_files:
        A tiny relevant file set (from codegraph via the context pack). May be
        empty on an empty/unreadable repo.
    route:
        The deterministic :class:`RouteDecision` for the goal.
    suggested_units:
        A small ordered list of suggested swarm unit goals.
    next_command:
        The exact ``onmc swarm plan ...`` command to run next.
    """

    goal: str
    brief: str
    dead_ends: list[tuple[str, str]] = field(default_factory=list)
    context_files: list[str] = field(default_factory=list)
    route: RouteDecision | None = None
    suggested_units: list[str] = field(default_factory=list)
    next_command: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe mapping for the ``--json`` CLI surface."""
        return {
            "goal": self.goal,
            "brief": self.brief,
            "dead_ends": [{"title": t, "why": w} for t, w in self.dead_ends],
            "context_files": list(self.context_files),
            "route": asdict(self.route) if self.route is not None else None,
            "suggested_units": list(self.suggested_units),
            "next_command": self.next_command,
        }


def compile_mission(
    storage: SQLiteStorage,
    repo_root: Path,
    goal: str,
    *,
    budget: int = DEFAULT_BUDGET,
) -> MissionPlan:
    """Assemble a deterministic, offline :class:`MissionPlan` for *goal*.

    Parameters
    ----------
    storage:
        Open memory store (for recalled decisions and dead-ends).
    repo_root:
        Repository root (for the code-graph context slice).
    goal:
        The mission goal. May be empty/whitespace; an empty goal yields a
        graceful plan (empty grounding, default route, single unit).
    budget:
        Character budget forwarded to the underlying context pack.
    """
    clean_goal = goal.strip()

    pack = _build_pack(storage, repo_root, clean_goal, budget)
    route = route_task(clean_goal)
    dead_ends = [(d.title, d.why) for d in pack.dead_ends]
    context_files = list(pack.context_files)
    brief = _build_brief(clean_goal, pack)
    units = _suggest_units(clean_goal, context_files)
    next_command = _swarm_plan_command(units)

    return MissionPlan(
        goal=clean_goal,
        brief=brief,
        dead_ends=dead_ends,
        context_files=context_files,
        route=route,
        suggested_units=units,
        next_command=next_command,
    )


def _build_pack(
    storage: SQLiteStorage,
    repo_root: Path,
    goal: str,
    budget: int,
) -> ContextPack:
    """Build the grounding context pack, never raising on a fresh brain.

    ``build_pack`` already wraps each composed compiler graceful-empty, but we
    add a belt-and-braces guard so a missing/corrupt store can never abort the
    whole mission plan.
    """
    try:
        return build_pack(storage, repo_root, goal, budget=budget)
    except Exception:  # noqa: BLE001 - a fresh/empty brain must never crash the mission
        return ContextPack(goal=goal, budget=max(budget, 0))


def _build_brief(goal: str, pack: ContextPack) -> str:
    """Compose a one-line grounded brief from the goal and recalled decisions."""
    if not goal:
        return "No goal provided — nothing to ground."

    parts = [f"Mission: {shorten(goal, max_length=160)}"]
    if pack.decisions:
        lead = pack.decisions[0].title
        more = len(pack.decisions) - 1
        suffix = f" (+{more} more)" if more > 0 else ""
        parts.append(f"Respects {len(pack.decisions)} prior decision(s): {lead}{suffix}")
    if pack.dead_ends:
        parts.append(f"Avoids {len(pack.dead_ends)} known dead-end(s)")
    if pack.context_files:
        parts.append(f"Touches ~{len(pack.context_files)} relevant file(s)")
    return ". ".join(parts) + "."


def _suggest_units(goal: str, context_files: list[str]) -> list[str]:
    """Derive a small ordered set of suggested swarm unit goals.

    Heuristic, deterministic breakdown: when the code graph surfaced concrete
    files, propose one focused unit per file (capped), each phrased as the goal
    scoped to that file. With no context (empty repo / empty brain) fall back to
    a single unit that is the goal itself, so the plan is always runnable.
    """
    if not goal:
        return []
    if not context_files:
        return [goal]

    units = [
        f"{goal} — focus on {path}" for path in context_files[: _MAX_UNITS - 1]
    ]
    # Always include an integration/verification unit so the fan-out converges.
    units.append(f"{goal} — integrate and verify across the touched files")
    return units[: max(_MIN_UNITS, _MAX_UNITS)]


def _swarm_plan_command(units: list[str]) -> str:
    """Render the exact ``onmc swarm plan`` command for *units*.

    Emits one ``--task`` per unit, shell-quoted, plus ``--json`` so the caller
    can pipe the resulting manifest. Returns an empty string when there are no
    units (an empty goal), since there is nothing to plan.
    """
    if not units:
        return ""
    flags = " ".join(f"--task {shlex.quote(unit)}" for unit in units)
    return f"onmc swarm plan {flags} --json"
