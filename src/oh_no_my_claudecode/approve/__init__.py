"""The ``onmc approve`` feature — the executor that closes the phone-to-merge loop.

The mission bridge only *parses* a chat approval ("approve unit 2" / "approve
all" / a button callback) into an
:class:`~oh_no_my_claudecode.missionbridge.models.ApproveAction`.  This feature
*executes* it: a parsed action becomes a real action — merge the approved,
**verified** unit's PR.

Accountability is the whole point: the executor refuses to act on any unit that
is not a verified success (held / unverified / receipt-less / aborted units are
never merged), and merging is DRY-by-default — real execution requires an
explicit ``--execute``.

Modules
-------
executor  — pure ``plan_approval(card, action) -> ApprovalPlan`` decision core
            plus the thin, injectable-merger ``execute_plan`` side-effecting step.
commands  — CLI surface (``register(app)``), auto-discovered by the registry.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`) — **zero** edits to ``cli.py``.
"""

from __future__ import annotations

from oh_no_my_claudecode.approve.executor import (
    REASON_ABORTED,
    REASON_HELD,
    REASON_NOT_FOUND,
    REASON_UNVERIFIED,
    ApprovalPlan,
    ExecutionResult,
    MergeOutcome,
    Merger,
    execute_plan,
    plan_approval,
)

__all__ = [
    "REASON_ABORTED",
    "REASON_HELD",
    "REASON_NOT_FOUND",
    "REASON_UNVERIFIED",
    "ApprovalPlan",
    "ExecutionResult",
    "MergeOutcome",
    "Merger",
    "execute_plan",
    "plan_approval",
]
