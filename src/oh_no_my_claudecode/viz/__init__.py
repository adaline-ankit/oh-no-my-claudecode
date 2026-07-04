"""Static Mermaid diagram rendering for onmc's graphs.

``onmc viz`` renders two of onmc's internal graphs as **Mermaid** ``graph TD``
text — shareable, screenshot-able, and paste-able into GitHub, Obsidian, or
`mermaid.live`. There is no server and no new dependency: Mermaid is just text.

This is deliberately **distinct** from ``onmc missioncontrol`` (the live
dashboard). ``viz`` emits deterministic diagram *source* to stdout.

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

from oh_no_my_claudecode.viz.mermaid import code_mermaid, memory_mermaid

__all__ = ["code_mermaid", "memory_mermaid"]
