"""The ``onmc standup`` feature — a periodic agent-activity digest.

``standup`` answers *what did my agents do* over a recent window, summarising
run receipts (:mod:`oh_no_my_claudecode.ledger.accounting`) into a
daily-standup-style report: run counts, verified/failed split, cost, wall
time, per-model breakdown, top goals, and notable items (failures,
high-iteration runs).

It is a sibling to :mod:`oh_no_my_claudecode.digest` (a memory changelog) and
:mod:`oh_no_my_claudecode.timeline` (a memory narrative) — but ``standup``
looks at **runs**, not memories.

The core is pure and deterministic (see :func:`build_standup`): given the same
list of receipt dicts and the same ``now``, it always produces the same
:class:`StandupReport`. No LLM call, no randomness — the command layer passes
in the loaded receipts and ``now``.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a
``standup.commands`` module exposing ``register(app)`` — **zero** edits to
``cli.py`` or any shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.standup.standup import (
    DEFAULT_SINCE,
    HIGH_ITERATION_THRESHOLD,
    GoalBreakdown,
    ModelBreakdown,
    NotableRun,
    StandupReport,
    build_standup,
    parse_since,
    render_text,
)

__all__ = [
    "DEFAULT_SINCE",
    "HIGH_ITERATION_THRESHOLD",
    "GoalBreakdown",
    "ModelBreakdown",
    "NotableRun",
    "StandupReport",
    "build_standup",
    "parse_since",
    "render_text",
]
