"""The ``onmc flywheel`` feature — self-improving trajectory analysis.

``flywheel`` mines onmc's uniquely-held asset: *verified* run trajectories.
Every ``onmc loop`` / ``onmc swarm`` run writes a tamper-evident
:class:`~oh_no_my_claudecode.loop.receipt.RunReceipt` recording the model, the
honest ``verified`` flag, cost, and wall-time.  No other tool has
verified-*outcome* data keyed to the approach that produced it.

This feature aggregates that corpus (by model, by goal keyword) and recommends
the approach that has historically produced verified results for work like
yours — a self-improvement flywheel grounded in real, verified outcomes rather
than vibes.  It composes existing signals: it reuses the ledger's on-disk
receipt reader for I/O and re-uses the same honesty constraints (null cost is
never faked; insufficient samples are stated, not smoothed over).

Fully offline and deterministic — no LLM call.  Self-registers via the command
auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``flywheel.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any shared
hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.flywheel.analyze import (
    MIN_SAMPLES,
    FlywheelReport,
    KeywordStat,
    ModelStat,
    load_trajectories,
    recommend,
    summarize,
)

__all__ = [
    "MIN_SAMPLES",
    "FlywheelReport",
    "KeywordStat",
    "ModelStat",
    "load_trajectories",
    "recommend",
    "summarize",
]
