"""The ``onmc timeline`` feature — the repo's evolution story from its brain.

``timeline`` orders the durable memory (decisions, invariants, gotchas,
dead-ends, …) over time into a readable narrative grouped into periods. It is a
sibling to :mod:`oh_no_my_claudecode.digest`: where ``digest`` answers *what
changed since a git ref*, ``timeline`` answers *how did this repo get here*.

The core is pure and deterministic (see :func:`build_timeline`): given the same
list of :class:`~oh_no_my_claudecode.models.MemoryEntry` objects it always
produces the same :class:`Timeline`. No LLM call, no clock read at import time —
the command layer passes any ``now`` needed for ``--since`` parsing.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``timeline.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any shared
hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.timeline.timeline import (
    Period,
    Timeline,
    TimelineEntry,
    build_timeline,
    render_markdown,
    render_summary,
)

__all__ = [
    "Period",
    "Timeline",
    "TimelineEntry",
    "build_timeline",
    "render_markdown",
    "render_summary",
]
