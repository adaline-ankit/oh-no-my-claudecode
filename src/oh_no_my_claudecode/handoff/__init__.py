"""The ``onmc handoff`` feature — portable cross-session task-context bundles.

``handoff`` answers one question: *how does a fresh agent or a new session pick
up a task exactly where the last one left off?*  It does not invent new analysis;
it packages signals that already exist in onmc into one portable JSON bundle:

- the deterministic per-task **context pack**
  (:func:`oh_no_my_claudecode.pack.builder.build_pack`),
- the goal-relevant **decisions** from the institutional-memory graph
  (:func:`oh_no_my_claudecode.orggraph.graph.build_org_graph`),
- the recorded **dead-ends** the agent must not retry
  (:func:`oh_no_my_claudecode.guard.compiler.compile_guard`),
- and the most-recent tamper-evident **run receipts**
  (:func:`oh_no_my_claudecode.badge.load_receipt`).

``onmc handoff create <goal>`` builds and writes the bundle; ``onmc handoff
resume <file>`` reads it back into a briefing. Both are offline and degrade
gracefully — a missing source yields an empty section plus a note, never a crash.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``handoff.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.handoff.handoff import (
    BUNDLE_VERSION,
    HandoffBundle,
    build_handoff,
    read_bundle,
    render_resume,
    summarize,
    write_bundle,
)

__all__ = [
    "BUNDLE_VERSION",
    "HandoffBundle",
    "build_handoff",
    "read_bundle",
    "render_resume",
    "summarize",
    "write_bundle",
]
