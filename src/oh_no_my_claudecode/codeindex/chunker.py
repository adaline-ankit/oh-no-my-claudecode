"""AST-based file chunker for the code index.

Produces a list of :class:`~oh_no_my_claudecode.codeindex.models.IndexChunk`
objects for a single source file.  Python files are chunked via the standard-
library :mod:`ast` module (no third-party dependencies).  Other languages go
through the optional tree-sitter path when available, falling back to a
single whole-file chunk.

Chunk identity is keyed by git blob SHA: same blob SHA → same chunk IDs,
so unchanged files produce identical output (idempotent).

One chunk is always emitted per file: the module-level chunk
(``symbol="__module__"``, ``kind="module"``).  Additional chunks are emitted
for each top-level function, class, and method discovered in the AST.
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from oh_no_my_claudecode.codeindex.models import (
    ChunkKind,
    IndexChunk,
    IndexEdge,
    Language,
)
from oh_no_my_claudecode.core.repo import is_test_path

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Language detection from file extension
# ---------------------------------------------------------------------------

_EXT_TO_LANGUAGE: dict[str, Language] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}


def _detect_language(rel_path: str) -> Language:
    suffix = Path(rel_path).suffix.lower()
    return _EXT_TO_LANGUAGE.get(suffix, "other")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

_GIT_TIMEOUT = 15  # seconds


def get_blob_shas(repo_root: Path) -> dict[str, str]:
    """Return a mapping of repo-relative path → git blob SHA for tracked files.

    Uses ``git ls-files -s`` to read the index.  Files that are tracked but
    have unstaged modifications still appear here with their *index* blob SHA.
    Returns an empty dict on any git failure so the caller can fall back to
    ``git hash-object``.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-s"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}

    blob_shas: dict[str, str] = {}
    for line in result.stdout.splitlines():
        # Format: <mode> <blob_sha> <stage>\t<path>
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        meta = parts[0].split()
        if len(meta) < 2:  # noqa: PLR2004
            continue
        blob_sha = meta[1]
        path = parts[1]
        blob_shas[path] = blob_sha

    return blob_shas


