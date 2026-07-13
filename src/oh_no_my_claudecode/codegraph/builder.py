"""Deterministic, offline builder for the structural repo code graph.

Walks every ``*.py`` file under a repo root using the standard-library
:mod:`ast` module (no third-party parsers required) and assembles a
:class:`~oh_no_my_claudecode.codegraph.models.CodeGraph`:

- top-level ``def`` / ``async def`` / ``class`` symbols per file,
- in-repo import edges (resolved from ``import`` / ``from ... import``),
- the reverse blast radius (which files depend on each module), and
- a test-file → source-file mapping derived from test imports.

**Optional multi-language reach.**  When the optional ``tree-sitter`` extra is
installed (``pip install oh-no-my-claudecode[treesitter]``), the builder *also*
indexes JavaScript, TypeScript, Go, Rust, and Java files via
:mod:`~oh_no_my_claudecode.codegraph.treesitter_ext`, mapping their top-level
symbols onto the same :class:`~oh_no_my_claudecode.codegraph.models.Symbol`
model and resolving JS/TS relative import edges.  When tree-sitter is **not**
installed, the builder behaves exactly as the pure-Python path did — only
``*.py`` files are discovered and indexed (zero regression).

Everything is bounded and deterministic: files are visited in sorted order,
``.venv`` / ``.git`` / ``__pycache__`` and friends are skipped, and unparsable
files are recorded as empty nodes rather than raising.
"""

from __future__ import annotations

import ast
import os
from collections.abc import Callable
from pathlib import Path

from oh_no_my_claudecode.codegraph import treesitter_ext
from oh_no_my_claudecode.codegraph.models import (
    CodeGraph,
    ContextSelection,
    GraphNode,
    Neighbors,
    Symbol,
    SymbolKind,
)
from oh_no_my_claudecode.core.repo import is_test_path, relative_path
from oh_no_my_claudecode.utils.text import tokenize, unique_preserve

# Directories never worth walking — vendored deps, VCS, caches, build output.
_EXCLUDE_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".onmc",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        ".tox",
        "build",
        "dist",
        ".eggs",
        "site-packages",
    }
)

# Hard cap on files indexed so a giant monorepo can never run unbounded.
_MAX_FILES = 5000
# Default ceiling for context_files selection.
_DEFAULT_CONTEXT_BUDGET = 8


