"""Pure assembly of agent context from pre-fetched codegraph + memory inputs.

This module is intentionally side-effect-free.  It takes already-fetched
:class:`~oh_no_my_claudecode.codegraph.models.Neighbors` and
:class:`~oh_no_my_claudecode.models.memory.MemoryEntry` lists and assembles a
single :class:`AgentContext` record.

Keeping the assembly pure means tests can inject any fake graph or memory list
and assert the output structure without touching the filesystem, SQLite, or any
external service.

Callers that *do* want real data should use the helpers in
:mod:`oh_no_my_claudecode.agentcontext.commands` or call
:meth:`~oh_no_my_claudecode.core.service.OnmcService.codegraph_neighbors` and
:meth:`~oh_no_my_claudecode.core.service.OnmcService.search_memories` directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from oh_no_my_claudecode.codegraph.models import Neighbors
from oh_no_my_claudecode.models.memory import MemoryEntry


@dataclass(slots=True)
class BlastRadius:
    """Codegraph blast-radius summary for a single file.

    Fields mirror the relevant parts of
    :class:`~oh_no_my_claudecode.codegraph.models.Neighbors` so the context
    record is self-contained.
    """

    target: str
    """The file path or symbol name the blast radius was computed for."""

    target_files: list[str] = field(default_factory=list)
    """Resolved in-graph file path(s) for ``target``."""

    dependents: list[str] = field(default_factory=list)
    """Files that import the target (the blast radius)."""

    imports: list[str] = field(default_factory=list)
    """Files the target itself imports (its dependencies)."""

    tests: list[str] = field(default_factory=list)
    """Test files that exercise the target."""

    in_graph: bool = True
    """``False`` when the target was not found in the code graph at all."""

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {
            "target": self.target,
            "target_files": list(self.target_files),
            "dependents": list(self.dependents),
            "imports": list(self.imports),
            "tests": list(self.tests),
            "in_graph": self.in_graph,
        }


@dataclass(slots=True)
class MemoryHit:
    """A single relevant memory entry surfaced for the file.

    Only the fields an agent needs are carried forward; full memory detail is
    available via ``onmc memory get <id>``.
    """

    id: str
    kind: str
    title: str
    summary: str
    source_ref: str

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "summary": self.summary,
            "source_ref": self.source_ref,
        }


@dataclass(slots=True)
class AgentContext:
    """One-shot context snapshot for a file: blast radius + relevant memory.

    Produced by :func:`build_context`.  Fully serialisable via
    :meth:`to_dict`.
    """

    kind: str = "context"
    file: str = ""
    blast_radius: BlastRadius = field(default_factory=lambda: BlastRadius(target=""))
    memory: list[MemoryHit] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serialise to the ``--json`` wire shape."""
        return {
            "kind": self.kind,
            "file": self.file,
            "blast_radius": self.blast_radius.to_dict(),
            "memory": [m.to_dict() for m in self.memory],
        }


def build_context(
    file: str,
    neighbors: Neighbors,
    memory_entries: list[MemoryEntry],
    *,
    limit: int = 8,
) -> AgentContext:
    """Assemble an :class:`AgentContext` from pre-fetched graph + memory inputs.

    Parameters
    ----------
    file:
        The repo-relative or absolute file path that was queried.
    neighbors:
        The :class:`~oh_no_my_claudecode.codegraph.models.Neighbors` result for
        *file* from the code graph.  Pass ``Neighbors(target=file)`` with empty
        lists when the file is not in the graph.
    memory_entries:
        Already-ranked :class:`~oh_no_my_claudecode.models.memory.MemoryEntry`
        objects from
        :meth:`~oh_no_my_claudecode.core.service.OnmcService.search_memories`.
    limit:
        Maximum number of memory hits to include (applied after the caller has
        already done its own ranking/filtering).

    Returns
    -------
    AgentContext
        Assembled context record.  ``blast_radius.in_graph`` is ``False`` when
        ``neighbors.target_files`` is empty.
    """
    in_graph = bool(neighbors.target_files)
    blast = BlastRadius(
        target=neighbors.target,
        target_files=list(neighbors.target_files),
        dependents=list(neighbors.dependents),
        imports=list(neighbors.imports),
        tests=list(neighbors.tests),
        in_graph=in_graph,
    )

    hits: list[MemoryHit] = [
        MemoryHit(
            id=entry.id,
            kind=entry.kind.value if hasattr(entry.kind, "value") else str(entry.kind),
            title=entry.title,
            summary=entry.summary,
            source_ref=entry.source_ref,
        )
        for entry in memory_entries[:limit]
    ]

    return AgentContext(
        kind="context",
        file=file,
        blast_radius=blast,
        memory=hits,
    )
