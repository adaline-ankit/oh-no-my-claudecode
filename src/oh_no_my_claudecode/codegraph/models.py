"""Dataclasses for the structural repo code graph.

A :class:`CodeGraph` is a lightweight, deterministic structural index of a
Python repository: top-level symbols per file, import edges between modules,
the reverse blast-radius (which files depend on a given module), and a mapping
from test files to the modules they exercise.

The graph is intentionally *small* — it carries enough structure to answer
"what is the blast radius of this file?" and "which files matter for this
goal?" without ever loading whole-file source into an agent's context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SymbolKind = Literal["func", "class"]


@dataclass(slots=True, frozen=True)
class Symbol:
    """A single top-level definition discovered in a Python file.

    Fields
    ------
    name:
        The symbol's identifier (function or class name).
    kind:
        ``"func"`` for ``def``/``async def`` or ``"class"`` for ``class``.
    file:
        Repo-relative POSIX path of the file the symbol is defined in.
    lineno:
        1-based line number of the definition.
    """

    name: str
    kind: SymbolKind
    file: str
    lineno: int


@dataclass(slots=True)
class GraphNode:
    """Per-file node in the code graph.

    Fields
    ------
    file:
        Repo-relative POSIX path of the file.
    symbols:
        Top-level symbols defined in the file, in source order.
    imports:
        Repo-relative paths of in-repo modules this file imports, sorted.
    is_test:
        Whether the file is a test file (``tests/test_*.py`` etc.).
    """

    file: str
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    is_test: bool = False


@dataclass(slots=True)
class CodeGraph:
    """A structural index of a Python repository.

    Fields
    ------
    nodes:
        Mapping of repo-relative file path → :class:`GraphNode`.
    symbols:
        Flat list of every :class:`Symbol` discovered, in deterministic order
        (by file, then line number).
    symbols_by_name:
        Mapping of bare symbol name → the files that define it.  A name can map
        to multiple files (e.g. two ``setup`` functions in different modules).
    dependents:
        Reverse import edges — for each file, the set of files that import it.
        This is the *blast radius*: change ``X`` and every file in
        ``dependents[X]`` is potentially affected.
    file_tests:
        Mapping of source-file path → the test files that import it (directly).
    file_count:
        Total number of Python files indexed.
    """

    nodes: dict[str, GraphNode] = field(default_factory=dict)
    symbols: list[Symbol] = field(default_factory=list)
    symbols_by_name: dict[str, list[str]] = field(default_factory=dict)
    dependents: dict[str, list[str]] = field(default_factory=dict)
    file_tests: dict[str, list[str]] = field(default_factory=dict)
    file_count: int = 0

    def to_dict(self) -> dict[str, object]:
        """Serialise the graph to a plain JSON-safe dict (deterministic order)."""
        return {
            "file_count": self.file_count,
            "nodes": {
                path: {
                    "file": node.file,
                    "is_test": node.is_test,
                    "imports": list(node.imports),
                    "symbols": [
                        {
                            "name": sym.name,
                            "kind": sym.kind,
                            "file": sym.file,
                            "lineno": sym.lineno,
                        }
                        for sym in node.symbols
                    ],
                }
                for path, node in sorted(self.nodes.items())
            },
            "dependents": {
                path: list(deps) for path, deps in sorted(self.dependents.items())
            },
            "file_tests": {
                path: list(tests) for path, tests in sorted(self.file_tests.items())
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> CodeGraph:
        """Reconstruct a :class:`CodeGraph` from :meth:`to_dict` output.

        Tolerant of missing keys so a partially-written or older cache file
        never raises — absent sections simply yield empty mappings.
        """
        raw_nodes = _as_dict(payload.get("nodes"))
        nodes: dict[str, GraphNode] = {}
        symbols: list[Symbol] = []
        symbols_by_name: dict[str, list[str]] = {}

        for path in sorted(raw_nodes):
            raw_node = _as_dict(raw_nodes[path])
            node_symbols: list[Symbol] = []
            for raw_sym in _as_list(raw_node.get("symbols")):
                sym_map = _as_dict(raw_sym)
                kind = sym_map.get("kind")
                if kind not in ("func", "class"):
                    continue
                symbol = Symbol(
                    name=str(sym_map.get("name", "")),
                    kind=kind,
                    file=str(sym_map.get("file", path)),
                    lineno=_as_int(sym_map.get("lineno")),
                )
                node_symbols.append(symbol)
                symbols.append(symbol)
                symbols_by_name.setdefault(symbol.name, [])
                if symbol.file not in symbols_by_name[symbol.name]:
                    symbols_by_name[symbol.name].append(symbol.file)
            nodes[path] = GraphNode(
                file=str(raw_node.get("file", path)),
                symbols=node_symbols,
                imports=[str(item) for item in _as_list(raw_node.get("imports"))],
                is_test=bool(raw_node.get("is_test", False)),
            )

        dependents = {
            str(path): [str(dep) for dep in _as_list(deps)]
            for path, deps in _as_dict(payload.get("dependents")).items()
        }
        file_tests = {
            str(path): [str(test) for test in _as_list(tests)]
            for path, tests in _as_dict(payload.get("file_tests")).items()
        }
        return cls(
            nodes=nodes,
            symbols=symbols,
            symbols_by_name=symbols_by_name,
            dependents=dependents,
            file_tests=file_tests,
            file_count=_as_int(payload.get("file_count"), default=len(nodes)),
        )


@dataclass(slots=True)
class Neighbors:
    """The blast radius of a file or symbol.

    Fields
    ------
    target:
        The resolved file path (or symbol name) the neighbours were computed for.
    target_files:
        The file(s) the target resolved to.  A file target resolves to itself;
        a symbol target resolves to every file defining that symbol.
    importers:
        Files that directly import any of the target files (same as dependents
        for a file target).
    dependents:
        Reverse-dependency files (the blast radius); identical to *importers*
        today but kept distinct for forward-compatibility / clarity.
    tests:
        Related test files (tests that import any target file).
    imports:
        Files the target files import (their own dependencies).
    """

    target: str
    target_files: list[str] = field(default_factory=list)
    importers: list[str] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {
            "target": self.target,
            "target_files": list(self.target_files),
            "importers": list(self.importers),
            "dependents": list(self.dependents),
            "tests": list(self.tests),
            "imports": list(self.imports),
        }


@dataclass(slots=True)
class ContextSelection:
    """A bounded set of files relevant to a goal.

    Fields
    ------
    goal:
        The original goal string.
    files:
        Selected repo-relative file paths, most-relevant first, bounded by the
        caller's budget.
    budget:
        The maximum number of files requested.
    matched_terms:
        Goal tokens that matched at least one file or symbol — surfaced so the
        caller can see *why* files were chosen.
    """

    goal: str
    files: list[str] = field(default_factory=list)
    budget: int = 0
    matched_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {
            "goal": self.goal,
            "budget": self.budget,
            "files": list(self.files),
            "matched_terms": list(self.matched_terms),
        }


def _as_dict(value: object) -> dict[str, object]:
    """Return *value* as a dict, or an empty dict if it is not one."""
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    """Return *value* as a list, or an empty list if it is not one."""
    return value if isinstance(value, list) else []


def _as_int(value: object, *, default: int = 0) -> int:
    """Coerce *value* to an int, falling back to *default* on any failure."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default