def build_codegraph(
    repo_root: Path,
    *,
    max_files: int = _MAX_FILES,
    _warn: bool = False,
) -> CodeGraph:
    """Build a :class:`CodeGraph` for the source files under *repo_root*.

    Always indexes ``*.py`` files via :mod:`ast`.  When the optional
    ``tree-sitter`` extra is installed, *also* indexes JS/TS/Go/Rust/Java files;
    when it is not, only ``*.py`` files are discovered — identical to the
    original pure-Python behaviour.

    **Coverage warning (opt-in only).**  When ``_warn=True``, a one-line
    coverage summary is printed to *stderr* and a prominent warning is emitted
    when a meaningful number of files could not be indexed because the
    ``tree-sitter`` extra is absent.  The default is ``False`` so internal
    callers (``pack``, ``context``, ``mission``, …) stay silent — only the
    user-facing ``onmc codegraph build`` command opts in.

    Pure read — walks the filesystem, never writes.  Deterministic: the same
    tree always yields the same graph (sorted traversal, sorted edges).

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root.
    max_files:
        Hard cap on the number of source files indexed (defaults to 5000).
    _warn:
        When ``True``, print a coverage summary and a warning to *stderr* if
        non-Python files are present but not indexed.  Defaults to ``False``
        so library/internal callers produce no output.
    """
    repo_root = repo_root.resolve()
    source_files = _discover_source_files(repo_root, max_files=max_files)

    # First pass: parse each file into a node + build a module→path index so
    # Python imports can be resolved to in-repo files.
    nodes: dict[str, GraphNode] = {}
    module_index: dict[str, str] = {}
    for rel_path in source_files:
        node = _parse_file(repo_root / rel_path, rel_path)
        nodes[rel_path] = node
        if _is_python(rel_path):
            for module_name in _module_names_for(rel_path):
                # First definition wins for a given module name (deterministic
                # via sorted files), keeping resolution stable.
                module_index.setdefault(module_name, rel_path)

    # Second pass: resolve imports to in-repo file paths.  Python uses the
    # module index; JS/TS uses relative-specifier resolution (tree-sitter).
    indexed = set(source_files)
    dependents: dict[str, set[str]] = {rel_path: set() for rel_path in source_files}
    file_tests: dict[str, set[str]] = {}
    for rel_path in source_files:
        node = nodes[rel_path]
        if _is_python(rel_path):
            raw_imports = _raw_imports(repo_root / rel_path, rel_path)
            resolved = sorted(
                {
                    target
                    for raw in raw_imports
                    if (target := module_index.get(raw)) is not None and target != rel_path
                }
            )
        else:
            source = _read_bytes(repo_root / rel_path)
            resolved = sorted(
                {
                    target
                    for target in treesitter_ext.extract_import_targets(rel_path, source)
                    if target in indexed and target != rel_path
                }
            )
        node.imports = resolved
        for target in resolved:
            dependents[target].add(rel_path)
            if node.is_test:
                file_tests.setdefault(target, set()).add(rel_path)

    # Flatten symbols + name index in deterministic order.
    symbols: list[Symbol] = []
    symbols_by_name: dict[str, list[str]] = {}
    for rel_path in source_files:
        for symbol in nodes[rel_path].symbols:
            symbols.append(symbol)
            symbols_by_name.setdefault(symbol.name, [])
            if symbol.file not in symbols_by_name[symbol.name]:
                symbols_by_name[symbol.name].append(symbol.file)

    graph = CodeGraph(
        nodes=nodes,
        symbols=symbols,
        symbols_by_name=symbols_by_name,
        dependents={path: sorted(deps) for path, deps in sorted(dependents.items())},
        file_tests={path: sorted(tests) for path, tests in sorted(file_tests.items())},
        file_count=len(source_files),
    )

    if _warn:
        from oh_no_my_claudecode.codegraph.coverage import (  # noqa: PLC0415
            codegraph_coverage,
            emit_coverage_warning,
        )

        report = codegraph_coverage(repo_root, graph)
        emit_coverage_warning(report)

    return graph


def neighbors(graph: CodeGraph, target: str) -> Neighbors:
    """Return the blast radius of a file or symbol *target*.

    *target* may be a repo-relative file path or a bare symbol name.  A file
    target resolves to itself; a symbol target resolves to every file that
    defines that symbol.  The result lists the importers / dependents of the
    target file(s), the tests that exercise them, and their own imports.

    Returns an empty :class:`Neighbors` (no target files) when *target* cannot
    be resolved — never raises.
    """
    target_files = _resolve_target(graph, target)

    importers: set[str] = set()
    tests: set[str] = set()
    imports: set[str] = set()
    for file in target_files:
        importers.update(graph.dependents.get(file, []))
        tests.update(graph.file_tests.get(file, []))
        node = graph.nodes.get(file)
        if node is not None:
            imports.update(node.imports)

    # A direct test importer is also a dependent; surface it in both lists.
    dependents = importers | tests
    return Neighbors(
        target=target,
        target_files=sorted(target_files),
        importers=sorted(importers),
        dependents=sorted(dependents),
        tests=sorted(tests),
        imports=sorted(imports - set(target_files)),
    )


