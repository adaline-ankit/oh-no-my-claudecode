"""The ``onmc whip`` feature — live agent steering + reward signal ledger.

Provides a durable *steering-directive queue* and *reward-signal store* that
lets a human (or an outer orchestrator) steer a running Claude Code session
and record whether its output was praised or corrected.

Core I/O is isolated in :mod:`~oh_no_my_claudecode.whip.steer` — all
public functions are pure over injectable ``whip_dir`` and ``ts`` arguments,
making the module fully testable offline.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``whip.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any
shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.whip.steer import (
    PENDING_FILE,
    REWARDS_FILE,
    WHIP_SUBDIR,
    clear,
    consume,
    enqueue,
    pending,
    record_signal,
    tally,
)

__all__ = [
    "PENDING_FILE",
    "REWARDS_FILE",
    "WHIP_SUBDIR",
    "clear",
    "consume",
    "enqueue",
    "pending",
    "record_signal",
    "tally",
]
