"""The ``onmc postmortem`` feature — LLM-free narrative recap of a swarm run.

``postmortem`` turns a completed swarm's manifest (see
:mod:`oh_no_my_claudecode.missioncontrol.dashboard`) plus each unit's
tamper-evident receipt (see :mod:`oh_no_my_claudecode.loop.receipt`) into a
readable, deterministic story: an overview (units / verified / failed / total
wall time), a per-unit account of what happened, and an honest summary of what
went well versus what needs attention. There is **no LLM call** anywhere in
this module — every sentence is assembled from data already on disk.

The core (:mod:`oh_no_my_claudecode.postmortem.postmortem`) is pure: given a
:class:`~oh_no_my_claudecode.missioncontrol.dashboard.DashboardModel` and an
injectable receipt reader it always produces the same
:class:`~oh_no_my_claudecode.postmortem.postmortem.Postmortem`. Missing or
partial data degrades gracefully — a unit without a receipt is reported as
"no receipt recorded" rather than raising.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a
``postmortem.commands`` module exposing ``register(app)`` — **zero** edits to
``cli.py`` or any shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.postmortem.postmortem import (
    HIGH_ITERATION_THRESHOLD,
    Postmortem,
    UnitNarrative,
    build_postmortem,
    render_text,
)

__all__ = [
    "HIGH_ITERATION_THRESHOLD",
    "Postmortem",
    "UnitNarrative",
    "build_postmortem",
    "render_text",
]
