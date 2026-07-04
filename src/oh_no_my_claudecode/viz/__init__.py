"""Static diagram rendering for onmc's graphs.

``onmc viz`` renders two of onmc's internal graphs as diagram text — shareable,
screenshot-able, and paste-able into GitHub, Obsidian, mermaid.live, or any
D2-compatible tool. There is no server and no new dependency.

This is deliberately **distinct** from ``onmc missioncontrol`` (the live
dashboard). ``viz`` emits deterministic diagram *source* to stdout.

Two diagram formats are supported:

* **Mermaid** (default) — ``graph TD`` text.
* **D2** — `terrastruct.com/d2 <https://terrastruct.com/d2>`_ text via
  ``--format d2``.

- ``onmc viz memory`` → the memory relationship graph: nodes are memory
  entries (grouped by :class:`~oh_no_my_claudecode.models.memory.MemoryKind`),
  edges are :class:`~oh_no_my_claudecode.models.memory_edge.MemoryEdge` rows
  (``supersedes`` / ``contradicts`` / ``relates`` / ``duplicate_of``).
- ``onmc viz code [<target>]`` → the code-graph blast radius of a file or
  symbol, reusing :func:`oh_no_my_claudecode.codegraph.neighbors`.

The package self-registers via the command auto-discovery hook (see
:mod:`oh_no_my_claudecode.command_registry`) — adding it touches no shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.viz.d2 import code_d2, memory_d2
from oh_no_my_claudecode.viz.mermaid import code_mermaid, memory_mermaid

__all__ = ["code_d2", "code_mermaid", "memory_d2", "memory_mermaid"]
