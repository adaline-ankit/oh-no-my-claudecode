"""Tests for the ``onmc viz`` feature — Mermaid + D2 memory + code graph diagrams.

Covers the pure renderers (:func:`memory_mermaid`, :func:`code_mermaid`,
:func:`memory_d2`, :func:`code_d2`) for valid output, seeded nodes+edges,
empty-graph graceful handling, determinism, label escaping, ``--format``
switching, and ``--json`` CLI envelopes.

Deliberately never asserts against Rich ``--help`` output (that would test
Typer, not this feature).
"""

from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.codegraph import build_codegraph
from oh_no_my_claudecode.models import (
    EdgeType,
    MemoryEdge,
    MemoryEntry,
    MemoryKind,
    SourceType,
)
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now
from oh_no_my_claudecode.viz.d2 import code_d2, memory_d2
from oh_no_my_claudecode.viz.mermaid import code_mermaid, memory_mermaid

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seeded_store(tmp_path: Path) -> SQLiteStorage:
    """Return a storage seeded with two memories linked by a ``supersedes`` edge."""
    storage = SQLiteStorage(tmp_path / "memory.db")
    storage.initialize()
    now = utc_now()
    storage.upsert_memories(
        [
            MemoryEntry(
                id="mem-a",
                kind=MemoryKind.DECISION,
                title="Use a shared cache boundary",
                summary="Decision A",
                details="Details A",
                source_type=SourceType.DOC,
                source_ref="docs/architecture.md",
                confidence=0.9,
                created_at=now,
                updated_at=now,
            ),
            MemoryEntry(
                id="mem-b",
                kind=MemoryKind.INVARIANT,
                title='Do not bypass the "cache" boundary',
                summary="Invariant B",
                details="Details B",
                source_type=SourceType.DOC,
                source_ref="docs/architecture.md",
                confidence=0.8,
                created_at=now,
                updated_at=now,
            ),
        ]
    )
    storage.upsert_memory_edge(
        MemoryEdge(
            id="edge-1",
            from_memory_id="mem-a",
            to_memory_id="mem-b",
            edge_type=EdgeType.SUPERSEDES,
            confidence=1.0,
            created_at=now,
        )
    )
    return storage


# ---------------------------------------------------------------------------
# memory_mermaid
# ---------------------------------------------------------------------------


def test_memory_mermaid_emits_valid_graph_td_with_nodes_and_edges(tmp_path: Path) -> None:
    storage = _seeded_store(tmp_path)
    diagram = memory_mermaid(storage)

    lines = diagram.splitlines()
    assert lines[0] == "graph TD"
    # Both seeded memories are rendered.
    assert "Use a shared cache boundary" in diagram
    # Kinds become subgraphs.
    assert "subgraph" in diagram
    assert "decision" in diagram
    assert "invariant" in diagram
    # The supersedes edge is drawn with a labelled arrow.
    assert "|supersedes|" in diagram


def test_memory_mermaid_escapes_quotes_in_labels(tmp_path: Path) -> None:
    storage = _seeded_store(tmp_path)
    diagram = memory_mermaid(storage)
    # The raw double quote from the invariant title must be escaped, never bare.
    assert '"cache"' not in diagram
    assert "&quot;cache&quot;" in diagram


def test_memory_mermaid_empty_is_graceful(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "memory.db")
    storage.initialize()
    diagram = memory_mermaid(storage)
    assert diagram.splitlines()[0] == "graph TD"
    assert "no memories yet" in diagram


def test_memory_mermaid_is_deterministic(tmp_path: Path) -> None:
    storage = _seeded_store(tmp_path)
    assert memory_mermaid(storage) == memory_mermaid(storage)


def test_memory_mermaid_limit_zero_renders_only_placeholder(tmp_path: Path) -> None:
    storage = _seeded_store(tmp_path)
    diagram = memory_mermaid(storage, limit=0)
    assert "no memories yet" in diagram


