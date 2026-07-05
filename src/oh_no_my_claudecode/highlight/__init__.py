"""The ``onmc highlight`` feature — curated session highlight reel.

Mines verified run receipts for the BEST moments in a coding session and renders
a shareable recap, like a sports highlight reel. Distinct from ``replay`` (full
step-by-step) and ``timeline`` (chronological milestones) — ``highlight`` is a
CURATED, RANKED "best-of" selection.

Moments surfaces:

- **Biggest win**: the highest-value verified run (by cost + wall time invested).
- **Boss kill**: hardest task completed (by wall time in verified runs).
- **Longest streak**: max consecutive days with at least one verified run.
- **Most efficient**: verified run with the best outcome-to-cost ratio.
- **Fastest merge**: shortest wall-time verified run.

Pure core in :mod:`oh_no_my_claudecode.highlight.reel`: ``build_reel`` is
injected with ``now`` for determinism; no clock or random calls inside.

Command auto-discovery: ships ``highlight/commands.py`` exposing ``register(app)``
— zero edits to ``cli.py`` or any hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.highlight.reel import (
    Moment,
    Reel,
    build_reel,
    render_markdown,
)

__all__ = [
    "Moment",
    "Reel",
    "build_reel",
    "render_markdown",
]
