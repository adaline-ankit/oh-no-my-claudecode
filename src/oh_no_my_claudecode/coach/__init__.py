"""The ``onmc coach`` feature — live hype/roast session commentator + streaks.

``coach`` is a personality layer that reacts to per-event coding-session
activity (e.g. ``test_pass``, ``build_break``, ``pr_merged``) with a
tone-matched quip (hype / roast / dry) and tracks green/red streaks across
the session.

Distinct from :mod:`oh_no_my_claudecode.roast` (which scores static
agent-readiness); ``coach`` is live, per-event, and stateful.

The core is pure and deterministic (see :mod:`oh_no_my_claudecode.coach.commentary`):

*  ``quip(event, tone, *, seed)`` returns a line from a template bank using
   ``seed`` as the selection index — the same triple always produces the same
   line, making tests trivially assertable and the feature fully reproducible.

*  ``StreakState`` + ``advance(state, event)`` implement an immutable streak
   tracker; green events extend the streak, red events reset it.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``coach.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any shared
hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.coach.commentary import (
    GREEN_EVENTS,
    RED_EVENTS,
    StreakState,
    advance,
    quip,
)

__all__ = [
    "GREEN_EVENTS",
    "RED_EVENTS",
    "StreakState",
    "advance",
    "quip",
]
