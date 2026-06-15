"""Tests for the TOON serialization module."""

from __future__ import annotations

import json

import pytest

from oh_no_my_claudecode.serialize.toon import to_markdown_table, to_toon

# ---------------------------------------------------------------------------
# Tabular encoding (list[dict] with shared keys)
# ---------------------------------------------------------------------------


def test_uniform_list_of_dicts_produces_tabular_block() -> None:
    rows = [
        {"id": "m1", "kind": "decision", "title": "Use TOON"},
        {"id": "m2", "kind": "gotcha", "title": "Avoid JSON overhead"},
    ]
    result = to_toon(rows)
    assert result.startswith("KEYS  ")
    assert "ROW   " in result
    lines = result.strip().splitlines()
    header = lines[0]
    assert "id" in header
    assert "kind" in header
    assert "title" in header
    assert lines[1].startswith("ROW   ")
    assert "m1" in lines[1]
    assert "decision" in lines[1]
    assert lines[2].startswith("ROW   ")
    assert "m2" in lines[2]


def test_single_dict_row_is_tabular() -> None:
    rows = [{"id": "m1", "kind": "gotcha"}]
    result = to_toon(rows)
    assert "KEYS" in result
    assert "ROW" in result


def test_tabular_handles_none_values() -> None:
    rows = [
        {"id": "m1", "score": None},
        {"id": "m2", "score": 0.85},
    ]
    result = to_toon(rows)
    assert "-" in result  # None renders as dash
    assert "0.85" in result


def test_tabular_handles_bool_values() -> None:
    rows = [
        {"active": True, "deleted": False},
    ]
    result = to_toon(rows)
    assert "true" in result
    assert "false" in result


def test_tabular_handles_nested_object_inline() -> None:
    rows = [{"id": "m1", "meta": {"x": 1}}]
    result = to_toon(rows)
    # Nested dict should be rendered as compact JSON in the cell.
    assert '{"x":' in result or '"x": 1' in result


# ---------------------------------------------------------------------------
# Scalar list
# ---------------------------------------------------------------------------


def test_scalar_list_renders_inline() -> None:
    result = to_toon(["alpha", "beta", "gamma"])
    assert result.strip() == "[alpha, beta, gamma]"


def test_empty_list_renders_as_brackets() -> None:
    result = to_toon([])
    assert result.strip() == "[]"


def test_integer_list_renders_inline() -> None:
    result = to_toon([1, 2, 3])
    assert result.strip() == "[1, 2, 3]"


# ---------------------------------------------------------------------------
# Dict encoding
# ---------------------------------------------------------------------------


def test_dict_renders_as_key_value_lines() -> None:
    result = to_toon({"repo_root": "/some/repo", "count": 42})
    assert "repo_root: /some/repo" in result
    assert "count: 42" in result


def test_empty_dict_renders_as_braces() -> None:
    result = to_toon({})
    assert result.strip() == "{}"


def test_nested_dict_is_indented() -> None:
    data = {"outer": {"inner": "value"}}
    result = to_toon(data)
    assert "outer:" in result
    assert "inner: value" in result


# ---------------------------------------------------------------------------
# Scalar top-level
# ---------------------------------------------------------------------------


def test_none_scalar_renders_as_dash() -> None:
    result = to_toon(None)
    assert result.strip() == "-"


def test_bool_scalar() -> None:
    assert to_toon(True).strip() == "true"
    assert to_toon(False).strip() == "false"


def test_string_scalar() -> None:
    assert to_toon("hello").strip() == "hello"


# ---------------------------------------------------------------------------
# Mixed / non-uniform list falls back gracefully
# ---------------------------------------------------------------------------


def test_mixed_list_renders_each_item() -> None:
    result = to_toon([{"id": "m1"}, "plain", 42])
    # Should not crash; each item gets a bullet line.
    assert "m1" in result
    assert "plain" in result
    assert "42" in result


# ---------------------------------------------------------------------------
# Token-savings evidence
# ---------------------------------------------------------------------------

