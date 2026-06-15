"""TOON — Token-Oriented Object Notation.

A compact, dependency-free encoder that represents structured data in a format
that is substantially more token-efficient than JSON for LLM consumption.

Format rules
------------
* ``list[dict]`` with at least one shared key across all rows → **tabular block**:

      KEYS  key1  key2  key3
      ROW   v1    v2    v3
      ROW   v4    v5    v6

* ``list`` of scalars → ``[a, b, c]``
* ``dict`` → ``key: value`` lines, nested values indented
* Nested objects inside a tabular cell → ``json.dumps`` inline (compact)
* ``None`` → ``-``
* All other scalars → ``str()``

The format is designed for *reading*, not machine round-tripping.  An LLM can
parse it unambiguously; it is not reversible to the original Python object.
"""

from __future__ import annotations

import json
from typing import Any  # noqa: UP035

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def to_toon(obj: Any, *, _indent: int = 0) -> str:  # noqa: ANN401
    """Encode *obj* to a compact TOON string.

    Parameters
    ----------
    obj:
        The object to encode.  Accepts any JSON-compatible Python value.
    _indent:
        Internal indentation level (used for recursive dict encoding).

    Returns
    -------
    str
        A human- and LLM-readable TOON-formatted string, terminated with
        a newline.
    """
    if isinstance(obj, list):
        return _encode_list(obj, _indent=_indent)
    if isinstance(obj, dict):
        return _encode_dict(obj, _indent=_indent)
    return _encode_scalar(obj) + "\n"


def to_markdown_table(rows: list[dict[str, Any]]) -> str:
    """Render *rows* as a GitHub-flavoured markdown table.

    All rows must share the same keys (or a superset of the first row's keys
    is used as the header).  Missing values are rendered as ``-``.

    Parameters
    ----------
    rows:
        A list of flat dictionaries with string keys.

    Returns
    -------
    str
        A markdown table string, terminated with a newline.  Returns an empty
        string when *rows* is empty.
    """
    if not rows:
        return ""
    headers = list(rows[0].keys())
    # Collect any extra keys that appear in later rows.
    seen: set[str] = set(headers)
    for row in rows[1:]:
        for key in row:
            if key not in seen:
                headers.append(key)
                seen.add(key)

    col_widths = [max(len(h), _max_cell_width(rows, h)) for h in headers]
    lines: list[str] = []

    header_cells = [h.ljust(col_widths[i]) for i, h in enumerate(headers)]
    lines.append("| " + " | ".join(header_cells) + " |")

    sep_cells = ["-" * col_widths[i] for i in range(len(headers))]
    lines.append("| " + " | ".join(sep_cells) + " |")

    for row in rows:
        cells = [
            _cell_str(row.get(h)).ljust(col_widths[i]) for i, h in enumerate(headers)
        ]
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _encode_list(obj: list[Any], *, _indent: int) -> str:
    if not obj:
        return "[]\n"

    # Detect uniform list[dict] — tabular encoding wins here.
    if _is_uniform_dict_list(obj):
        return _encode_tabular(obj)

    # Scalar list — inline.
    if all(_is_scalar(item) for item in obj):
        parts = ", ".join(_encode_scalar(item) for item in obj)
        return f"[{parts}]\n"

    # Mixed / nested list — one item per line with indentation.
    pad = "  " * _indent
    lines: list[str] = []
    for item in obj:
        rendered = to_toon(item, _indent=_indent + 1).rstrip("\n")
        lines.append(f"{pad}- {rendered}")
    return "\n".join(lines) + "\n"


def _encode_dict(obj: dict[str, Any], *, _indent: int) -> str:
    if not obj:
        return "{}\n"
    pad = "  " * _indent
    lines: list[str] = []
    for key, value in obj.items():
        if _is_scalar(value):
            lines.append(f"{pad}{key}: {_encode_scalar(value)}")
        elif isinstance(value, dict):
            inner = _encode_dict(value, _indent=_indent + 1).rstrip("\n")
            lines.append(f"{pad}{key}:\n{inner}")
        elif isinstance(value, list):
            inner = _encode_list(value, _indent=_indent + 1).rstrip("\n")
            lines.append(f"{pad}{key}: {inner}")
        else:
            lines.append(f"{pad}{key}: {_encode_scalar(value)}")
    return "\n".join(lines) + "\n"


def _encode_tabular(rows: list[dict[str, Any]]) -> str:
    """Render a uniform list[dict] as TOON tabular block."""
    headers = _union_keys(rows)
    header_line = "KEYS  " + "  ".join(headers)
    data_lines: list[str] = []
    for row in rows:
        cells = [_cell_str(row.get(h)) for h in headers]
        data_lines.append("ROW   " + "  ".join(cells))
    return "\n".join([header_line, *data_lines]) + "\n"


def _is_uniform_dict_list(obj: list[Any]) -> bool:
    """Return True when *obj* is a non-empty list whose items are all dicts
    and share at least one common key."""
    if not obj or not all(isinstance(item, dict) for item in obj):
        return False
    if len(obj) == 1:
        return bool(obj[0])  # single dict row — tabular if it has any keys
    first_keys = set(obj[0].keys())
    return any(set(item.keys()) & first_keys for item in obj[1:])


def _union_keys(rows: list[dict[str, Any]]) -> list[str]:
    """Return a stable ordered union of all keys across *rows*."""
    seen: dict[str, None] = {}
    for row in rows:
        for k in row:
            seen[k] = None
    return list(seen)


def _is_scalar(value: Any) -> bool:  # noqa: ANN401
    return value is None or isinstance(value, (str, int, float, bool))


def _encode_scalar(value: Any) -> str:  # noqa: ANN401
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        # Trim trailing zeros for cleaner output.
        formatted = f"{value:.6g}"
        return formatted
    return str(value)


def _cell_str(value: Any) -> str:  # noqa: ANN401
    """Render a cell value, falling back to compact JSON for complex types."""
    if _is_scalar(value):
        return _encode_scalar(value)
    # Nested structure — inline compact JSON.
    return json.dumps(value, separators=(",", ":"))


def _max_cell_width(rows: list[dict[str, Any]], key: str) -> int:
    return max(len(_cell_str(row.get(key))) for row in rows) if rows else 0
