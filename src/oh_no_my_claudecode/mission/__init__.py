"""Mission — the keystone command that composes the shipped pipeline.

``onmc mission "<goal>"`` runs the full engineering pipeline end-to-end and
produces ONE result + plan: recall/guard (dead-ends) → pack (context) →
codegraph (blast radius) → swarm plan.  It does not reimplement any of those —
it *orchestrates* the existing pure compilers.

The default is **plan mode** (a deterministic, offline dry-run): assemble the
mission plan and show it without spawning a single agent.  ``--execute`` hands
the plan to ``onmc swarm`` (emitting the inline-swarm plan) but never spawns
agents in this build.

See :mod:`oh_no_my_claudecode.mission.pipeline` for the planner and
:mod:`oh_no_my_claudecode.mission.commands` for the auto-discovered CLI surface.
"""

from __future__ import annotations

from oh_no_my_claudecode.mission.pipeline import (
    MissionPlan,
    MissionStep,
    plan_mission,
    render_mission_markdown,
    run_mission,
)

__all__ = [
    "MissionPlan",
    "MissionStep",
    "plan_mission",
    "render_mission_markdown",
    "run_mission",
]