_REPRESENTATIVE_MEMORIES = [
    {
        "id": f"mem_{i:04d}",
        "kind": kind,
        "title": title,
        "summary": summary,
        "source_ref": f"src/module_{i % 5}.py",
        "confidence": round(0.5 + (i % 5) * 0.1, 1),
        "feedback_score": 0.0,
        "relevance": round(0.9 - i * 0.05, 3),
    }
    for i, (kind, title, summary) in enumerate(
        [
            ("decision", "Use TOON for MCP output", "Reduces token usage vs JSON."),
            ("gotcha", "JSON wastes tokens", "Structural overhead is ~40-60% of chars."),
            ("invariant", "Never skip the cache boundary", "All workers must validate cache."),
            ("hotspot", "src/cache.py is frequently modified", "High churn file."),
            ("validation_rule", "Run ruff before commit", "Enforced by pre-commit hook."),
            ("decision", "Double quotes everywhere", "Prettier config enforces this."),
            ("gotcha", "pnpm only — no npm/yarn", "Monorepo strictly uses pnpm."),
            ("invariant", "Type-check before merging", "CI runs mypy --strict."),
            ("hotspot", "auth module touched in 80% of PRs", "Core dependency."),
            ("failed_approach", "Tried LRU cache in Redis", "Latency too high for use case."),
        ]
    )
]


def test_toon_is_meaningfully_smaller_than_json() -> None:
    """Assert TOON saves >=25% characters vs JSON for a representative payload."""
    payload = {"memories": _REPRESENTATIVE_MEMORIES}
    json_text = json.dumps(payload, indent=2, sort_keys=True)
    toon_text = to_toon(payload)

    json_chars = len(json_text)
    toon_chars = len(toon_text)
    savings_pct = (json_chars - toon_chars) / json_chars * 100

    assert savings_pct >= 25, (
        f"TOON should be >=25% smaller than JSON; got {savings_pct:.1f}% "
        f"(JSON={json_chars}, TOON={toon_chars})"
    )


def test_toon_reduces_punctuation_token_proxy() -> None:
    """TOON should have meaningfully fewer structural punctuation characters."""
    payload = {"memories": _REPRESENTATIVE_MEMORIES}
    json_text = json.dumps(payload, indent=2, sort_keys=True)
    toon_text = to_toon(payload)

    def punct_count(text: str) -> int:
        return sum(1 for c in text if c in '{}[]",:\n ')

    json_punct = punct_count(json_text)
    toon_punct = punct_count(toon_text)

    assert toon_punct < json_punct, (
        f"TOON should have fewer punctuation chars: TOON={toon_punct} vs JSON={json_punct}"
    )


# ---------------------------------------------------------------------------
# Markdown table helper
# ---------------------------------------------------------------------------


def test_markdown_table_basic() -> None:
    rows = [
        {"name": "Alice", "role": "admin"},
        {"name": "Bob", "role": "viewer"},
    ]
    result = to_markdown_table(rows)
    lines = result.strip().splitlines()
    assert lines[0].startswith("|")
    assert "name" in lines[0]
    assert "role" in lines[0]
    # Separator row
    assert "---" in lines[1]
    # Data rows
    assert "Alice" in lines[2]
    assert "Bob" in lines[3]


def test_markdown_table_empty_returns_empty_string() -> None:
    assert to_markdown_table([]) == ""


def test_markdown_table_handles_missing_keys() -> None:
    rows = [
        {"a": 1, "b": 2},
        {"a": 3},  # missing "b"
    ]
    result = to_markdown_table(rows)
    assert "a" in result
    assert "b" in result
    # Missing value should render as "-"
    assert "-" in result


def test_markdown_table_is_smaller_than_json() -> None:
    rows = _REPRESENTATIVE_MEMORIES
    json_text = json.dumps(rows, indent=2)
    md_text = to_markdown_table(rows)
    assert len(md_text) < len(json_text)


# ---------------------------------------------------------------------------
# Readability / unambiguity spot-checks
# ---------------------------------------------------------------------------


def test_tabular_all_field_values_present() -> None:
    """Every field value must appear verbatim in the TOON output."""
    rows = [{"id": "abc123", "status": "active", "score": 0.75}]
    result = to_toon(rows)
    assert "abc123" in result
    assert "active" in result
    assert "0.75" in result


def test_toon_terminates_with_newline() -> None:
    assert to_toon({"key": "val"}).endswith("\n")
    assert to_toon([{"a": 1}]).endswith("\n")
    assert to_toon([1, 2]).endswith("\n")


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "-"),
        (True, "true"),
        (False, "false"),
        (0, "0"),
        (3.14, "3.14"),
    ],
)
def test_scalar_rendering_in_tabular_cell(value: object, expected: str) -> None:
    rows = [{"field": value}]
    result = to_toon(rows)
    assert expected in result
