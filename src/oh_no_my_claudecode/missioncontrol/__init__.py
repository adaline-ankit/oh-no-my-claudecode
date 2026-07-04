"""The ``onmc missioncontrol`` feature — a live, read-only swarm dashboard.

Mission Control answers "what is my swarm doing *right now*?" without touching
any swarm state.  It reads the manifest + receipts the swarm orchestrator
writes (see :mod:`oh_no_my_claudecode.swarm.inline`) and renders a per-unit
status view: lifecycle state, whether a tamper-evident receipt exists, its
``verified`` flag and ``diff_sha``, plus the abort-sentinel state.

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

__all__ = [
    "DashboardModel",
    "UnitStatus",
    "build_dashboard",
    "list_swarm_ids",
    "render_dashboard",
    "render_swarm_list",
]