def test_memory_mermaid_drops_edges_to_clipped_nodes(tmp_path: Path) -> None:
    storage = _seeded_store(tmp_path)
    # Only one node survives the limit, so the edge has a dangling endpoint.
    diagram = memory_mermaid(storage, limit=1)
    assert "|supersedes|" not in diagram


# ---------------------------------------------------------------------------
# code_mermaid
# ---------------------------------------------------------------------------


def test_code_mermaid_emits_graph_for_seeded_repo(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    diagram = code_mermaid(sample_repo, "src/cache.py", graph=graph)

    lines = diagram.splitlines()
    assert lines[0] == "graph TD"
    # Target file present.
    assert "src/cache.py" in diagram
    # worker imports cache → shown as an importer edge into the target.
    assert "src/worker.py" in diagram
    assert "-->" in diagram
    # The test that exercises cache is grouped under tests.
    assert "tests/test_cache.py" in diagram
    assert "-.->" in diagram


def test_code_mermaid_resolves_symbol_target(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    diagram = code_mermaid(sample_repo, "invalidate_cache", graph=graph)
    assert diagram.splitlines()[0] == "graph TD"
    assert "src/cache.py" in diagram


def test_code_mermaid_missing_target_is_graceful(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    diagram = code_mermaid(sample_repo, "does/not/exist.py", graph=graph)
    assert diagram.splitlines()[0] == "graph TD"
    assert "not found" in diagram


def test_code_mermaid_is_deterministic(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    first = code_mermaid(sample_repo, "src/cache.py", graph=graph)
    second = code_mermaid(sample_repo, "src/cache.py", graph=graph)
    assert first == second


# ---------------------------------------------------------------------------
# --json envelopes (pure, no CLI runner / Rich help)
# ---------------------------------------------------------------------------


def test_memory_mermaid_json_envelope_shape(tmp_path: Path) -> None:
    storage = _seeded_store(tmp_path)
    diagram = memory_mermaid(storage)
    envelope = json.loads(json.dumps({"kind": "memory", "mermaid": diagram}))
    assert envelope["kind"] == "memory"
    assert envelope["mermaid"].splitlines()[0] == "graph TD"


# ---------------------------------------------------------------------------
# memory_d2 — valid D2 output with seeded nodes and edges
# ---------------------------------------------------------------------------


def test_memory_d2_emits_direction_and_containers(tmp_path: Path) -> None:
    """D2 output starts with ``direction: right`` and groups nodes by kind."""
    storage = _seeded_store(tmp_path)
    diagram = memory_d2(storage)

    lines = diagram.splitlines()
    assert lines[0] == "direction: right"
    # Both kinds become containers.
    assert "decision" in diagram
    assert "invariant" in diagram
    # Nodes nested inside containers (D2 key: { ... }).
    assert "m0:" in diagram or "m1:" in diagram
    # The supersedes edge is emitted.
    assert "supersedes" in diagram
    assert "->" in diagram


def test_memory_d2_escapes_double_quotes_in_labels(tmp_path: Path) -> None:
    """Raw ASCII double-quotes in memory titles must not appear in D2 labels.

    The invariant title contains ASCII straight double-quotes around the word
    cache. Our renderer replaces each bare 0x22 with a Unicode typographic
    quotation mark (U+201C) so D2 does not mistake it for the string terminator.
    """
    storage = _seeded_store(tmp_path)
    diagram = memory_d2(storage)
    # The raw ASCII double-quote (0x22) must not surround "cache" in label text.
    # Our renderer replaces each bare double-quote with U+201C (curly left-quote).
    raw_dq = chr(0x22)
    assert raw_dq + "cache" + raw_dq not in diagram
    # The word cache must still appear in the output (flanked by curly quotes).
    assert "cache" in diagram


def test_memory_d2_empty_is_graceful(tmp_path: Path) -> None:
    """An empty store returns a valid single-node placeholder D2 diagram."""
    storage = SQLiteStorage(tmp_path / "memory.db")
    storage.initialize()
    diagram = memory_d2(storage)
    assert "direction: right" in diagram
    assert "no memories yet" in diagram


def test_memory_d2_is_deterministic(tmp_path: Path) -> None:
    """Two calls on the same store produce byte-identical output."""
    storage = _seeded_store(tmp_path)
    assert memory_d2(storage) == memory_d2(storage)


def test_memory_d2_limit_zero_renders_only_placeholder(tmp_path: Path) -> None:
    storage = _seeded_store(tmp_path)
    diagram = memory_d2(storage, limit=0)
    assert "no memories yet" in diagram


def test_memory_d2_drops_edges_to_clipped_nodes(tmp_path: Path) -> None:
    """When only one node survives the limit the edge must be suppressed."""
    storage = _seeded_store(tmp_path)
    diagram = memory_d2(storage, limit=1)
    assert "supersedes" not in diagram


# ---------------------------------------------------------------------------
# code_d2 — valid D2 output for a seeded repo
# ---------------------------------------------------------------------------


def test_code_d2_emits_valid_d2_for_seeded_repo(sample_repo: Path) -> None:
    """D2 code graph contains containers and edges for cache.py blast radius."""
    graph = build_codegraph(sample_repo)
    diagram = code_d2(sample_repo, "src/cache.py", graph=graph)

    assert diagram.splitlines()[0] == "direction: right"
    # Target container present.
    assert "src/cache.py" in diagram
    # worker.py is an importer → appears in diagram.
    assert "src/worker.py" in diagram
    # Tests container present.
    assert "tests/test_cache.py" in diagram
    # Edge markers (D2 uses ->).
    assert "->" in diagram


def test_code_d2_resolves_symbol_target(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    diagram = code_d2(sample_repo, "invalidate_cache", graph=graph)
    assert "direction: right" in diagram
    assert "src/cache.py" in diagram


def test_code_d2_missing_target_is_graceful(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    diagram = code_d2(sample_repo, "does/not/exist.py", graph=graph)
    assert "direction: right" in diagram
    assert "not found" in diagram


def test_code_d2_is_deterministic(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    first = code_d2(sample_repo, "src/cache.py", graph=graph)
    second = code_d2(sample_repo, "src/cache.py", graph=graph)
    assert first == second


# ---------------------------------------------------------------------------
# Format switching — D2 vs Mermaid produce distinct output on same data
# ---------------------------------------------------------------------------


def test_format_d2_and_mermaid_produce_distinct_output(tmp_path: Path) -> None:
    """The two renderers produce different text for the same underlying data."""
    storage = _seeded_store(tmp_path)
    mermaid_out = memory_mermaid(storage)
    d2_out = memory_d2(storage)
    assert mermaid_out != d2_out
    # Each has its own header syntax.
    assert mermaid_out.startswith("graph TD")
    assert d2_out.startswith("direction: right")


def test_mermaid_output_unchanged_after_d2_addition(tmp_path: Path) -> None:
    """Adding D2 support must leave existing Mermaid output byte-identical."""
    storage = _seeded_store(tmp_path)
    diagram = memory_mermaid(storage)
    # Spot-check every property of the original Mermaid contract:
    assert diagram.splitlines()[0] == "graph TD"
    assert "subgraph" in diagram
    assert "|supersedes|" in diagram
    assert "&quot;cache&quot;" in diagram


# ---------------------------------------------------------------------------
# D2 JSON envelopes (pure, no CLI runner)
# ---------------------------------------------------------------------------


def test_memory_d2_json_envelope_shape(tmp_path: Path) -> None:
    storage = _seeded_store(tmp_path)
    diagram = memory_d2(storage)
    envelope = json.loads(
        json.dumps({"kind": "memory", "format": "d2", "d2": diagram})
    )
    assert envelope["kind"] == "memory"
    assert envelope["format"] == "d2"
    assert envelope["d2"].startswith("direction: right")


def test_code_d2_json_envelope_shape(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    diagram = code_d2(sample_repo, "src/cache.py", graph=graph)
    envelope = json.loads(
        json.dumps(
            {"kind": "code", "format": "d2", "target": "src/cache.py", "d2": diagram}
        )
    )
    assert envelope["kind"] == "code"
    assert envelope["format"] == "d2"
    assert envelope["d2"].startswith("direction: right")
