"""Tests for the ``onmc viz`` feature — Mermaid memory + code graph diagrams.

Covers the pure renderers (:func:`memory_mermaid`, :func:`code_mermaid`) for
valid ``graph TD`` output, seeded nodes+edges, empty-graph graceful handling,
determinism, and label escaping — plus the ``--json`` CLI envelope.

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
