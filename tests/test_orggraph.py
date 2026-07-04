"""Tests for the pure org-graph builder (:mod:`oh_no_my_claudecode.orggraph.graph`).

These tests build graphs directly from in-memory :class:`MemoryEntry` lists — no
database required — so they exercise the deterministic extraction/inference core
in isolation.
"""

from __future__ import annotations

from datetime import datetime

from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.orggraph.graph import (
    KIND_COMPONENT,
    KIND_DECISION,
    KIND_FILE,
    KIND_PERSON,
    REL_CAUSED_BY,
    REL_DECIDED_BY,
    REL_DEPENDS_ON,
    REL_RELATES_TO,
    REL_SUPERSEDES,
    build_org_graph,
    decision_lineage,
    query_entity,
)

_NOW = datetime(2026, 7, 4, 12, 0, 0)


def _mem(
    mid: str,
    kind: MemoryKind,
    title: str,
    summary: str = "",
    details: str = "",
    tags: list[str] | None = None,
    source_ref: str = "manual:seed",
) -> MemoryEntry:
    return MemoryEntry(
        id=mid,
        kind=kind,
        title=title,
        summary=summary,
        details=details,
        source_type=SourceType.MANUAL,
        source_ref=source_ref,
        tags=tags or [],
        confidence=0.9,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _fixtures() -> list[MemoryEntry]:
    return [
        _mem(
            "m1",
            MemoryKind.DECISION,
            "Adopt command auto-discovery",
            summary="Use command_registry to load src/foo/commands.py per feature.",
            details="Avoids editing the central cli.py hub.",
            tags=["author:ankit"],
            source_ref="github:pr/55/author=ankit",
        ),
        _mem(
            "m2",
            MemoryKind.FAILED_APPROACH,
            "Central hub registration",
            summary="Editing src/cli.py for every feature caused merge conflicts.",
            details="Superseded by command_registry auto-discovery.",
        ),
        _mem(
            "m3",
            MemoryKind.INVARIANT,
            "storage is read-only in orggraph",
            summary="src/orggraph/commands.py must only read from SQLiteStorage.",
        ),
        _mem(
            "m4",
            MemoryKind.GOTCHA,
            "preflight is env-fragile",
            summary="src/preflight/runner.py false-fails without pinned typer.",
            details="Blame command_registry cliref drift.",
        ),
    ]


def test_entities_extracted() -> None:
    graph = build_org_graph(_fixtures())
    names = {e.name for e in graph.entities}
    kinds = {e.name: e.kind for e in graph.entities}

    # file/path entities
    assert "src/foo/commands.py" in names
    assert "src/cli.py" in names
    assert "src/orggraph/commands.py" in names
    assert kinds["src/cli.py"] == KIND_FILE

    # component entities
    assert "command_registry" in names
    assert kinds["command_registry"] == KIND_COMPONENT
    assert "SQLiteStorage" in names

    # decision entity (from decision-kind title)
    assert "Adopt command auto-discovery" in names
    assert kinds["Adopt command auto-discovery"] == KIND_DECISION

    # person entity (from author tag / source_ref)
    assert "ankit" in names
    assert kinds["ankit"] == KIND_PERSON


def test_typed_edges_present() -> None:
    graph = build_org_graph(_fixtures())
    rels = {(e.src, e.dst, e.rel) for e in graph.edges}

    # decided-by: decision -> author
    assert ("Adopt command auto-discovery", "ankit", REL_DECIDED_BY) in rels

    # supersedes: failed-approach actor supersedes the file it touched
    assert any(rel == REL_SUPERSEDES and dst == "src/cli.py" for _, dst, rel in rels)

    # depends-on: co-mentioned code entities in an invariant memory
    assert any(rel == REL_DEPENDS_ON for _, _, rel in rels)

    # caused-by: gotcha file -> blamed actor
    assert any(src == "src/preflight/runner.py" and rel == REL_CAUSED_BY for src, _, rel in rels)

    # relates-to fallback exists
    assert any(rel == REL_RELATES_TO for _, _, rel in rels)


def test_lineage_populated() -> None:
    graph = build_org_graph(_fixtures())
    # every entity carries at least one source memory id
    for ent in graph.entities:
        assert ent.memory_ids, f"entity {ent.name} has no lineage"
    # every edge carries lineage
    for edge in graph.edges:
        assert edge.memory_ids, f"edge {edge.src}->{edge.dst} has no lineage"
    # a specific edge traces to the memory that justified it
    supersede_edges = [e for e in graph.edges if e.rel == REL_SUPERSEDES]
    assert supersede_edges
    assert all("m2" in e.memory_ids for e in supersede_edges)


def test_query_entity_returns_neighbors_and_provenance() -> None:
    graph = build_org_graph(_fixtures())
    result = query_entity(graph, "Adopt command auto-discovery")

    assert result["entity"] is not None
    assert result["entity"].kind == KIND_DECISION
    assert result["neighbors"], "decision should have neighbours"
    # the author is among the neighbours via a decided-by edge
    neighbor_names = {other.name for _, other in result["neighbors"]}
    assert "ankit" in neighbor_names
    # provenance includes the decision's own memory
    assert "m1" in result["provenance"]


def test_query_missing_entity_is_graceful() -> None:
    graph = build_org_graph(_fixtures())
    result = query_entity(graph, "does-not-exist")
    assert result["entity"] is None
    assert result["neighbors"] == []
    assert result["provenance"] == []


def test_decision_lineage_returns_chain() -> None:
    graph = build_org_graph(_fixtures())
    result = decision_lineage(graph, "Adopt command auto-discovery")

    assert result["decision"] is not None
    assert result["chain"], "lineage chain should be non-empty"
    assert "m1" in result["memory_ids"]
    # chain is deterministically ordered by (rel, dst, src)
    keys = [(e.rel, e.dst, e.src) for e in result["chain"]]
    assert keys == sorted(keys)


def test_decision_lineage_missing_is_graceful() -> None:
    graph = build_org_graph(_fixtures())
    result = decision_lineage(graph, "no such decision")
    assert result["decision"] is None
    assert result["chain"] == []
    assert result["memory_ids"] == []


def test_empty_input_yields_empty_graph() -> None:
    graph = build_org_graph([])
    assert graph.entities == []
    assert graph.edges == []
    # queries on an empty graph do not crash
    assert query_entity(graph, "anything")["entity"] is None
    assert decision_lineage(graph, "anything")["decision"] is None


def test_deterministic_output() -> None:
    fixtures = _fixtures()
    g1 = build_org_graph(fixtures)
    g2 = build_org_graph(list(reversed(fixtures)))
    assert [(e.name, e.kind, e.memory_ids) for e in g1.entities] == [
        (e.name, e.kind, e.memory_ids) for e in g2.entities
    ]
    assert [(e.src, e.dst, e.rel, e.memory_ids) for e in g1.edges] == [
        (e.src, e.dst, e.rel, e.memory_ids) for e in g2.edges
    ]