def context_files(
    graph: CodeGraph,
    goal: str,
    *,
    budget: int = _DEFAULT_CONTEXT_BUDGET,
) -> ContextSelection:
    """Select a small, bounded set of files relevant to *goal*.

    Tokenises the goal and scores every file by how strongly its path and its
    symbol names match those tokens.  Returns at most *budget* files, sorted by
    descending relevance (ties broken by path for determinism).  Files matched
    via a symbol pull in that symbol's importers/tests too — but the overall
    result is always capped at *budget* so the context stays tiny.

    Returns an empty selection (with matched terms) when nothing matches.
    """
    effective_budget = max(1, budget)
    terms = unique_preserve(tokenize(goal))
    term_set = set(terms)
    matched_terms: set[str] = set()

    if not term_set:
        return ContextSelection(goal=goal, files=[], budget=effective_budget, matched_terms=[])

    scores: dict[str, int] = {}
    for path, node in graph.nodes.items():
        path_tokens = set(tokenize(path))
        symbol_tokens = {tok for sym in node.symbols for tok in tokenize(sym.name)}
        symbol_names = {sym.name.lower() for sym in node.symbols}

        path_hits = term_set & path_tokens
        symbol_hits = term_set & (symbol_tokens | symbol_names)
        if not path_hits and not symbol_hits:
            continue
        matched_terms.update(path_hits | symbol_hits)
        # Path matches weigh more than symbol matches — the file is squarely
        # on-topic, not merely defining a same-named helper.
        scores[path] = len(path_hits) * 3 + len(symbol_hits)

    if not scores:
        return ContextSelection(
            goal=goal, files=[], budget=effective_budget, matched_terms=sorted(term_set)
        )

    ranked = sorted(scores, key=lambda path: (-scores[path], path))
    selected: list[str] = []
    for path in ranked:
        if len(selected) >= effective_budget:
            break
        selected.append(path)
        # Pull in the single closest related test if budget remains — agents
        # almost always want the test alongside the file they edit.
        for test in graph.file_tests.get(path, []):
            if len(selected) >= effective_budget:
                break
            if test not in selected:
                selected.append(test)

    return ContextSelection(
        goal=goal,
        files=selected[:effective_budget],
        budget=effective_budget,
        matched_terms=sorted(matched_terms),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _indexable_extensions() -> frozenset[str]:
    """Return the file extensions the builder should discover.

    Always ``.py``; plus the tree-sitter languages when that optional extra is
    installed.  When tree-sitter is absent this is exactly ``{".py"}`` — the
    original behaviour, zero regression.
    """
    if treesitter_ext.treesitter_available():
        return frozenset({".py"}) | treesitter_ext.supported_extensions()
    return frozenset({".py"})


def _is_python(rel_path: str) -> bool:
    """Return whether *rel_path* is a Python source file."""
    return rel_path.endswith(".py")


def _discover_source_files(repo_root: Path, *, max_files: int) -> list[str]:
    """Return sorted repo-relative paths of all indexable source files.

    Includes ``*.py`` always, and the tree-sitter-supported extensions when
    that optional extra is installed.
    """
    extensions = _indexable_extensions()
    found: list[str] = []
    for current_root, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in _EXCLUDE_DIRS and not name.startswith(".git")
        )
        for filename in sorted(filenames):
            if Path(filename).suffix.lower() not in extensions:
                continue
            file_path = Path(current_root) / filename
            if file_path.is_symlink():
                continue
            try:
                rel = relative_path(repo_root, file_path)
            except ValueError:
                continue
            found.append(rel)
            if len(found) >= max_files:
                found.sort()
                return found
    found.sort()
    return found


def _parse_file(file_path: Path, rel_path: str) -> GraphNode:
    """Parse one file into a :class:`GraphNode` of top-level symbols.

    Python files go through :mod:`ast`; other supported extensions go through
    the optional tree-sitter path.  Unreadable or unparsable files yield an
    empty node — never raises.
    """
    node = GraphNode(file=rel_path, is_test=is_test_path(rel_path))
    if _is_python(rel_path):
        tree = _safe_parse(file_path)
        if tree is None:
            return node
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                node.symbols.append(
                    Symbol(name=stmt.name, kind="func", file=rel_path, lineno=stmt.lineno)
                )
            elif isinstance(stmt, ast.ClassDef):
                node.symbols.append(
                    Symbol(name=stmt.name, kind="class", file=rel_path, lineno=stmt.lineno)
                )
        return node

    # Non-Python: tree-sitter path (only reached when the extra is installed,
    # since otherwise these extensions are never discovered).
    source = _read_bytes(file_path)
    if not source:
        return node
    node.symbols.extend(
        treesitter_ext.extract_symbols(rel_path, source, make_symbol=_make_symbol_for(rel_path))
    )
    return node


