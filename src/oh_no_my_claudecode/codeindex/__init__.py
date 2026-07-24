"""Incremental code-intelligence index keyed by git blob SHA.

Offline, deterministic, stdlib-first (tree-sitter optional / import-guarded).
No LLM calls.

Entry points
------------
:func:`build`
    Atomic full rebuild of the index for a repository root.
:func:`update`
    Incremental one-file update; no-ops when blob SHA is unchanged.
:mod:`~oh_no_my_claudecode.codeindex.query`
    Pure query API: ``get_symbol``, ``neighbors``, ``callers``, ``callees``,
    ``chunks_for_file``, ``search_symbols``, ``stats``.
"""

from __future__ import annotations

from oh_no_my_claudecode.codeindex.builder import build, update
from oh_no_my_claudecode.codeindex.models import (
    ChunkKind,
    EdgeType,
    IndexChunk,
    IndexEdge,
    IndexStats,
    Language,
)
from oh_no_my_claudecode.codeindex.query import (
    callees,
    callers,
    chunks_for_file,
    edges_for_chunk,
    get_symbol,
    neighbors,
    search_symbols,
    stats,
)
from oh_no_my_claudecode.codeindex.store import CodeIndexStore, open_store

__all__ = [
    # builder
    "build",
    "update",
    # models
    "ChunkKind",
    "EdgeType",
    "IndexChunk",
    "IndexEdge",
    "IndexStats",
    "Language",
    # query
    "callers",
    "callees",
    "chunks_for_file",
    "edges_for_chunk",
    "get_symbol",
    "neighbors",
    "search_symbols",
    "stats",
    # store
    "CodeIndexStore",
    "open_store",
]
