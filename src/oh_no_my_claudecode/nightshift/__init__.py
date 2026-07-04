"""onmc nightshift — plan a bounded, verified overnight swarm + morning digest.

``onmc nightshift`` answers: *given a backlog and a budget, exactly which swarm
units run overnight, and — the next morning — which of them actually verified?*
It is the accountability spine of an unattended run: a bounded plan up front, a
verified-vs-failed morning report after.

The default is **dry-run** (plan mode): it composes a
:class:`~oh_no_my_claudecode.nightshift.runner.NightshiftPlan` and prints a
sample morning digest WITHOUT spawning a single agent or touching the swarm
state directory — mirroring ``onmc mission``'s plan-mode safety.  The real
inline fan-out (via :func:`oh_no_my_claudecode.swarm.inline.plan_inline_swarm`)
is the model's job, driven from the emitted plan.

Self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``nightshift.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any shared
hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.nightshift.digest import render_morning_digest
from oh_no_my_claudecode.nightshift.runner import (
    DEFAULT_BUDGET,
    NightshiftPlan,
    NightshiftSummary,
    NightshiftUnit,
    plan_nightshift,
    summarize_receipts,
)

__all__ = [
    "DEFAULT_BUDGET",
    "NightshiftPlan",
    "NightshiftSummary",
    "NightshiftUnit",
    "plan_nightshift",
    "render_morning_digest",
    "summarize_receipts",
]
