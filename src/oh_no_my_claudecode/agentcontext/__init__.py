"""One-shot agent context for a file: codegraph blast radius + relevant memory.

``onmc context <file>`` combines two signals a coding agent needs before
editing a file:

1. **Blast radius** — which files depend on it (dependents), what it depends on
   (imports), and which tests exercise it (tests) — sourced from the structural
   code graph (:mod:`oh_no_my_claudecode.codegraph`).

2. **Relevant memory** — onmc memories that mention the file or are semantically
   related to it, drawn from the memory store via
   :meth:`~oh_no_my_claudecode.core.service.OnmcService.search_memories`.

Pure assembly logic lives in :mod:`oh_no_my_claudecode.agentcontext.build` so
tests can inject fake graphs and memory lists without touching real storage.
The CLI surface is in :mod:`oh_no_my_claudecode.agentcontext.commands`.
"""

from __future__ import annotations

from oh_no_my_claudecode.agentcontext.build import (
    AgentContext,
    BlastRadius,
    MemoryHit,
    build_context,
)

__all__ = [
    "AgentContext",
    "BlastRadius",
    "MemoryHit",
    "build_context",
]
