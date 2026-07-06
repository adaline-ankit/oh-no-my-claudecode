"""The ``onmc heatmap`` feature — a GitHub-contributions-style activity grid.

``heatmap`` renders a calendar heatmap of agent run density sourced from the
tamper-evident run receipts written by ``onmc loop`` / ``onmc swarm``. It is a
sibling to :mod:`oh_no_my_claudecode.timeline`: where ``timeline`` narrates
*what happened* over time, ``heatmap`` visualizes *how much happened, when* —
fun, at-a-glance density, like GitHub's contribution graph but for agent work.

The core is pure and deterministic (see :func:`build_heatmap`): given the same
list of receipt dicts and the same ``today`` it always produces the same
:class:`Heatmap`. No LLM call, no clock read at import time — the command
layer supplies ``today`` explicitly.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``heatmap.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any shared
hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.heatmap.heatmap import (
    DEFAULT_WEEKS,
    DayCell,
    Heatmap,
    build_heatmap,
    render_text,
)

__all__ = [
    "DEFAULT_WEEKS",
    "DayCell",
    "Heatmap",
    "build_heatmap",
    "render_text",
]
