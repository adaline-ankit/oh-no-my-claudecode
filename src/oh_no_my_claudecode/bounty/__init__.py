"""The ``onmc bounty`` feature — task wagers + payout ledger.

Put a points/XP wager on a task, then collect (or forfeit) the payout when it
is resolved.  This is the *stakes* layer: it turns tasks into bounties with
a deterministic payout formula based on difficulty.

Core I/O is isolated in :mod:`~oh_no_my_claudecode.bounty.board` — all public
functions are pure over injectable ``bounty_dir`` and ``now_iso`` arguments,
making the module fully testable offline.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``bounty.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any
shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.bounty.board import (
    BOARD_FILE,
    BOUNTY_SUBDIR,
    DIFFICULTIES,
    DIFFICULTY_MULTIPLIERS,
    LEDGER_FILE,
    STATUS_CLAIMED,
    STATUS_FORFEITED,
    STATUS_OPEN,
    Bounty,
    balance,
    claim,
    forfeit,
    list_bounties,
    payout,
    post,
    total_pot,
)

__all__ = [
    "BOARD_FILE",
    "BOUNTY_SUBDIR",
    "DIFFICULTIES",
    "DIFFICULTY_MULTIPLIERS",
    "LEDGER_FILE",
    "STATUS_CLAIMED",
    "STATUS_FORFEITED",
    "STATUS_OPEN",
    "Bounty",
    "balance",
    "claim",
    "forfeit",
    "list_bounties",
    "payout",
    "post",
    "total_pot",
]
