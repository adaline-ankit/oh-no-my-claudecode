"""The ``onmc swarmreplay`` feature — time-travel reconstruction of a swarm run.

``swarmreplay`` answers "what happened, and in what order?" for a completed
(or in-flight) swarm run, by reusing the same read-only readers Mission
Control uses (``.onmc/swarm/<id>/manifest.json`` + each unit's tamper-evident
receipt) and flattening them into a single, globally ordered, per-iteration
timeline. It is a sibling to :mod:`oh_no_my_claudecode.missioncontrol`: where
Mission Control answers *what is my swarm doing right now*, ``swarmreplay``
answers *what happened, step by step*, deterministically after the fact — the
CLI foundation for a future UI scrubber.

Named ``swarmreplay`` (not ``replay``) because ``onmc replay`` is already the
"Replay Lab" feature (:mod:`oh_no_my_claudecode.replay` — re-derives memory
recall/guard hits over a recorded trace session, wired directly in
``cli.py``). This is an unrelated feature, so it ships under a distinct
top-level command name to avoid a collision.

The core (:func:`build_replay`) is pure and deterministic: given the same
on-disk state it always produces the same :class:`Replay`. No LLM call, no
clock read, no randomness — units are ordered by receipt ``started_at`` and
iterations are taken in ``iteration_hashes`` order.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a
``swarmreplay.commands`` module exposing ``register(app)`` — **zero** edits to
``cli.py`` or any shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.swarmreplay.replay import (
    Replay,
    ReplayStep,
    build_replay,
    render_step_text,
    render_text,
)

__all__ = [
    "Replay",
    "ReplayStep",
    "build_replay",
    "render_step_text",
    "render_text",
]
