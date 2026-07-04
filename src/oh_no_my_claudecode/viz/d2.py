"""Deterministic D2 diagram renderers for onmc graphs.

Two pure functions turn onmc's internal graphs into D2 (terrastruct.com/d2)
source text:

- :func:`memory_d2` -- the memory relationship graph (memory nodes grouped
  into D2 containers by kind, ``memory_edges`` as labelled arrows).
- :func:`code_d2` -- the code-graph blast radius of a target, reusing
  :func:`oh_no_my_claudecode.codegraph.neighbors`.

Both are **deterministic** (stable node ids, sorted iteration), **offline**
(no network, no LLM), and produce **pure stdlib string output** -- D2 is not
a dependency, it is just a diagram grammar.

D2 syntax used here::

    direction: right
    group: {
      node_id: {
        label: "display label"
        shape: rectangle
      }
    }
    from_id -> to_id: edge label
"""

from __future__ import annotations

from typing import Protocol

from oh_no_my_claudecode.codegraph import CodeGraph, build_codegraph, neighbors
from oh_no_my_claudecode.models.memory import MemoryEntry
from oh_no_my_claudecode.models.memory_edge import EdgeType, MemoryEdge

# Re-export so importers share the same default.
DEFAULT_MEMORY_LIMIT = 40

# D2 edge label per edge type.
_EDGE_LABELS: dict[EdgeType, str] = {
    EdgeType.SUPERSEDES: "supersedes",
    EdgeType.CONTRADICTS: "contradicts",
    EdgeType.RELATES: "relates",
    EdgeType.DUPLICATE_OF: "duplicate_of",
}
_FALLBACK_LABEL = "relates"

# Unicode left/right double quotation marks used to replace ASCII straight
# quotes in label text so the D2 double-quoted string is never terminated early.
_LDQUO = "“"  # left double quotation mark: "
_RDQUO = "”"  # right double quotation mark: "


class _MemoryStore(Protocol):
    """Minimal read surface :func:`memory_d2` needs from storage."""

    def list_memories(self) -> list[MemoryEntry]: ...

    def list_memory_edges(self) -> list[MemoryEdge]: ...


def _escape_d2_label(text: str) -> str:
    """Escape *text* for safe embedding inside a D2 double-quoted string.

    D2 label values are wrapped in ``"..."`` here.  Characters that break
    parsing are double quotes (close the label early) and raw newlines (end
    the statement).  ASCII straight double-quotes are replaced with Unicode
    typographic quotation marks which read well and are unambiguous to D2.
    Whitespace is collapsed to a single space so a label is always one line.
    """
    collapsed = " ".join(text.split())
    # Replace ASCII straight double-quote with Unicode curly quotes.
    # We use replace() twice: left-quote before a word, right-quote after.
    # A simple global replace to the right-quote form is safe here because
    # we are not trying to pair them -- any curly quote avoids D2 breakage.
    escaped = collapsed.replace('"', _LDQUO)
    return escaped if escaped else "(untitled)"


