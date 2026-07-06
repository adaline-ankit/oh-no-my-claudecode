"""The ``onmc blackboard`` feature — shared-memory coordination board for a swarm.

A blackboard is a shared **append-only** board where swarm units post
findings/claims/warnings/questions (and a terminal "done") so other units
(and humans) can read what's already known instead of every unit working
blind. It is the foundation for collaborative multi-agent work: purely
additive, an opt-in coordination channel + reader that does not change how
existing swarm units execute.

The core (:mod:`oh_no_my_claudecode.blackboard.blackboard`) is pure and
path-based; the CLI (:mod:`oh_no_my_claudecode.blackboard.commands`)
self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`) — **zero** edits to ``cli.py``
or any shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.blackboard.blackboard import (
    DEFAULT_KIND,
    VALID_KINDS,
    BoardEntry,
    InvalidEntryError,
    append_entry,
    filter_entries,
    read_board,
    render_board,
)

__all__ = [
    "DEFAULT_KIND",
    "VALID_KINDS",
    "BoardEntry",
    "InvalidEntryError",
    "append_entry",
    "filter_entries",
    "read_board",
    "render_board",
]
