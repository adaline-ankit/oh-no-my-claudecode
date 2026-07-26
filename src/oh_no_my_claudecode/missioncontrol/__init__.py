"""Read-only views over ONMC's canonical runtime and advanced swarm state.

The primary view replays the canonical harness event stream and accepts
``verified`` only from a matching, integrity-valid harness receipt.  The legacy
swarm dashboard remains available as an advanced compatibility view.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a
``missioncontrol.commands`` module exposing ``register(app)`` — **zero** edits
to ``cli.py`` or any shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.missioncontrol.dashboard import (
    DashboardModel,
    UnitStatus,
    build_dashboard,
    list_swarm_ids,
    render_dashboard,
    render_swarm_list,
)
from oh_no_my_claudecode.missioncontrol.runtime import (
    RuntimeDashboard,
    RuntimeNodeStatus,
    RuntimeRunStatus,
    build_runtime_dashboard,
    render_runtime_dashboard,
)

__all__ = [
    "DashboardModel",
    "RuntimeDashboard",
    "RuntimeNodeStatus",
    "RuntimeRunStatus",
    "UnitStatus",
    "build_dashboard",
    "build_runtime_dashboard",
    "list_swarm_ids",
    "render_dashboard",
    "render_runtime_dashboard",
    "render_swarm_list",
]
