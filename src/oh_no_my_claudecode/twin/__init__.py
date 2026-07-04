"""The ``onmc twin`` feature — a repo "digital twin" for change rehearsal.

Before an agent touches code, ``twin`` rehearses the edit against the offline
structural code graph and answers *what would break?*:

- **Blast radius** — which files depend on the ones you're about to touch,
  reusing :func:`oh_no_my_claudecode.codegraph.neighbors`.
- **Covering tests** — the test files that exercise the touched files, so an
  agent knows what to run before and after.
- **High-risk touches** — hub files with many dependents get flagged.

It never executes code and never edits files — a twin is an *analysis*, not a
sandbox runner.  Everything is deterministic and offline; the same repo + same
touched paths always yields the same rehearsal.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``twin.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any shared
hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.twin.twin import (
    HIGH_RISK_DEPENDENTS,
    RehearsalPlan,
    TouchedFile,
    build_rehearsal,
)

__all__ = [
    "HIGH_RISK_DEPENDENTS",
    "RehearsalPlan",
    "TouchedFile",
    "build_rehearsal",
]
