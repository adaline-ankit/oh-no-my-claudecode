"""Mission — plan safely or execute the shared ONMC harness.

``onmc mission "<goal>"`` composes recall/guard, context packing, codegraph
blast radius, and the typed execution contract into one inspectable plan.

The default is **plan mode** (a deterministic, offline dry-run): assemble the
mission plan and show it without spawning an agent. ``--execute`` delegates to
the real verifier-backed harness used by ``onmc run --execute``.

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
