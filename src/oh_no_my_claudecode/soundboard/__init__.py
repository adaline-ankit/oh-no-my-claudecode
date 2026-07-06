"""Soundboard — fun inline terminal event reactions.

Maps session events (test_pass, build_break, pr_merged, etc.) to emoji /
ASCII / terminal-bell reactions and lets users bind custom reactions.

This is **distinct from** the ``notify`` subsystem which dispatches events
to external sinks (Discord, Slack, file).  Soundboard is purely inline:
it prints a string (and optionally sounds a terminal bell ``\\a``) directly
to the terminal.

Public API
----------
- ``DEFAULTS``          — built-in event → :class:`Reaction` map.
- ``Reaction``          — a named reaction string (may end with ``\\a``).
- ``react``             — look up and return the :class:`Reaction` for an event.
- ``load_bindings``     — load user overrides from ``.onmc/soundboard/bindings.json``.
- ``save_bindings``     — persist a bindings dict to disk.
- ``merged_bindings``   — merge defaults with user overrides (overrides win).
"""

from __future__ import annotations

from oh_no_my_claudecode.soundboard.board import (
    DEFAULTS,
    Reaction,
    load_bindings,
    merged_bindings,
    react,
    save_bindings,
)

__all__ = [
    "DEFAULTS",
    "Reaction",
    "load_bindings",
    "merged_bindings",
    "react",
    "save_bindings",
]