def _truncate(text: str, *, limit: int = 60) -> str:
    """Return *text* clipped to *limit* chars with an ellipsis when longer."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _memory_node_id(index: int) -> str:
    """Return the stable D2 node id for the *index*-th memory node."""
    return f"m{index}"


def _sanitize_d2_id(value: str) -> str:
    """Return a D2-safe container/node id from an arbitrary string.

    D2 identifiers may contain alphanumerics and underscores.  Other chars
    are replaced with underscores, and a ``grp_`` prefix avoids leading digits.
    """
    return "grp_" + "".join(ch if ch.isalnum() else "_" for ch in value)


def _file_node_id(prefix: str, path: str) -> str:
    """Return a stable D2 node id for a file path within a container."""
    slug = "".join(ch if ch.isalnum() else "_" for ch in path)
    return f"{prefix}_{slug}"


def memory_d2(store: _MemoryStore, *, limit: int = DEFAULT_MEMORY_LIMIT) -> str:
    """Render the memory relationship graph as D2 diagram text.

    Nodes are memory entries grouped into per-:class:`MemoryKind` containers;
    edges are ``memory_edges`` rows drawn only when *both* endpoints are among
    the rendered nodes.  When the store is empty, a valid single-node diagram
    is returned so downstream tools always receive parseable D2.

    Parameters
    ----------
    store:
        Anything exposing ``list_memories()`` and ``list_memory_edges()``
        (the onmc SQLite storage satisfies this).
    limit:
        Maximum number of memory nodes to render (most-recently-updated first,
        matching the storage ordering).  Values ``<= 0`` render nothing but
        the empty placeholder.
    """
    lines: list[str] = ["direction: right", ""]

    memories = store.list_memories()
    memories = memories[:limit] if limit > 0 else []

    if not memories:
        lines.append("empty: {")
        lines.append('  label: "(no memories yet)"')
        lines.append("  shape: rectangle")
        lines.append("}")
        return "\n".join(lines)

    # Assign a stable id to each memory.
    node_id_by_memory: dict[str, str] = {}
    for index, memory in enumerate(memories):
        node_id_by_memory[memory.id] = _memory_node_id(index)

    # Group nodes by kind (sorted by kind value, then by node index).
    grouped: dict[str, list[tuple[str, MemoryEntry]]] = {}
    for memory in memories:
        grouped.setdefault(memory.kind.value, []).append(
            (node_id_by_memory[memory.id], memory)
        )

    for kind_value in sorted(grouped):
        container_id = _sanitize_d2_id(kind_value)
        label = _escape_d2_label(kind_value)
        lines.append(f"{container_id}: {{")
        lines.append(f'  label: "{label}"')
        for node_id, memory in grouped[kind_value]:
            mem_label = _escape_d2_label(_truncate(memory.title))
            lines.append(f"  {node_id}: {{")
            lines.append(f'    label: "{mem_label}"')
            lines.append("    shape: rectangle")
            lines.append("  }")
        lines.append("}")
        lines.append("")

    # Edges: sorted for determinism, deduplicated on (from, to, type).
    edges = store.list_memory_edges()
    seen: set[tuple[str, str, str]] = set()
    edge_lines: list[str] = []

    # Build reverse map: node_id -> memory, for container lookup.
    node_to_kind: dict[str, str] = {
        node_id_by_memory[m.id]: m.kind.value for m in memories
    }

    for edge in edges:
        from_node = node_id_by_memory.get(edge.from_memory_id)
        to_node = node_id_by_memory.get(edge.to_memory_id)
        if from_node is None or to_node is None:
            continue
        key = (from_node, to_node, edge.edge_type.value)
        if key in seen:
            continue
        seen.add(key)
        from_container = _sanitize_d2_id(node_to_kind[from_node])
        to_container = _sanitize_d2_id(node_to_kind[to_node])
        edge_label = _EDGE_LABELS.get(edge.edge_type, _FALLBACK_LABEL)
        edge_lines.append(
            f"{from_container}.{from_node} -> {to_container}.{to_node}: {edge_label}"
        )
    lines.extend(sorted(edge_lines))

    return "\n".join(lines)


def code_d2(repo_root: object, target: str, *, graph: CodeGraph | None = None) -> str:
    """Render the code-graph blast radius of *target* as D2 diagram text.

    Reuses :func:`oh_no_my_claudecode.codegraph.neighbors`: the target file(s)
    sit in the centre, importers/dependents flow into them, and the target's
    own imports flow out.  Test files are rendered as a distinct container.

    Parameters
    ----------
    repo_root:
        Repo root path passed to :func:`build_codegraph` when *graph* is not
        supplied.  Accepted as ``object`` so callers can pass a ``Path``
        without this module importing ``pathlib`` purely for a signature.
    target:
        A repo-relative file path or a bare symbol name.  Unresolved targets
        render a valid single-node placeholder diagram.
    graph:
        A pre-built :class:`CodeGraph` to reuse (skips a rebuild); when
        ``None`` the graph is built from *repo_root*.
    """
    code_graph = graph if graph is not None else build_codegraph(repo_root)  # type: ignore[arg-type]
    result = neighbors(code_graph, target)

    lines: list[str] = ["direction: right", ""]

    if not result.target_files:
        missing_label = _escape_d2_label(f"{target} (not found)")
        lines.append("missing: {")
        lines.append(f'  label: "{missing_label}"')
        lines.append("  shape: rectangle")
        lines.append("}")
        return "\n".join(lines)

    # Central target files.
    target_ids: dict[str, str] = {}
    target_label = _escape_d2_label(target)
    lines.append("target: {")
    lines.append(f'  label: "target: {target_label}"')
    for path in result.target_files:
        node_id = _file_node_id("t", path)
        target_ids[path] = node_id
        path_label = _escape_d2_label(path)
        lines.append(f"  {node_id}: {{")
        lines.append(f'    label: "{path_label}"')
        lines.append("    shape: rectangle")
        lines.append("  }")
    lines.append("}")
    lines.append("")

    # Non-test dependents (importers) -> target.
    test_set = set(result.tests)
    importer_ids: dict[str, str] = {}
    plain_importers = [p for p in result.dependents if p not in test_set]
    if plain_importers:
        lines.append("importers: {")
        lines.append('  label: "imported by"')
        for path in plain_importers:
            node_id = _file_node_id("i", path)
            importer_ids[path] = node_id
            path_label = _escape_d2_label(path)
            lines.append(f"  {node_id}: {{")
            lines.append(f'    label: "{path_label}"')
            lines.append("    shape: rectangle")
            lines.append("  }")
        lines.append("}")
        lines.append("")

    # Tests exercising the target.
    test_ids: dict[str, str] = {}
    if result.tests:
        lines.append("tests: {")
        lines.append('  label: "tests"')
        for path in result.tests:
            node_id = _file_node_id("x", path)
            test_ids[path] = node_id
            path_label = _escape_d2_label(path)
            lines.append(f"  {node_id}: {{")
            lines.append(f'    label: "{path_label}"')
            lines.append("    shape: rectangle")
            lines.append("  }")
        lines.append("}")
        lines.append("")

    # Target's own imports.
    import_ids: dict[str, str] = {}
    if result.imports:
        lines.append("imports: {")
        lines.append('  label: "imports"')
        for path in result.imports:
            node_id = _file_node_id("d", path)
            import_ids[path] = node_id
            path_label = _escape_d2_label(path)
            lines.append(f"  {node_id}: {{")
            lines.append(f'    label: "{path_label}"')
            lines.append("    shape: rectangle")
            lines.append("  }")
        lines.append("}")
        lines.append("")

    # Edges (sorted for determinism).
    edge_lines: list[str] = []
    for path in result.target_files:
        tid = target_ids[path]
        for imp_path in plain_importers:
            edge_lines.append(f"importers.{importer_ids[imp_path]} -> target.{tid}")
        for test_path in result.tests:
            edge_lines.append(f"tests.{test_ids[test_path]} -> target.{tid}: tests")
        for dep_path in result.imports:
            edge_lines.append(f"target.{tid} -> imports.{import_ids[dep_path]}")
    lines.extend(sorted(edge_lines))

    return "\n".join(lines)
