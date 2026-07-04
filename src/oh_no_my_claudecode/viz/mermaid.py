"""Deterministic Mermaid ``graph TD`` renderers for onmc graphs.

Two pure functions turn onmc's internal graphs into Mermaid source text:

- :func:`memory_mermaid` — the memory relationship graph (memory nodes grouped
  by kind in subgraphs, ``memory_edges`` as labelled arrows).
- :func:`code_mermaid` — the code-graph blast radius of a target, reusing
  :func:`oh_no_my_claudecode.codegraph.neighbors`.

Both are **deterministic** (stable node ids, sorted iteration) and **offline**
(no network, no LLM). Node labels are escaped so Mermaid never mis-parses a
title containing quotes, brackets, or newlines. Output is plain text — Mermaid
is not a dependency, it is just a diagram grammar.
"""

from __future__ import annotations

from typing import Protocol

from oh_no_my_claudecode.codegraph import CodeGraph, build_codegraph, neighbors
from oh_no_my_claudecode.models.memory import MemoryEntry
from oh_no_my_claudecode.models.memory_edge import EdgeType, MemoryEdge

# Default cap on memory nodes so a large store still renders a legible diagram.
DEFAULT_MEMORY_LIMIT = 40

# Arrow syntax per edge type — Mermaid link styles chosen to read at a glance.
_EDGE_ARROWS: dict[EdgeType, str] = {
    EdgeType.SUPERSEDES: "==>",
    EdgeType.CONTRADICTS: "-.->",
    EdgeType.RELATES: "-->",
    EdgeType.DUPLICATE_OF: "-.->",
}
_FALLBACK_ARROW = "-->"


class _MemoryStore(Protocol):
    """Minimal read surface :func:`memory_mermaid` needs from storage.

    Structural typing keeps this module decoupled from the concrete
    :class:`~oh_no_my_claudecode.storage.sqlite.SQLiteStorage` while still being
    mypy-strict clean.
    """

    def list_memories(self) -> list[MemoryEntry]: ...

    def list_memory_edges(self) -> list[MemoryEdge]: ...


def _escape_label(text: str) -> str:
    """Escape *text* for safe use inside a Mermaid ``["..."]`` label.

    Mermaid node labels are wrapped in double quotes here; the characters that
    break parsing are double quotes (close the label early) and newlines (end
    the statement). We replace quotes with the HTML entity Mermaid renders and
    flatten whitespace so a label is always a single clean line.
    """
    collapsed = " ".join(text.split())
    escaped = collapsed.replace('"', "&quot;")
    return escaped if escaped else "(untitled)"


