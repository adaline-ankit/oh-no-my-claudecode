"""Pure query API for the code index.

All functions in this module are read-only — they never modify the index.
This is the interface a later hybrid-retrieval PR will consume.

Functions
---------
get_symbol(store, name)
    Return all chunks defining *name*.

neighbors(store, chunk_id)
    Return all chunks directly adjacent to *chunk_id* via any edge.

callers(store, symbol)
    Return chunks that call *symbol* (callee edges pointing to *symbol*).

callees(store, symbol)
    Return chunks called by *symbol* (callee edges leaving *symbol*).

chunks_for_file(store, path)
    Return all chunks for a repo-relative *path*, ordered by start_line.

search_symbols(store, substr)
    Return chunks whose symbol name contains *substr* (case-insensitive).

stats(store)
    Return current :class:`~oh_no_my_claudecode.codeindex.models.IndexStats`.
"""

from __future__ import annotations

from oh_no_my_claudecode.codeindex.models import IndexChunk, IndexEdge, IndexStats
from oh_no_my_claudecode.codeindex.store import CodeIndexStore


def get_symbol(store: CodeIndexStore, name: str) -> list[IndexChunk]:
    """Return all chunks that define *name*.

    Performs an exact-match on the ``symbol`` column.  A symbol may be defined
    in multiple files (e.g. two ``setup`` functions in different modules).

    Parameters
    ----------
    store:
        Open :class:`CodeIndexStore`.
    name:
        Exact symbol name to look up (e.g. ``"invalidate_cache"`` or
        ``"CacheManager.clear"``).

    Returns
    -------
    list[IndexChunk]
        Chunks defining *name*, sorted by path then start_line.
        Empty list when the symbol is not found.
    """
    return store.get_chunks_for_symbol(name)


def neighbors(store: CodeIndexStore, chunk_id: str) -> list[IndexChunk]:
    """Return all chunks directly adjacent to *chunk_id* via any edge.

    Resolves the chunk's (path, symbol), queries both outgoing and incoming
    edges, then resolves each adjacent (path, symbol) to its current chunk.
    Dangling edges (pointing to symbols no longer in the index) are silently
    skipped.

    Parameters
    ----------
    store:
        Open :class:`CodeIndexStore`.
    chunk_id:
        ID of the source chunk.

    Returns
    -------
    list[IndexChunk]
        Adjacent chunks, deduplicated, sorted by path then start_line.
        Empty when *chunk_id* is not found or has no edges.
    """
    chunk = store.get_chunk(chunk_id)
    if chunk is None:
        return []

    outgoing = store.get_outgoing_edges(chunk.path, chunk.symbol)
    incoming = store.get_incoming_edges(chunk.path, chunk.symbol)

    adjacent_symbols: set[tuple[str, str]] = set()
    for edge in outgoing + incoming:
        if (edge.dst_path, edge.dst_symbol) != (chunk.path, chunk.symbol):
            adjacent_symbols.add((edge.dst_path, edge.dst_symbol))
        if (edge.src_path, edge.src_symbol) != (chunk.path, chunk.symbol):
            adjacent_symbols.add((edge.src_path, edge.src_symbol))

    result: list[IndexChunk] = []
    seen_ids: set[str] = set()
    for adj_path, adj_symbol in sorted(adjacent_symbols):
        adj_chunks = store.get_chunks_for_symbol(adj_symbol)
        for adj_chunk in adj_chunks:
            if adj_chunk.path == adj_path and adj_chunk.chunk_id not in seen_ids:
                seen_ids.add(adj_chunk.chunk_id)
                result.append(adj_chunk)

    result.sort(key=lambda c: (c.path, c.start_line))
    return result


