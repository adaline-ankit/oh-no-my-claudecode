"""blame/compiler.py — governance map linking a file's symbols to recorded memories.

``compile_blame`` is fully offline (no LLM, no network).  It:

1. Normalises the requested path to a repo-relative form.
2. Gathers all memories referencing the file (reusing ``_memory_references_path``
   from ``why.compiler`` — do NOT duplicate that logic).
3. Extracts top-level symbols from the file (functions, classes, module-level
   constants for .py/.ts/.js; markdown headings for .md; degrades gracefully for
   other extensions or binary / oversized files).
4. For each memory, tries to attach it to the symbol(s) it names (substring match
   of a symbol name within the memory title, summary, or details).  Memories that
   don't match any symbol land in the ``"(whole file)"`` bucket.

Heuristic limits (honest):
- Symbol extraction is regex-based, NOT AST-based.  Nested classes/functions,
  decorators on their own line, and minified code may mis-parse.
- Attachment is plain substring match (case-sensitive).  A memory mentioning the
  word ``cache`` will attach to any symbol whose name contains ``cache``.
- No NLP, no semantic similarity — purely lexical.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.models import MemoryEntry
from oh_no_my_claudecode.storage import SQLiteStorage

# Reuse path-matching helpers from why.compiler to avoid duplication.
from oh_no_my_claudecode.why.compiler import _memory_references_path, _normalize_path

# Maximum file size we'll attempt to scan for symbols (bytes).
_MAX_FILE_BYTES = 512 * 1024  # 512 KiB

# Sentinel anchor name for memories that don't match any symbol.
FILE_LEVEL_ANCHOR = "(whole file)"

# ---------------------------------------------------------------------------
# Symbol patterns — ordered by priority; first match per line wins.
# ---------------------------------------------------------------------------

# Python: `def foo(`, `async def foo(`, `class Foo(`
_PY_DEF = re.compile(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)\s*[\(:]")
_PY_CLASS = re.compile(r"^class\s+([A-Za-z_]\w*)\s*[\(:]")
# TypeScript / JavaScript: `function foo(`, `const foo =`, `class Foo`
_TS_FUNC = re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$]\w*)\s*[\(<]")
_TS_CLASS = re.compile(r"^(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$]\w*)\s*[{(<\s]")
_TS_CONST = re.compile(
    r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$]\w*)\s*(?::\s*[A-Za-z][\w<\[\]|&, ]*\s*)?="
)
# Markdown: any ATX heading level  `# Heading`
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+)")


@dataclass(frozen=True)
class SymbolAnchor:
    """A top-level symbol or section extracted from the file."""

    name: str  # symbol / heading text (stripped)
    line: int  # 1-based line number


@dataclass
class BlameAnchor:
    """One entry in the blame map — either a symbol or the whole-file bucket."""

    anchor: str  # symbol name or FILE_LEVEL_ANCHOR
    line: int | None  # 1-based line number; None for whole-file bucket
    memories: list[MemoryEntry] = field(default_factory=list)


@dataclass
class BlameResult:
    """Full governance map for a single file."""

    path: str  # repo-relative path
    file_exists: bool
    symbol_count: int  # number of symbols extracted (0 if unknown extension or parse failed)
    anchors: list[BlameAnchor] = field(default_factory=list)
    # Memories that reference the file but were not matched to any symbol.
    file_level_memories: list[MemoryEntry] = field(default_factory=list)
    has_data: bool = False
    output_path: str = ""

    # Set when the file could not be read (binary, too large, decode error).
    parse_skipped: bool = False
    parse_skip_reason: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_symbols(file_path: Path) -> list[SymbolAnchor] | None:
    """Return a list of top-level symbols from *file_path*, or None on failure.

    Returns ``None`` when the file is missing, oversized, binary, or has an
    extension we don't recognise — callers treat that as "no symbol info".
    """
    if not file_path.exists():
        return None

    try:
        size = file_path.stat().st_size
    except OSError:
        return None
    if size > _MAX_FILE_BYTES:
        return None

    suffix = file_path.suffix.lower()
    if suffix not in {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".md", ".mdx"}:
        return None

    try:
        text = file_path.read_bytes()
        # Bail on obvious binary content (NUL bytes in first 8 KiB).
        if b"\x00" in text[:8192]:
            return None
        content = text.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return None

    is_markdown = suffix in {".md", ".mdx"}
    symbols: list[SymbolAnchor] = []

    for lineno, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if is_markdown:
            m = _MD_HEADING.match(line)
            if m:
                symbols.append(SymbolAnchor(name=m.group(2).strip(), line=lineno))
            continue
        # Python
        if suffix == ".py":
            for pattern in (_PY_DEF, _PY_CLASS):
                m = pattern.match(line)
                if m:
                    symbols.append(SymbolAnchor(name=m.group(1), line=lineno))
                    break
            continue
        # TS / JS
        for pattern in (_TS_FUNC, _TS_CLASS, _TS_CONST):
            m = pattern.match(line)
            if m:
                symbols.append(SymbolAnchor(name=m.group(1), line=lineno))
                break

    return symbols


def _memory_names_symbol(memory: MemoryEntry, symbol_name: str) -> bool:
    """Return True if *memory* mentions *symbol_name* in title/summary/details.

    Case-sensitive substring match.  We intentionally keep this simple — a
    memory mentioning ``invalidate_cache`` will attach to that symbol; one
    mentioning only ``cache`` will also attach (and the user can judge).
    """
    haystack = " ".join(
        filter(None, [memory.title, memory.summary, memory.details, memory.source_ref])
    )
    return symbol_name in haystack


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_blame(
    repo_root: Path,
    storage: SQLiteStorage,
    raw_path: str,
) -> BlameResult:
    """Assemble a BlameResult for *raw_path* from the existing memory store.

    Entirely offline — no LLM calls, no network access.  Deterministic.

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root.
    storage:
        Initialised SQLiteStorage from which memories are read.
    raw_path:
        File path (absolute or repo-relative) to blame.

    Returns
    -------
    BlameResult
        ``has_data=False`` when no memories reference this file.  The caller
        (CLI / service) is responsible for rendering the "nothing known" path.
    """
    rel_path = _normalize_path(repo_root, raw_path)
    abs_path = repo_root / rel_path

    memories = storage.list_memories()

    # ── Step 1: filter memories that reference this file ─────────────────────
    relevant: list[MemoryEntry] = [
        m for m in memories if _memory_references_path(m, rel_path)
    ]

    if not relevant:
        return BlameResult(
            path=rel_path,
            file_exists=abs_path.exists(),
            symbol_count=0,
            has_data=False,
        )

    # ── Step 2: extract symbols ───────────────────────────────────────────────
    parse_skipped = False
    parse_skip_reason = ""
    symbols: list[SymbolAnchor] = []

    if not abs_path.exists():
        parse_skipped = True
        parse_skip_reason = "file not found in working tree"
    else:
        extracted = _extract_symbols(abs_path)
        if extracted is None:
            parse_skipped = True
            suffix = abs_path.suffix.lower()
            if suffix not in {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".md", ".mdx"}:
                parse_skip_reason = f"unsupported extension ({suffix or 'none'})"
            else:
                parse_skip_reason = "file too large, binary, or undecodable"
        else:
            symbols = extracted

    # ── Step 3: attach memories to symbols ────────────────────────────────────
    # Build a map: symbol_name → BlameAnchor (preserves declaration order).
    anchor_map: dict[str, BlameAnchor] = {
        sym.name: BlameAnchor(anchor=sym.name, line=sym.line) for sym in symbols
    }
    # Ordered list of symbol names for fast lookup.
    symbol_names: list[str] = [sym.name for sym in symbols]

    file_level: list[MemoryEntry] = []

    for memory in relevant:
        matched = False
        for name in symbol_names:
            if _memory_names_symbol(memory, name):
                anchor_map[name].memories.append(memory)
                matched = True
                # Don't break — a memory may legitimately name multiple symbols.
        if not matched:
            file_level.append(memory)

    # ── Step 4: build result ─────────────────────────────────────────────────
    # Only include anchors that actually have memories attached.
    anchors_with_memories = [a for a in anchor_map.values() if a.memories]

    return BlameResult(
        path=rel_path,
        file_exists=abs_path.exists(),
        symbol_count=len(symbols),
        anchors=anchors_with_memories,
        file_level_memories=file_level,
        has_data=bool(anchors_with_memories or file_level),
        parse_skipped=parse_skipped,
        parse_skip_reason=parse_skip_reason,
    )


def blame_result_to_markdown(result: BlameResult) -> str:
    """Render a BlameResult as a markdown string."""
    lines: list[str] = []
    lines.append(f"# Blame map: `{result.path}`")
    lines.append("")
    lines.append("> *Heuristic* — symbol extraction uses regex, not AST.")
    lines.append("> Attachment is plain substring match (case-sensitive).")
    lines.append("")

    if result.parse_skipped:
        lines.append(f"**Symbol extraction skipped:** {result.parse_skip_reason}")
        lines.append("")
    else:
        lines.append(f"**Symbols extracted:** {result.symbol_count}")
        lines.append("")

    if not result.has_data:
        lines.append(
            "> No recorded knowledge for this file — "
            "run `onmc ingest` / `onmc mine` to populate."
        )
        return "\n".join(lines)

    # ── per-symbol sections ───────────────────────────────────────────────────
    if result.anchors:
        lines.append("## Symbol-level governance")
        lines.append("")
        for anchor in result.anchors:
            line_label = f"  _(line {anchor.line})_" if anchor.line is not None else ""
            lines.append(f"### `{anchor.anchor}`{line_label}")
            lines.append("")
            for memory in anchor.memories:
                lines.append(f"- **[{memory.kind.value}]** {memory.title}")
                lines.append(f"  {memory.summary}")
                if memory.source_ref:
                    lines.append(f"  _{memory.source_ref}_")
            lines.append("")

    # ── file-level bucket ────────────────────────────────────────────────────
    if result.file_level_memories:
        lines.append("## File-level governance (applies to whole file)")
        lines.append("")
        for memory in result.file_level_memories:
            lines.append(f"- **[{memory.kind.value}]** {memory.title}")
            lines.append(f"  {memory.summary}")
            if memory.source_ref:
                lines.append(f"  _{memory.source_ref}_")
        lines.append("")

    return "\n".join(lines)
