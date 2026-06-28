"""One-command grounded mission planning for ``onmc``.

This feature ships as a self-contained package and registers its CLI surface via
the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`) — adding it touches **zero** shared
hub files (``cli.py``, ``core/service.py``, ``rendering/console.py``).

The core is a pure-ish composer :func:`compile_mission` that assembles a
:class:`MissionPlan` for a goal out of onmc's already-shipped primitives:

- **recall + guard** (relevant decisions + KNOWN dead-ends to avoid) and
  **pack + codegraph** (a tiny relevant file set) — both via the existing
  :func:`oh_no_my_claudecode.pack.builder.build_pack`, which already composes
  guard/recall/reuse/codegraph and degrades gracefully to empty.
- **route** — :func:`oh_no_my_claudecode.route.router.route_task` recommends an
  agent/model/strategy deterministically.
- a suggested swarm **unit breakdown** plus the exact ``onmc swarm plan ...``
  command to run next.

It PLANS and grounds the mission; it does **not** spawn agents — it emits the
swarm command to run, keeping the whole thing offline and auth-free.
"""

from __future__ import annotations

from oh_no_my_claudecode.mission.planner import MissionPlan, compile_mission

__all__ = ["MissionPlan", "compile_mission"]