def callers(store: CodeIndexStore, symbol: str) -> list[IndexChunk]:
    """Return chunks that call *symbol* (callee edges pointing to *symbol*).

    Finds all (path, symbol) pairs that define *symbol*, then collects all
    callee edges pointing to each definition.  Resolves src (path, symbol)
    to chunks.

    Parameters
    ----------
    store:
        Open :class:`CodeIndexStore`.
    symbol:
        Symbol name (e.g. ``"invalidate_cache"`` or ``"MyClass.method"``).

    Returns
    -------
    list[IndexChunk]
        Chunks that call *symbol*, sorted by path then start_line.
    """
    definitions = store.get_chunks_for_symbol(symbol)
    if not definitions:
        return []

    caller_chunks: list[IndexChunk] = []
    seen_ids: set[str] = set()

    for defn in definitions:
        edges = store.get_callers(defn.path, defn.symbol)
        for edge in edges:
            src_chunks = store.get_chunks_for_symbol(edge.src_symbol)
            for src_chunk in src_chunks:
                if src_chunk.path == edge.src_path and src_chunk.chunk_id not in seen_ids:
                    seen_ids.add(src_chunk.chunk_id)
                    caller_chunks.append(src_chunk)

    caller_chunks.sort(key=lambda c: (c.path, c.start_line))
    return caller_chunks


def callees(store: CodeIndexStore, symbol: str) -> list[IndexChunk]:
    """Return chunks called by *symbol* (callee edges leaving *symbol*).

    Parameters
    ----------
    store:
        Open :class:`CodeIndexStore`.
    symbol:
        Symbol name (e.g. ``"refresh_worker"``).

    Returns
    -------
    list[IndexChunk]
        Chunks that *symbol* calls, sorted by path then start_line.
    """
    definitions = store.get_chunks_for_symbol(symbol)
    if not definitions:
        return []

    callee_chunks: list[IndexChunk] = []
    seen_ids: set[str] = set()

    for defn in definitions:
        edges = store.get_callees(defn.path, defn.symbol)
        for edge in edges:
            dst_chunks = store.get_chunks_for_symbol(edge.dst_symbol)
            for dst_chunk in dst_chunks:
                if dst_chunk.path == edge.dst_path and dst_chunk.chunk_id not in seen_ids:
                    seen_ids.add(dst_chunk.chunk_id)
                    callee_chunks.append(dst_chunk)

    callee_chunks.sort(key=lambda c: (c.path, c.start_line))
    return callee_chunks


def chunks_for_file(store: CodeIndexStore, path: str) -> list[IndexChunk]:
    """Return all chunks for *path*, ordered by start_line.

    Parameters
    ----------
    store:
        Open :class:`CodeIndexStore`.
    path:
        Repo-relative POSIX path (e.g. ``"src/cache.py"``).

    Returns
    -------
    list[IndexChunk]
        Chunks in source order.  Empty when the path is not in the index.
    """
    return store.get_chunks_for_path(path)


def search_symbols(store: CodeIndexStore, substr: str) -> list[IndexChunk]:
    """Return chunks whose symbol name contains *substr* (case-insensitive).

    Excludes the ``"__module__"`` file-level sentinel from results to keep
    output symbol-focused.

    Parameters
    ----------
    store:
        Open :class:`CodeIndexStore`.
    substr:
        Substring to search for in symbol names.

    Returns
    -------
    list[IndexChunk]
        Matching chunks sorted by path then start_line.  Empty on no match.
    """
    results = store.search_chunks_by_symbol_substr(substr)
    return [c for c in results if c.symbol != "__module__"]


def stats(store: CodeIndexStore) -> IndexStats:
    """Return current index statistics.

    Parameters
    ----------
    store:
        Open :class:`CodeIndexStore`.

    Returns
    -------
    IndexStats
        Counts, language breakdown, commit SHA, and build timestamp.
    """
    return store.get_stats()


def edges_for_chunk(store: CodeIndexStore, chunk_id: str) -> list[IndexEdge]:
    """Return all edges (outgoing + incoming) for *chunk_id*.

    Parameters
    ----------
    store:
        Open :class:`CodeIndexStore`.
    chunk_id:
        ID of the chunk.

    Returns
    -------
    list[IndexEdge]
        All edges involving this chunk.  Empty when not found.
    """
    chunk = store.get_chunk(chunk_id)
    if chunk is None:
        return []
    outgoing = store.get_outgoing_edges(chunk.path, chunk.symbol)
    incoming = store.get_incoming_edges(chunk.path, chunk.symbol)
    seen: set[tuple[str, str, str, str, str]] = set()
    result: list[IndexEdge] = []
    for edge in outgoing + incoming:
        key = (edge.src_path, edge.src_symbol, edge.dst_path, edge.dst_symbol, edge.edge_type)
        if key not in seen:
            seen.add(key)
            result.append(edge)
    return result