def _truncate(text: str, *, limit: int = 60) -> str:
    """Return *text* clipped to *limit* chars with an ellipsis when longer."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _memory_node_id(index: int) -> str:
    """Return the stable Mermaid node id for the *index*-th memory node."""
    return f"m{index}"


def _sanitize_group_id(kind_value: str) -> str:
    """Return a Mermaid-safe subgraph id derived from a memory-kind value."""
    return "grp_" + "".join(ch if ch.isalnum() else "_" for ch in kind_value)


def memory_mermaid(store: _MemoryStore, *, limit: int = DEFAULT_MEMORY_LIMIT) -> str:
    """Render the memory relationship graph as Mermaid ``graph TD`` text.

    Nodes are memory entries grouped into per-:class:`MemoryKind` subgraphs;
    edges are ``memory_edges`` rows drawn only when *both* endpoints are among
    the rendered nodes. When the store is empty, a valid single-node diagram is
    returned so downstream tools always receive parseable Mermaid.

    Parameters
    ----------
    store:
        Anything exposing ``list_memories()`` and ``list_memory_edges()``
        (the onmc SQLite storage satisfies this).
    limit:
        Maximum number of memory nodes to render (most-recently-updated first,
        matching the storage ordering). Values ``<= 0`` render nothing but the
        empty placeholder.
    """
    lines: list[str] = ["graph TD"]

    memories = store.list_memories()
    # A non-positive limit renders nothing but the empty placeholder; a positive
    # limit clips to the most-recently-updated N (storage ordering).
    memories = memories[:limit] if limit > 0 else []

    if not memories:
        lines.append('  empty["(no memories yet)"]')
        return "\n".join(lines)

    # Assign a stable id to each memory and remember which we actually render,
    # so edges to clipped-out nodes are dropped rather than dangling.
    node_id_by_memory: dict[str, str] = {}
    for index, memory in enumerate(memories):
        node_id_by_memory[memory.id] = _memory_node_id(index)

    # Group nodes by kind (sorted by kind value, then by node index) so the
    # output is deterministic regardless of store ordering quirks.
    grouped: dict[str, list[tuple[str, MemoryEntry]]] = {}
    for memory in memories:
        grouped.setdefault(memory.kind.value, []).append(
            (node_id_by_memory[memory.id], memory)
        )

    for kind_value in sorted(grouped):
        group_id = _sanitize_group_id(kind_value)
        lines.append(f'  subgraph {group_id}["{_escape_label(kind_value)}"]')
        for node_id, memory in grouped[kind_value]:
            label = _escape_label(_truncate(memory.title))
            lines.append(f'    {node_id}["{label}"]')
        lines.append("  end")

    edges = store.list_memory_edges()
    # Deduplicate identical (from, to, type) triples and sort for determinism.
    seen: set[tuple[str, str, str]] = set()
    edge_lines: list[str] = []
    for edge in edges:
        from_node = node_id_by_memory.get(edge.from_memory_id)
        to_node = node_id_by_memory.get(edge.to_memory_id)
        if from_node is None or to_node is None:
            continue
        key = (from_node, to_node, edge.edge_type.value)
        if key in seen:
            continue
        seen.add(key)
        arrow = _EDGE_ARROWS.get(edge.edge_type, _FALLBACK_ARROW)
        edge_lines.append(
            f'  {from_node} {arrow}|{_escape_label(edge.edge_type.value)}| {to_node}'
        )
    lines.extend(sorted(edge_lines))

    return "\n".join(lines)


def _file_node_id(prefix: str, path: str) -> str:
    """Return a stable Mermaid node id for a file path within a section."""
    slug = "".join(ch if ch.isalnum() else "_" for ch in path)
    return f"{prefix}_{slug}"


def code_mermaid(repo_root: object, target: str, *, graph: CodeGraph | None = None) -> str:
    """Render the code-graph blast radius of *target* as Mermaid ``graph TD``.

    Reuses :func:`oh_no_my_claudecode.codegraph.neighbors`: the target file(s)
    sit in the centre, importers/dependents flow *into* them, and the target's
    own imports flow *out*. Test files are rendered as a distinct group.

    Parameters
    ----------
    repo_root:
        Repo root path passed to :func:`build_codegraph` when *graph* is not
        supplied. Accepted as ``object`` so callers can pass a ``Path`` without
        this module importing ``pathlib`` purely for a signature.
    target:
        A repo-relative file path or a bare symbol name. Unresolved targets
        render a valid single-node placeholder diagram.
    graph:
        A pre-built :class:`CodeGraph` to reuse (skips a rebuild); when ``None``
        the graph is built from *repo_root*.
    """
    code_graph = graph if graph is not None else build_codegraph(repo_root)  # type: ignore[arg-type]
    result = neighbors(code_graph, target)

    lines: list[str] = ["graph TD"]

    if not result.target_files:
        lines.append(f'  missing["{_escape_label(target)} (not found)"]')
        return "\n".join(lines)

    # Central target files.
    target_ids: dict[str, str] = {}
    lines.append(f'  subgraph target["target: {_escape_label(target)}"]')
    for path in result.target_files:
        node_id = _file_node_id("t", path)
        target_ids[path] = node_id
        lines.append(f'    {node_id}["{_escape_label(path)}"]')
    lines.append("  end")

    # Non-test dependents (importers) → target.
    test_set = set(result.tests)
    importer_ids: dict[str, str] = {}
    plain_importers = [p for p in result.dependents if p not in test_set]
    if plain_importers:
        lines.append('  subgraph importers["imported by"]')
        for path in plain_importers:
            node_id = _file_node_id("i", path)
            importer_ids[path] = node_id
            lines.append(f'    {node_id}["{_escape_label(path)}"]')
        lines.append("  end")

    # Tests exercising the target.
    test_ids: dict[str, str] = {}
    if result.tests:
        lines.append('  subgraph tests["tests"]')
        for path in result.tests:
            node_id = _file_node_id("x", path)
            test_ids[path] = node_id
            lines.append(f'    {node_id}["{_escape_label(path)}"]')
        lines.append("  end")

    # Target's own imports.
    import_ids: dict[str, str] = {}
    if result.imports:
        lines.append('  subgraph imports["imports"]')
        for path in result.imports:
            node_id = _file_node_id("d", path)
            import_ids[path] = node_id
            lines.append(f'    {node_id}["{_escape_label(path)}"]')
        lines.append("  end")

    # Edges (sorted for determinism). Importers/tests point *into* the target;
    # the target points *out* to its imports.
    edge_lines: list[str] = []
    for path in result.target_files:
        tid = target_ids[path]
        for imp_path in plain_importers:
            edge_lines.append(f"  {importer_ids[imp_path]} --> {tid}")
        for test_path in result.tests:
            edge_lines.append(f"  {test_ids[test_path]} -.-> {tid}")
        for dep_path in result.imports:
            edge_lines.append(f"  {tid} --> {import_ids[dep_path]}")
    lines.extend(sorted(edge_lines))

    return "\n".join(lines)
