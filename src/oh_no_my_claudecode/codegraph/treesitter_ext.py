"""Optional tree-sitter multi-language extraction for the code graph.

The core :mod:`~oh_no_my_claudecode.codegraph.builder` indexes ``*.py`` files
with the standard-library :mod:`ast` module.  This module *optionally* extends
that reach to JavaScript, TypeScript, Go, Rust, and Java by parsing them with
tree-sitter — **but only when tree-sitter is installed**.

tree-sitter is an optional dependency (``pip install oh-no-my-claudecode[treesitter]``).
Every import here is guarded: if tree-sitter (or the language pack) is missing,
:func:`treesitter_available` returns ``False`` and the builder falls back to the
pure-Python path with zero behavioural change.

What we extract per non-Python file:

- top-level symbols — functions, classes, and type-like declarations, mapped
  onto the same :class:`~oh_no_my_claudecode.codegraph.models.Symbol` model the
  Python path uses (``kind`` is ``"func"`` or ``"class"``), and
- relative import specifiers (JS/TS ``import ... from "./x"``) so import edges
  can be resolved to in-repo files by the builder.  Non-relative / package
  imports (Go/Rust/Java module systems) are intentionally not turned into edges
  — their resolution is ambiguous offline and would produce false blast radius.

Everything is bounded and deterministic: parse failures yield empty results
rather than raising, exactly like the ``ast`` path.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from oh_no_my_claudecode.codegraph.models import Symbol, SymbolKind

# --- Optional dependency guard --------------------------------------------
# Both packages must import for the tree-sitter path to be usable.  Any
# ImportError (or a broken build) disables the feature cleanly.  The modules
# are dynamic C extensions with no stubs, so they are held as ``Any``.
_tree_sitter: Any = None
_get_language: Any = None
try:  # pragma: no cover - exercised indirectly via treesitter_available()
    import tree_sitter as _tree_sitter_mod
    from tree_sitter_language_pack import get_language as _get_language_fn

    _tree_sitter = _tree_sitter_mod
    _get_language = _get_language_fn
    _TREESITTER_IMPORT_OK = True
except Exception:  # noqa: BLE001 - any failure means "not available"
    _TREESITTER_IMPORT_OK = False


# File extension → tree-sitter language name.  Only languages we can reliably
# extract top-level symbols from are listed.
_EXT_TO_LANGUAGE: dict[str, str] = {
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}

# Per-grammar node types that name a top-level symbol, and the kind we record.
# "func" and "class" are the only two kinds the Symbol model allows, so
# type-like declarations (interface/struct/enum/trait/type alias) are recorded
# as "class" — they are the nearest structural analogue.
_SYMBOL_NODE_KINDS: dict[str, SymbolKind] = {
    # functions / methods
    "function_declaration": "func",
    "method_declaration": "func",
    "function_item": "func",  # rust
    "method_definition": "func",
    # classes / type-like declarations
    "class_declaration": "class",
    "interface_declaration": "class",
    "enum_declaration": "class",
    "type_alias_declaration": "class",  # ts
    "struct_item": "class",  # rust
    "enum_item": "class",  # rust
    "trait_item": "class",  # rust
    "type_declaration": "class",  # go
}

# Nodes that wrap a real declaration (JS/TS ``export function foo`` etc.) — we
# recurse into their children to find the underlying named declaration.
_WRAPPER_NODE_TYPES = frozenset({"export_statement"})

# Import statement node types per grammar family we resolve to file edges.
# Only JS/TS relative specifiers become edges (see module docstring).
_IMPORT_NODE_TYPES = frozenset({"import_statement"})


def treesitter_available() -> bool:
    """Return ``True`` when tree-sitter multi-language parsing is usable."""
    return _TREESITTER_IMPORT_OK


def supported_extensions() -> frozenset[str]:
    """Return the set of file extensions the tree-sitter path can parse."""
    return frozenset(_EXT_TO_LANGUAGE)


def language_for_path(rel_path: str) -> str | None:
    """Return the tree-sitter language name for *rel_path*, or ``None``."""
    return _EXT_TO_LANGUAGE.get(Path(rel_path).suffix.lower())


@cache
def _parser_for(language_name: str) -> Any:
    """Return a cached tree-sitter ``Parser`` for *language_name* (or ``None``).

    Built via ``tree_sitter.Parser(get_language(...))`` — the language-pack's
    ``get_parser`` wrapper expects ``str`` source, whereas the raw ``Parser``
    accepts ``bytes`` (what we feed it).  Any failure disables that language.
    """
    if not _TREESITTER_IMPORT_OK:
        return None
    try:
        language = _get_language(language_name)
        return _tree_sitter.Parser(language)
    except Exception:  # noqa: BLE001 - unknown/unbuildable language → skip
        return None


def extract_symbols(
    rel_path: str,
    source: bytes,
    *,
    make_symbol: Callable[[str, SymbolKind, int], Symbol],
) -> list[Symbol]:
    """Extract top-level symbols from *source* for the language of *rel_path*.

    *make_symbol* is a callable ``(name, kind, lineno) -> Symbol`` supplied by
    the builder so this module never has to import the model at runtime (keeps
    the optional dependency boundary clean).  Returns an empty list on any
    failure — never raises.
    """
    language_name = language_for_path(rel_path)
    if language_name is None:
        return []
    parser = _parser_for(language_name)
    if parser is None:
        return []
    try:
        tree = parser.parse(source)
    except Exception:  # noqa: BLE001 - malformed input → no symbols
        return []

    symbols: list[Symbol] = []
    seen: set[tuple[str, int]] = set()
    for child in tree.root_node.children:
        for decl in _iter_named_declarations(child):
            kind = _SYMBOL_NODE_KINDS.get(decl.type)
            if kind is None:
                continue
            name = _declaration_name(decl)
            if not name:
                continue
            lineno = int(decl.start_point[0]) + 1
            dedup_key = (name, lineno)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            symbols.append(make_symbol(name, kind, lineno))
    return symbols


def extract_import_targets(rel_path: str, source: bytes) -> list[str]:
    """Return in-repo file paths imported by *rel_path* (best effort).

    Only JS/TS *relative* import specifiers (``./x``, ``../y``) are resolved,
    against a small set of candidate extensions and ``index`` files.  Returns
    repo-relative POSIX paths; the builder filters these against the files it
    actually indexed.  Non-relative / package imports are ignored (see module
    docstring).  Never raises.
    """
    language_name = language_for_path(rel_path)
    if language_name not in ("javascript", "typescript", "tsx"):
        return []
    parser = _parser_for(language_name)
    if parser is None:
        return []
    try:
        tree = parser.parse(source)
    except Exception:  # noqa: BLE001
        return []

    specifiers: list[str] = []
    for child in tree.root_node.children:
        if child.type not in _IMPORT_NODE_TYPES:
            continue
        spec = _import_specifier(child)
        if spec and (spec.startswith("./") or spec.startswith("../")):
            specifiers.append(spec)

    targets: list[str] = []
    seen: set[str] = set()
    for spec in specifiers:
        for candidate in _resolve_relative_specifier(rel_path, spec):
            if candidate not in seen:
                seen.add(candidate)
                targets.append(candidate)
    return targets


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iter_named_declarations(node: Any) -> list[Any]:
    """Yield the declaration node(s) a top-level *node* contributes.

    Unwraps ``export`` wrappers so ``export function foo`` surfaces the inner
    ``function_declaration``.  A plain declaration yields itself.
    """
    node_type = getattr(node, "type", "")
    if node_type in _WRAPPER_NODE_TYPES:
        found: list[Any] = []
        for child in node.children:
            if child.type in _SYMBOL_NODE_KINDS:
                found.append(child)
        return found
    if node_type in _SYMBOL_NODE_KINDS:
        return [node]
    return []


def _declaration_name(node: Any) -> str | None:
    """Return the identifier name of a declaration node.

    Uses the ``name`` field when present; for Go ``type_declaration`` the name
    lives in a nested ``type_spec`` child, handled explicitly.
    """
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return _node_text(name_node)
    # Go: type_declaration → type_spec(name=...) [→ type_alias(name=...)]
    if node.type == "type_declaration":
        for child in node.children:
            if child.type in ("type_spec", "type_alias"):
                spec_name = child.child_by_field_name("name")
                if spec_name is not None:
                    return _node_text(spec_name)
    return None


def _import_specifier(import_node: Any) -> str | None:
    """Return the string specifier of a JS/TS ``import_statement``."""
    source_field = import_node.child_by_field_name("source")
    candidate = source_field if source_field is not None else _find_first_string(import_node)
    if candidate is None:
        return None
    text = _node_text(candidate)
    if text is None:
        return None
    return text.strip("\"'`")


def _find_first_string(node: Any) -> Any:
    """Depth-first search for the first ``string`` node under *node*."""
    for child in node.children:
        if child.type == "string":
            return child
        nested = _find_first_string(child)
        if nested is not None:
            return nested
    return None


def _resolve_relative_specifier(rel_path: str, specifier: str) -> list[str]:
    """Resolve a relative JS/TS import specifier to candidate repo file paths.

    Produces the specifier with common extensions appended plus ``index.*``
    forms, all normalised to repo-relative POSIX paths.  The builder keeps only
    those that correspond to a file it actually indexed.
    """
    base_dir = Path(rel_path).parent
    raw = (base_dir / specifier).as_posix()
    # Normalise away ``.``/``..`` segments without touching the filesystem.
    normalised = Path(raw)
    try:
        parts: list[str] = []
        for part in normalised.parts:
            if part == "..":
                if parts:
                    parts.pop()
            elif part != ".":
                parts.append(part)
        stem = "/".join(parts)
    except Exception:  # noqa: BLE001
        stem = raw

    if not stem:
        return []

    extensions = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
    candidates: list[str] = []
    has_known_ext = Path(stem).suffix.lower() in _EXT_TO_LANGUAGE
    if has_known_ext:
        candidates.append(stem)
    else:
        candidates.extend(f"{stem}{ext}" for ext in extensions)
        candidates.extend(f"{stem}/index{ext}" for ext in extensions)
    return candidates


def _node_text(node: Any) -> str | None:
    """Return the UTF-8 text of a tree-sitter node, or ``None`` on failure."""
    raw = getattr(node, "text", None)
    if raw is None:
        return None
    try:
        decoded = raw.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return None
    return str(decoded)
