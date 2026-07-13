"""Structural repo code graph — tiny, smart context for agents.

Deterministic, offline, stdlib-only (``ast``) structural index of a Python
repository.  See :mod:`oh_no_my_claudecode.codegraph.builder` for the entry
points, :mod:`oh_no_my_claudecode.codegraph.models` for the dataclasses, and
:mod:`oh_no_my_claudecode.codegraph.coverage` for the coverage report.
"""

from __future__ import annotations

from oh_no_my_claudecode.codegraph.builder import (
    build_codegraph,
    context_files,
    neighbors,
)
from oh_no_my_claudecode.codegraph.coverage import (
    CoverageReport,
    codegraph_coverage,
    emit_coverage_warning,
)
from oh_no_my_claudecode.codegraph.models import (
    CodeGraph,
    ContextSelection,
    GraphNode,
    Neighbors,
    Symbol,
    SymbolKind,
)

__all__ = [
    "CodeGraph",
    "ContextSelection",
    "CoverageReport",
    "GraphNode",
    "Neighbors",
    "Symbol",
    "SymbolKind",
    "build_codegraph",
    "codegraph_coverage",
    "context_files",
    "emit_coverage_warning",
    "neighbors",
]
