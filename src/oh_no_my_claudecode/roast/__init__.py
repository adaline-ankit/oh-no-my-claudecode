"""The ``onmc roast`` feature — a blunt 0-100 agent-readiness score.

``roast`` answers one viral question: *how ready is this repo for an AI coding
agent?*  It does **not** invent new analysis; it composes signals that already
exist elsewhere in onmc:

- **Hotspot memory coverage** — :func:`oh_no_my_claudecode.coverage.compiler.compile_coverage`
  tells us which high-churn files have zero stored memory.  Those are the
  landmines where an agent burns tokens rediscovering context.
- **Agent-config security** — :func:`oh_no_my_claudecode.audit.scanner.run_audit`
  grades the ``.claude`` / ``.mcp`` configuration surface.
- **Brain size** — :meth:`SQLiteStorage.list_memories` tells us how much durable
  context the repo has accumulated at all.
- **Conventions presence** — a ``.onmc/conventions.md`` file means spawned agents
  inherit the repo's coding norms instead of guessing.

The blend is a documented, deterministic weighted sum (see
:func:`oh_no_my_claudecode.roast.scorer.compute_roast`).  Same repo + same brain
→ same score, every time.  No LLM call, fully offline.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``roast.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any shared
hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.roast.scorer import RoastReport, compute_roast

__all__ = ["RoastReport", "compute_roast"]
