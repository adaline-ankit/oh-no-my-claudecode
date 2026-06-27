"""Deterministic task → agent/model/strategy router for ``onmc``.

This feature ships as a self-contained package and registers its CLI surface via
the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`) — adding it touches **zero** shared
hub files (``cli.py``, ``core/service.py``, ``rendering/console.py``).

The core is a pure function :func:`route_task` that maps a free-text task
description to a :class:`RouteDecision` using deterministic keyword/intent rules.
No LLM, no I/O — same input always yields the same decision.
"""

from __future__ import annotations

from oh_no_my_claudecode.route.router import RouteDecision, route_task

__all__ = ["RouteDecision", "route_task"]
