"""Reuse radar — surface existing code that already does a thing.

This module powers ``onmc reuse``.  It is entirely offline and deterministic
(no LLM calls, no network, stdlib only).  The goal is to stop agents in a swarm
from reimplementing a function/class that already exists — DRY across the repo.

Architecture
------------
1. **Index** the repo via the stdlib :mod:`ast` module: walk every ``*.py``
   file under *repo_root* (skipping ``.venv``/``.git``/``__pycache__``/tests),
   parse it, and collect every top-level function and class into a
   :class:`_Candidate`.  Each candidate captures its signature (argument names),
   the first line of its docstring, and the tokens derived from its name,
   docstring, and argument names.

2. **Rank** candidates against the query.  The query is tokenised with the same
   :func:`~oh_no_my_claudecode.utils.text.tokenize` used by recall, then scored
   by overlap of query tokens against each candidate's token buckets, with a
   bucket-specific weight:

   - name tokens:     ×3.0 — a name match is the strongest reuse signal
   - docstring tokens: ×1.5 — describes what the symbol does
   - arg-name tokens: ×1.0 — weak corroborating signal

   The overlap contribution from each bucket is normalised by the query token
   count so a long noisy query does not crowd out a precise match.  An exact
   (case-insensitive) name match adds a fixed bonus so ``onmc reuse tokenize``
   surfaces ``tokenize`` first.

3. **Deterministic sort**: descending score, then ascending symbol name, then
   ascending ``file:lineno`` — identical across runs.  Only candidates scoring
   above :data:`_MIN_SCORE` are returned, bounded to *limit*.

Mirrors the deterministic-ranking approach in
:mod:`oh_no_my_claudecode.recall.compiler`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.utils.text import tokenize

# ---------------------------------------------------------------------------
# Indexing constants
# ---------------------------------------------------------------------------

# Directories that never carry reusable production code worth surfacing.
_SKIP_DIRS = frozenset({".venv", "venv", ".git", "__pycache__", "tests", ".tox", ".mypy_cache"})

# Hard cap on files indexed so a giant repo cannot blow up wall-clock/memory.
_MAX_FILES = 2000

# Bucket-specific weights applied to the per-bucket overlap ratio.
_NAME_WEIGHT = 3.0
_DOC_WEIGHT = 1.5
_ARG_WEIGHT = 1.0

# Fixed bonus when the query exactly matches the symbol name (case-insensitive).
_EXACT_NAME_BONUS = 5.0

# Only candidates scoring above this threshold are emitted.
_MIN_SCORE = 0.1


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class ReuseHit:
    """One existing symbol that may already do what the query describes."""

    symbol: str  # the function/class name
    kind: str  # "function" | "class"
    file: str  # repo-relative POSIX path
    lineno: int  # 1-based definition line
    signature: str  # e.g. "tokenize(text)" or "OnmcService(cwd)"
    doc_excerpt: str  # first non-empty docstring line ("" when absent)
    score: float  # ranking score (higher = more relevant)


# ---------------------------------------------------------------------------
# Internal indexing model
# ---------------------------------------------------------------------------


@dataclass
class _Candidate:
    """An indexed top-level symbol plus its precomputed token buckets."""

    symbol: str
    kind: str
    file: str
    lineno: int
    signature: str
    doc_excerpt: str
    name_tokens: set[str] = field(default_factory=set)
    doc_tokens: set[str] = field(default_factory=set)
    arg_tokens: set[str] = field(default_factory=set)


def _first_doc_line(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    """Return the first non-empty line of *node*'s docstring, or ``""``."""
    doc = ast.get_docstring(node, clean=True)
    if not doc:
        return ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _arg_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Return the ordered argument names of a function definition."""
    args = node.args
    names: list[str] = []
    names.extend(a.arg for a in args.posonlyargs)
    names.extend(a.arg for a in args.args)
    if args.vararg is not None:
        names.append(args.vararg.arg)
    names.extend(a.arg for a in args.kwonlyargs)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return names


def _signature(node: ast.AST) -> str:
    """Build a compact ``name(arg, arg)`` signature for a definition node."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return f"{node.name}({', '.join(_arg_names(node))})"
    if isinstance(node, ast.ClassDef):
        return f"{node.name}(...)"
    return ""


