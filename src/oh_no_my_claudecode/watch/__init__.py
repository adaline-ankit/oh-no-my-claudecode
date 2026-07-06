"""The ``onmc watch`` feature — an auto-refreshing terminal live swarm monitor.

Watch answers "what are my agents doing *right now*?" across every swarm at
once, refreshed on an interval, without touching any swarm state. It is the
terminal-native complement to the web ``onmc ui`` and is distinct from
``onmc missioncontrol``, which renders a one-shot snapshot of a single named
swarm.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``watch.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any
shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.watch.watch import (
    SwarmFrame,
    WatchFrame,
    build_frame,
    render_frame,
)

__all__ = [
    "SwarmFrame",
    "WatchFrame",
    "build_frame",
    "render_frame",
]