def get_head_commit_sha(repo_root: Path) -> str:
    """Return the current HEAD commit SHA, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def compute_blob_sha(file_path: Path) -> str:
    """Compute the git blob SHA for a file (tracks working-tree state).

    Equivalent to ``git hash-object <file>``.  Returns an empty string on any
    failure.
    """
    try:
        result = subprocess.run(
            ["git", "hash-object", str(file_path)],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ---------------------------------------------------------------------------
# Chunk ID derivation
# ---------------------------------------------------------------------------

def _make_chunk_id(blob_sha: str, rel_path: str, symbol: str, start_line: int) -> str:
    """Return a stable 16-hex-char chunk ID.

    ``sha256(blob_sha:rel_path:symbol:start_line)[:16]`` — changes whenever
    the blob SHA changes (file content changed), unique per symbol per file.
    """
    raw = f"{blob_sha}:{rel_path}:{symbol}:{start_line}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Python AST chunker
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _read_lines(file_path: Path) -> list[str] | None:
    """Read file as a list of lines.  Returns None on read/decode failure."""
    try:
        return file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError):
        return None


def _lines_slice(lines: list[str], start: int, end: int) -> str:
    """Extract source text from *lines* for 1-based [start, end] range."""
    return "".join(lines[start - 1 : end])


def _chunk_id_for(blob_sha: str, rel_path: str, symbol: str, start_line: int) -> str:
    return _make_chunk_id(blob_sha, rel_path, symbol, start_line)


def _python_chunks(
    file_path: Path,
    rel_path: str,
    blob_sha: str,
    commit_sha: str,
    lines: list[str],
) -> tuple[list[IndexChunk], list[tuple[str, str]]]:
    """Chunk a Python file into :class:`IndexChunk` objects.

    Returns ``(chunks, call_edges)`` where *call_edges* is a list of
    ``(caller_symbol, called_name)`` pairs discovered by walking function
    bodies — resolved into :class:`IndexEdge` objects later by the builder.
    """
    try:
        tree = ast.parse("".join(lines), filename=str(file_path))
    except (SyntaxError, ValueError):
        return [], []

    is_test = is_test_path(rel_path)
    indexed_at = _now_iso()
    total_lines = len(lines)
    chunks: list[IndexChunk] = []
    call_edges: list[tuple[str, str]] = []  # (caller_symbol, called_name)

    # Module-level chunk (always emitted)
    module_chunk = IndexChunk(
        chunk_id=_chunk_id_for(blob_sha, rel_path, "__module__", 1),
        blob_sha=blob_sha,
        commit_sha=commit_sha,
        path=rel_path,
        symbol="__module__",
        kind="module",
        start_line=1,
        end_line=total_lines or 1,
        language="python",
        is_test=is_test,
        is_stale=False,
        trust_level="default",
        indexed_at=indexed_at,
        content=_lines_slice(lines, 1, total_lines or 1),
    )
    chunks.append(module_chunk)

    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(stmt, "end_lineno", stmt.lineno)
            kind: ChunkKind = "test" if is_test else "function"
            chunk = IndexChunk(
                chunk_id=_chunk_id_for(blob_sha, rel_path, stmt.name, stmt.lineno),
                blob_sha=blob_sha,
                commit_sha=commit_sha,
                path=rel_path,
                symbol=stmt.name,
                kind=kind,
                start_line=stmt.lineno,
                end_line=end,
                language="python",
                is_test=is_test,
                is_stale=False,
                trust_level="default",
                indexed_at=indexed_at,
                content=_lines_slice(lines, stmt.lineno, end),
            )
            chunks.append(chunk)
            # Collect call edges for this function
            for node in ast.walk(stmt):
                if isinstance(node, ast.Call):
                    called = _extract_call_name(node)
                    if called:
                        call_edges.append((stmt.name, called))

        elif isinstance(stmt, ast.ClassDef):
            class_end = getattr(stmt, "end_lineno", stmt.lineno)
            class_chunk = IndexChunk(
                chunk_id=_chunk_id_for(blob_sha, rel_path, stmt.name, stmt.lineno),
                blob_sha=blob_sha,
                commit_sha=commit_sha,
                path=rel_path,
                symbol=stmt.name,
                kind="class",
                start_line=stmt.lineno,
                end_line=class_end,
                language="python",
                is_test=is_test,
                is_stale=False,
                trust_level="default",
                indexed_at=indexed_at,
                content=_lines_slice(lines, stmt.lineno, class_end),
            )
            chunks.append(class_chunk)

            # Walk class body for methods
            for item in stmt.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_end = getattr(item, "end_lineno", item.lineno)
                    method_sym = f"{stmt.name}.{item.name}"
                    method_chunk = IndexChunk(
                        chunk_id=_chunk_id_for(blob_sha, rel_path, method_sym, item.lineno),
                        blob_sha=blob_sha,
                        commit_sha=commit_sha,
                        path=rel_path,
                        symbol=method_sym,
                        kind="method",
                        start_line=item.lineno,
                        end_line=method_end,
                        language="python",
                        is_test=is_test,
                        is_stale=False,
                        trust_level="default",
                        indexed_at=indexed_at,
                        content=_lines_slice(lines, item.lineno, method_end),
                    )
                    chunks.append(method_chunk)
                    # Collect call edges for this method
                    for node in ast.walk(item):
                        if isinstance(node, ast.Call):
                            called = _extract_call_name(node)
                            if called:
                                call_edges.append((method_sym, called))

    return chunks, call_edges


def _extract_call_name(call_node: ast.Call) -> str | None:
    """Extract the bare function/method name from an AST Call node.

    Returns the final attribute name for ``obj.method()`` calls, the bare name
    for ``func()`` calls, and None for complex call expressions.
    """
    func = call_node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


# ---------------------------------------------------------------------------
# Non-Python chunker (tree-sitter optional, whole-file fallback)
# ---------------------------------------------------------------------------

def _nonpython_chunks(
    file_path: Path,
    rel_path: str,
    blob_sha: str,
    commit_sha: str,
    lines: list[str],
    language: Language,
) -> tuple[list[IndexChunk], list[tuple[str, str]]]:
    """Chunk a non-Python file.

    Tries tree-sitter if available; falls back to a single whole-file chunk.
    """
    is_test = is_test_path(rel_path)
    indexed_at = _now_iso()
    total_lines = len(lines)
    content = "".join(lines)

    # Try tree-sitter (optional — import-guarded)
    try:
        from oh_no_my_claudecode.codegraph import treesitter_ext  # noqa: PLC0415
        from oh_no_my_claudecode.codegraph.models import Symbol as CodeGraphSymbol  # noqa: PLC0415

        if treesitter_ext.treesitter_available():
            source = content.encode("utf-8", errors="replace")

            def _make_cg_sym(name: str, kind: str, lineno: int) -> CodeGraphSymbol:
                from oh_no_my_claudecode.codegraph.models import Symbol as _Sym  # noqa: PLC0415

                kind_typed = kind if kind in ("func", "class") else "func"
                return _Sym(name=name, kind=kind_typed, file=rel_path, lineno=lineno)  # type: ignore[arg-type]

            cg_symbols = treesitter_ext.extract_symbols(
                rel_path, source, make_symbol=_make_cg_sym
            )
            chunks: list[IndexChunk] = [
                IndexChunk(
                    chunk_id=_chunk_id_for(blob_sha, rel_path, "__module__", 1),
                    blob_sha=blob_sha,
                    commit_sha=commit_sha,
                    path=rel_path,
                    symbol="__module__",
                    kind="module",
                    start_line=1,
                    end_line=total_lines or 1,
                    language=language,
                    is_test=is_test,
                    is_stale=False,
                    trust_level="default",
                    indexed_at=indexed_at,
                    content=content,
                )
            ]
            for sym in cg_symbols:
                sym_kind: ChunkKind = "function" if sym.kind == "func" else "class"
                chunks.append(
                    IndexChunk(
                        chunk_id=_chunk_id_for(blob_sha, rel_path, sym.name, sym.lineno),
                        blob_sha=blob_sha,
                        commit_sha=commit_sha,
                        path=rel_path,
                        symbol=sym.name,
                        kind=sym_kind,
                        start_line=sym.lineno,
                        end_line=sym.lineno,  # tree-sitter ext doesn't provide end_lineno
                        language=language,
                        is_test=is_test,
                        is_stale=False,
                        trust_level="default",
                        indexed_at=indexed_at,
                        content="",  # content requires a second pass; omit for now
                    )
                )
            return chunks, []
    except (ImportError, Exception):  # noqa: BLE001,S110
        pass

    # Whole-file fallback
    if _is_doc_path(rel_path):
        kind_fallback: ChunkKind = "docs"
    elif _is_config_path(rel_path):
        kind_fallback = "config"
    else:
        kind_fallback = "module"
    return [
        IndexChunk(
            chunk_id=_chunk_id_for(blob_sha, rel_path, "__module__", 1),
            blob_sha=blob_sha,
            commit_sha=commit_sha,
            path=rel_path,
            symbol="__module__",
            kind=kind_fallback,
            start_line=1,
            end_line=total_lines or 1,
            language=language,
            is_test=is_test,
            is_stale=False,
            trust_level="default",
            indexed_at=indexed_at,
            content=content,
        )
    ], []


def _is_doc_path(rel_path: str) -> bool:
    name = Path(rel_path).name.lower()
    return name.endswith(".md") or name.endswith(".rst") or name.endswith(".txt")


def _is_config_path(rel_path: str) -> bool:
    name = Path(rel_path).name.lower()
    return name in {
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "package.json",
        "tsconfig.json",
        "jest.config.js",
        "jest.config.ts",
        ".eslintrc",
        ".eslintrc.json",
        ".eslintrc.js",
        "makefile",
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
    } or name.endswith(".toml") or name.endswith(".yaml") or name.endswith(".yml")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Extensions always indexed (Python always; others when tree-sitter available)
_ALWAYS_INDEXED_EXTS: frozenset[str] = frozenset({".py"})
_DOC_EXTS: frozenset[str] = frozenset({".md", ".rst", ".txt"})
_CONFIG_EXTS: frozenset[str] = frozenset({".toml", ".yaml", ".yml", ".json", ".cfg", ".ini"})

# Additional extensions to index even without tree-sitter (docs + config)
_EXTRA_INDEXED_EXTS: frozenset[str] = _DOC_EXTS | _CONFIG_EXTS


def should_chunk_extension(rel_path: str) -> bool:
    """Return True if this file extension warrants chunking."""
    suffix = Path(rel_path).suffix.lower()
    if suffix in _ALWAYS_INDEXED_EXTS or suffix in _EXTRA_INDEXED_EXTS:
        return True

    # Non-Python source: only index if tree-sitter is available
    try:
        from oh_no_my_claudecode.codegraph import treesitter_ext  # noqa: PLC0415

        if treesitter_ext.treesitter_available():
            return suffix in treesitter_ext.supported_extensions()
    except ImportError:
        pass

    return False


def chunk_file(
    file_path: Path,
    rel_path: str,
    blob_sha: str,
    commit_sha: str,
) -> tuple[list[IndexChunk], list[tuple[str, str]]]:
    """Chunk one source file into :class:`IndexChunk` objects.

    Returns ``(chunks, call_edges)`` where *call_edges* is a list of
    ``(caller_symbol, called_name)`` pairs for later edge resolution.

    Returns ``([], [])`` when the file cannot be read or has no indexable
    content.  Never raises.
    """
    lines = _read_lines(file_path)
    if lines is None:
        return [], []

    language = _detect_language(rel_path)

    if rel_path.endswith(".py"):
        return _python_chunks(file_path, rel_path, blob_sha, commit_sha, lines)

    return _nonpython_chunks(file_path, rel_path, blob_sha, commit_sha, lines, language)


def build_import_edges(
    rel_path: str,
    repo_root: Path,
    file_to_module_chunk: dict[str, str],  # rel_path → symbol ("__module__")
    indexed_paths: set[str],
) -> list[IndexEdge]:
    """Build ``"import"`` edges for a Python file.

    Walks the file's AST for import statements and emits an edge for each
    in-repo module that is imported.  Returns an empty list on any parse
    failure.
    """
    if not rel_path.endswith(".py"):
        return []

    abs_path = repo_root / rel_path
    try:
        source = abs_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(abs_path))
    except (OSError, SyntaxError, ValueError):
        return []

    # Build module → path index for the indexed files
    module_index: dict[str, str] = {}
    for path in indexed_paths:
        if not path.endswith(".py"):
            continue
        from pathlib import PurePosixPath  # noqa: PLC0415

        parts = list(PurePosixPath(path).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            for start in range(len(parts)):
                mname = ".".join(parts[start:])
                module_index.setdefault(mname, path)

    package_parts = tuple(Path(rel_path).with_suffix("").parts[:-1])
    raw_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            raw_imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
                if base:
                    raw_imports.append(base)
                prefix = f"{base}." if base else ""
                raw_imports.extend(f"{prefix}{alias.name}" for alias in node.names)
            else:
                anchor = list(package_parts[: len(package_parts) - (node.level - 1)])
                if node.module:
                    anchor.extend(node.module.split("."))
                base_dotted = ".".join(anchor)
                if base_dotted:
                    raw_imports.append(base_dotted)
                prefix = f"{base_dotted}." if base_dotted else ""
                raw_imports.extend(f"{prefix}{alias.name}" for alias in node.names)

    edges: list[IndexEdge] = []
    seen: set[str] = set()
    for raw in raw_imports:
        target_path = module_index.get(raw)
        if target_path and target_path != rel_path and target_path not in seen:
            seen.add(target_path)
            edges.append(
                IndexEdge(
                    src_path=rel_path,
                    src_symbol="__module__",
                    dst_path=target_path,
                    dst_symbol="__module__",
                    edge_type="import",
                )
            )
    return edges