def _candidate_from_node(
    node: ast.AST,
    *,
    rel_path: str,
) -> _Candidate | None:
    """Build a :class:`_Candidate` from a top-level definition node, or None."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        kind = "function"
        arg_names = _arg_names(node)
    elif isinstance(node, ast.ClassDef):
        kind = "class"
        arg_names = []
    else:
        return None

    name = node.name
    # Skip private/dunder symbols — they are rarely the thing an agent reuses.
    if name.startswith("_"):
        return None

    doc_excerpt = _first_doc_line(node)
    arg_token_source = " ".join(a for a in arg_names if a not in {"self", "cls"})
    return _Candidate(
        symbol=name,
        kind=kind,
        file=rel_path,
        lineno=node.lineno,
        signature=_signature(node),
        doc_excerpt=doc_excerpt,
        name_tokens=set(tokenize(name)),
        doc_tokens=set(tokenize(doc_excerpt)),
        arg_tokens=set(tokenize(arg_token_source)),
    )


def _iter_python_files(repo_root: Path) -> list[Path]:
    """Return a deterministic, bounded list of indexable ``*.py`` files."""
    files: list[Path] = []
    for path in sorted(repo_root.rglob("*.py")):
        rel_parts = path.relative_to(repo_root).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        files.append(path)
        if len(files) >= _MAX_FILES:
            break
    return files


def _index_repo(repo_root: Path) -> list[_Candidate]:
    """Parse every indexable file and collect top-level symbols."""
    candidates: list[_Candidate] = []
    for path in _iter_python_files(repo_root):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
            # A single unparseable file must never break the whole scan.
            continue
        rel_path = path.relative_to(repo_root).as_posix()
        for node in tree.body:
            candidate = _candidate_from_node(node, rel_path=rel_path)
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def _score_candidate(candidate: _Candidate, query_tokens: set[str], query_text: str) -> float:
    """Return the relevance score of *candidate* against the query.

    Each token bucket contributes ``(|overlap| / |query_tokens|) × weight``.
    Overlap is normalised by the query token count so a long noisy query does
    not outrank a precise one.  An exact (case-insensitive) name match adds a
    fixed bonus so the obvious symbol always surfaces first.
    """
    if not query_tokens:
        return 0.0
    denom = float(len(query_tokens))
    name_overlap = len(query_tokens & candidate.name_tokens) / denom
    doc_overlap = len(query_tokens & candidate.doc_tokens) / denom
    arg_overlap = len(query_tokens & candidate.arg_tokens) / denom
    score = (
        name_overlap * _NAME_WEIGHT + doc_overlap * _DOC_WEIGHT + arg_overlap * _ARG_WEIGHT
    )
    if candidate.symbol.lower() == query_text.strip().lower():
        score += _EXACT_NAME_BONUS
    return score


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_reuse(repo_root: Path | str, query: str, *, limit: int = 8) -> list[ReuseHit]:
    """Find existing symbols that may already implement what *query* describes.

    Indexes *repo_root* via stdlib :mod:`ast`, collecting top-level functions
    and classes (skipping ``.venv``/``.git``/``__pycache__``/tests and private
    symbols), then ranks candidates by token overlap between the query and each
    symbol's name, docstring, and argument names.

    Args:
        repo_root: Directory to scan for ``*.py`` files.
        query: A description of the desired behaviour, or a symbol name.
        limit: Maximum number of hits to return (must be >= 1).

    Returns:
        A deterministically ordered list of :class:`ReuseHit` (score desc, then
        symbol name asc, then ``file:lineno`` asc), bounded to *limit*.  Returns
        an empty list when the query is blank, the repo has no indexable code,
        or nothing scores above the minimum threshold.  Never raises on a
        missing directory or unparseable file.
    """
    root = Path(repo_root)
    if not query or not query.strip():
        return []
    if limit < 1:
        return []
    if not root.is_dir():
        return []

    query_tokens = set(tokenize(query))
    candidates = _index_repo(root)

    scored: list[tuple[float, _Candidate]] = []
    for candidate in candidates:
        score = _score_candidate(candidate, query_tokens, query)
        if score >= _MIN_SCORE:
            scored.append((score, candidate))

    # Deterministic order: score desc, then symbol asc, then file:lineno asc.
    scored.sort(key=lambda item: (-item[0], item[1].symbol, item[1].file, item[1].lineno))

    hits: list[ReuseHit] = []
    for score, candidate in scored[:limit]:
        hits.append(
            ReuseHit(
                symbol=candidate.symbol,
                kind=candidate.kind,
                file=candidate.file,
                lineno=candidate.lineno,
                signature=candidate.signature,
                doc_excerpt=candidate.doc_excerpt,
                score=round(score, 4),
            )
        )
    return hits
