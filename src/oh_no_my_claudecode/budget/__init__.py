"""``onmc budget`` — cross-session token/cost guardian (kills the Tokenocalypse).

This feature is *enforcement*: it reads run receipts, sums spend over a rolling
window (day / week / all), and answers a single question — *may a new run
proceed, or has the hard cap been blown?* It emits an early-warning state at a
configurable ratio (default 80 %) and a ``blocked`` state that a pre-run hook or
CI gate can act on (``onmc budget check`` exits non-zero when blocked).

It is deliberately distinct from two neighbours:

- :mod:`oh_no_my_claudecode.cost` — a *read-only* spend breakdown and forecast
  ("where did the money go?"). ``budget`` reuses ``cost``'s receipt-spend
  compiler (:func:`oh_no_my_claudecode.cost.cost.build_cost_report`) rather than
  re-parsing receipts, but adds a cap and a block decision on top.
- :mod:`oh_no_my_claudecode.membudget` — a *byte* budget for the memory store,
  nothing to do with dollars or tokens.

The core (:mod:`oh_no_my_claudecode.budget.guard`) is pure and deterministic;
the CLI layer (:mod:`oh_no_my_claudecode.budget.commands`) resolves the repo,
loads receipts, and renders.
"""

from __future__ import annotations

from oh_no_my_claudecode.budget.guard import (
    BudgetDecision,
    check_budget,
    evaluate,
)

__all__ = [
    "BudgetDecision",
    "check_budget",
    "evaluate",
]
