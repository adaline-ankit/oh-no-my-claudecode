"""The ``onmc race`` feature — offline model/strategy tournament over run receipts.

``race`` answers a narrower question than ``onmc flywheel``: *for a specific
goal, which model actually won?*  It clusters recorded ``RunReceipt`` entries
by keyword overlap with a query goal, builds a per-model leaderboard (runs,
verified rate, avg cost, avg wall-time) ranked by verified rate then cost, and
declares a tournament winner — or honestly reports "insufficient data" when the
cluster is too thin to trust (fewer than :data:`MIN_VERIFIED_RUNS` verified
runs). ``onmc race --all`` skips clustering and races every model against the
whole receipt corpus.

Fully offline, deterministic, and LLM-free. Reuses
:func:`oh_no_my_claudecode.ledger.accounting.load_receipts` for I/O — no new
schema, no new storage. Self-registers via the command auto-discovery
convention (see :mod:`oh_no_my_claudecode.command_registry`): it ships a
``race.commands`` module exposing ``register(app)`` — **zero** edits to
``cli.py`` or any shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.race.race import (
    MIN_VERIFIED_RUNS,
    ModelRecord,
    RaceResult,
    build_leaderboard,
    cluster_by_goal,
    goal_keywords,
    race,
)

__all__ = [
    "MIN_VERIFIED_RUNS",
    "ModelRecord",
    "RaceResult",
    "build_leaderboard",
    "cluster_by_goal",
    "goal_keywords",
    "race",
]