def _make_symbol_for(rel_path: str) -> Callable[[str, SymbolKind, int], Symbol]:
    """Return a ``(name, kind, lineno) -> Symbol`` factory bound to *rel_path*."""

    def _make(name: str, kind: SymbolKind, lineno: int) -> Symbol:
        return Symbol(name=name, kind=kind, file=rel_path, lineno=lineno)

    return _make


def _read_bytes(file_path: Path) -> bytes:
    """Read *file_path* as bytes, returning empty bytes on any failure."""
    try:
        return file_path.read_bytes()
    except OSError:
        return b""


def _raw_imports(file_path: Path, rel_path: str) -> list[str]:
    """Return raw dotted module names imported by *file_path*.

    Relative imports (``from . import x``) are resolved against the file's own
    package so they can be matched in the module index.
    """
    tree = _safe_parse(file_path)
    if tree is None:
        return []
    package_parts = Path(rel_path).with_suffix("").parts[:-1]
    names: list[str] = []
    for stmt in ast.walk(tree):
        if isinstance(stmt, ast.Import):
            names.extend(alias.name for alias in stmt.names)
        elif isinstance(stmt, ast.ImportFrom):
            names.extend(_resolve_import_from(stmt, package_parts))
    return unique_preserve(names)


def _resolve_import_from(stmt: ast.ImportFrom, package_parts: tuple[str, ...]) -> list[str]:
    """Resolve a ``from ... import ...`` statement to dotted module names."""
    if stmt.level == 0:
        base = stmt.module or ""
        prefix = f"{base}." if base else ""
        names = [base] if base else []
        names.extend(f"{prefix}{alias.name}" for alias in stmt.names)
        return [name for name in names if name]

    # Relative import: walk up `level` packages from the importing file.
    anchor = list(package_parts[: len(package_parts) - (stmt.level - 1)])
    if stmt.module:
        anchor.extend(stmt.module.split("."))
    base_dotted = ".".join(anchor)
    names = [base_dotted] if base_dotted else []
    prefix = f"{base_dotted}." if base_dotted else ""
    names.extend(f"{prefix}{alias.name}" for alias in stmt.names)
    return [name for name in names if name]


def _module_names_for(rel_path: str) -> list[str]:
    """Return every dotted module name a file can be imported as.

    For ``src/pkg/mod.py`` this yields ``src.pkg.mod`` and the suffix forms
    ``pkg.mod`` and ``mod`` (and the package form for ``__init__.py``), so both
    ``import pkg.mod`` and ``from src.pkg import mod`` resolve to the file.
    """
    parts = list(Path(rel_path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return []
    names: list[str] = []
    for start in range(len(parts)):
        names.append(".".join(parts[start:]))
    return unique_preserve(names)


def _resolve_target(graph: CodeGraph, target: str) -> list[str]:
    """Resolve a file-path or symbol-name *target* to in-graph file paths."""
    normalised = target.strip().replace("\\", "/").lstrip("./")
    if normalised in graph.nodes:
        return [normalised]
    # Exact symbol-name match.
    if target in graph.symbols_by_name:
        return list(graph.symbols_by_name[target])
    # Suffix path match (e.g. user passes "cache.py" or "src/cache.py").
    suffix_hits = sorted(
        path for path in graph.nodes if path == normalised or path.endswith("/" + normalised)
    )
    return suffix_hits


def _safe_parse(file_path: Path) -> ast.Module | None:
    """Parse a file with :func:`ast.parse`, returning ``None`` on any failure."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return ast.parse(source, filename=str(file_path))
    except (SyntaxError, ValueError):
        return None
