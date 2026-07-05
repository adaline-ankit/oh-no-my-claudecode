"""``onmc vibe`` — ambient agent-mood HUD.

Aggregates coach streak, whip reward signals, and quest level/XP into a
single glanceable "mood" status display.  Read-only: never modifies coach,
whip, or quest state.

The core is pure and deterministic (see :mod:`~oh_no_my_claudecode.vibe.hud`):

* :func:`compute_mood` derives a :class:`Mood` from streak / praise / level
  inputs — the same inputs always return the same mood (no wallclock, no
  random).

* :func:`render` formats a :class:`VibeState` into a multi-line HUD string.

* :func:`render_json` returns a JSON-serialisable envelope for pipeline
  composition.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``vibe.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any
shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.vibe.hud import (
    Mood,
    VibeState,
    compute_mood,
    render,
    render_json,
)

__all__ = [
    "Mood",
    "VibeState",
    "compute_mood",
    "render",
    "render_json",
]
