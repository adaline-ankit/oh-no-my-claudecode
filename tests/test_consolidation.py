"""Tests for memory/consolidation.py and related storage (v5 migration)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.memory.consolidation import ConsolidationResult, consolidate_memories
from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.models.memory_edge import EdgeType, MemoryEdge
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

# ── helpers ────────────────────────────────────────────────────────────────────


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _make_memory(
    *,
    mid: str,
    kind: MemoryKind = MemoryKind.DECISION,
    title: str = "A decision",
    summary: str = "We decided something.",
    details: str = "Extended details.",
    source_type: SourceType = SourceType.CODE,
    source_ref: str = "src/foo.py",
    confidence: float = 0.6,
    feedback_score: float = 0.0,
) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=mid,
        kind=kind,
        title=title,
        summary=summary,
        details=details,
        source_type=source_type,
        source_ref=source_ref,
        tags=[],
        confidence=confidence,
        feedback_score=feedback_score,
        created_at=now,
        updated_at=now,
    )


# ── migration v5 ───────────────────────────────────────────────────────────────


def test_migration_v5_creates_memory_edges_table(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    storage = SQLiteStorage(db_path)
    storage.initialize()

    # Schema version must be "5" after a fresh init.
    assert storage.get_meta("schema_version") == "6"

    # The memory_edges table must exist.
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "memory_edges" in tables


def test_migration_v5_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    storage = SQLiteStorage(db_path)
    storage.initialize()
    # Second initialize must not raise and must leave schema_version at "6".
    storage.initialize()
    assert storage.get_meta("schema_version") == "6"


# ── edge CRUD ─────────────────────────────────────────────────────────────────


def test_upsert_and_list_memory_edge(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "test.db")
    storage.initialize()

    now = utc_now()
    edge = MemoryEdge(
        id="edge-abc",
        from_memory_id="mem-1",
        to_memory_id="mem-2",
        edge_type=EdgeType.RELATES,
        confidence=0.7,
        created_at=now,
    )
    storage.upsert_memory_edge(edge)

    edges = storage.list_memory_edges()
    assert len(edges) == 1
    assert edges[0].id == "edge-abc"
    assert edges[0].edge_type == EdgeType.RELATES
    assert edges[0].confidence == pytest.approx(0.7)


def test_list_edges_filtered_by_memory_id(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "test.db")
    storage.initialize()

    now = utc_now()
    storage.upsert_memory_edge(
        MemoryEdge(
            id="e1",
            from_memory_id="A",
            to_memory_id="B",
            edge_type=EdgeType.RELATES,
            confidence=0.7,
            created_at=now,
        )
    )
    storage.upsert_memory_edge(
        MemoryEdge(
            id="e2",
            from_memory_id="C",
            to_memory_id="D",
            edge_type=EdgeType.CONTRADICTS,
            confidence=0.6,
            created_at=now,
        )
    )

    edges_for_a = storage.list_memory_edges(memory_id="A")
    assert len(edges_for_a) == 1
    assert edges_for_a[0].id == "e1"

    edges_for_b = storage.list_memory_edges(memory_id="B")
    assert len(edges_for_b) == 1

    edges_contradicts = storage.list_memory_edges(edge_type=EdgeType.CONTRADICTS)
    assert len(edges_contradicts) == 1
    assert edges_contradicts[0].id == "e2"


def test_delete_memory_edge(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "test.db")
    storage.initialize()

    now = utc_now()
    storage.upsert_memory_edge(
        MemoryEdge(
            id="e-del",
            from_memory_id="X",
            to_memory_id="Y",
            edge_type=EdgeType.DUPLICATE_OF,
            confidence=1.0,
            created_at=now,
        )
    )
    assert storage.delete_memory_edge("e-del") is True
    assert storage.delete_memory_edge("e-del") is False
    assert storage.list_memory_edges() == []


# ── dedup heuristics ──────────────────────────────────────────────────────────


def test_dedup_detects_near_duplicate_by_token_overlap(sample_repo: Path) -> None:
    mem_a = _make_memory(
        mid="mem-a",
        title="Cache invalidation rule",
        summary="Always invalidate the cache when the worker updates state.",
        details="Always invalidate the cache when the worker updates state.",
        source_ref="src/cache.py",
        confidence=0.7,
    )
    mem_b = _make_memory(
        mid="mem-b",
        title="Cache invalidation rule",
        summary="Always invalidate cache when worker updates state.",
        details="Always invalidate cache when worker updates state.",
        source_ref="src/cache.py",
        confidence=0.5,
    )

    changed, edges, result = consolidate_memories([mem_a, mem_b], sample_repo)

    assert result.duplicates_detected >= 1
    dup_edges = [e for e in edges if e.edge_type == EdgeType.DUPLICATE_OF]
    assert len(dup_edges) >= 1
    # survivor should be mem_a (higher confidence)
    assert dup_edges[0].to_memory_id == "mem-a"
    assert dup_edges[0].from_memory_id == "mem-b"


def test_dedup_preserves_manual_over_non_manual(sample_repo: Path) -> None:
    """A MANUAL memory must survive even when it has lower confidence."""
    manual_mem = _make_memory(
        mid="mem-manual",
        title="Cache invalidation rule",
        summary="Always invalidate cache when worker updates state.",
        details="Always invalidate cache when worker updates state.",
        source_type=SourceType.MANUAL,
        confidence=0.4,
    )
    code_mem = _make_memory(
        mid="mem-code",
        title="Cache invalidation rule",
        summary="Always invalidate cache when worker updates state.",
        details="Always invalidate cache when worker updates state.",
        source_type=SourceType.CODE,
        confidence=0.9,
    )

    changed, edges, result = consolidate_memories([manual_mem, code_mem], sample_repo)

    dup_edges = [e for e in edges if e.edge_type == EdgeType.DUPLICATE_OF]
    assert len(dup_edges) >= 1
    # manual must be the survivor (to_memory_id)
    assert any(e.to_memory_id == "mem-manual" for e in dup_edges)

    # manual entry must not be retired (staleness = orphaned)
    changed_by_id = {m.id: m for m in changed}
    if "mem-manual" in changed_by_id:
        assert changed_by_id["mem-manual"].staleness != "orphaned"


def test_dedup_retires_non_protected_loser(sample_repo: Path) -> None:
    mem_a = _make_memory(
        mid="mem-hi",
        title="Invariant: boundary",
        summary="Never bypass cache boundary from workers.",
        details="Never bypass cache boundary from workers.",
        source_type=SourceType.CODE,
        confidence=0.8,
    )
    mem_b = _make_memory(
        mid="mem-lo",
        title="Invariant: boundary",
        summary="Never bypass cache boundary from workers.",
        details="Never bypass cache boundary from workers.",
        source_type=SourceType.CODE,
        confidence=0.4,
    )

    changed, edges, result = consolidate_memories([mem_a, mem_b], sample_repo)
    changed_by_id = {m.id: m for m in changed}

    # The loser (mem-lo) should be marked orphaned.
    assert "mem-lo" in changed_by_id
    assert changed_by_id["mem-lo"].staleness == "orphaned"


def test_dedup_carry_forward_max_confidence_and_sum_feedback(sample_repo: Path) -> None:
    mem_a = _make_memory(
        mid="ma",
        title="Shared token heavy wording same source ref anchor",
        summary="Cache must always be invalidated via boundary shared token heavy wording.",
        details="Cache must always be invalidated via boundary shared token heavy wording.",
        source_ref="src/cache.py",
        confidence=0.6,
        feedback_score=0.2,
    )
    mem_b = _make_memory(
        mid="mb",
        title="Shared token heavy wording same source ref anchor",
        summary="Cache must always be invalidated via boundary shared token heavy wording.",
        details="Cache must always be invalidated via boundary shared token heavy wording.",
        source_ref="src/cache.py",
        confidence=0.8,
        feedback_score=0.3,
    )

    changed, _, result = consolidate_memories([mem_a, mem_b], sample_repo)
    changed_by_id = {m.id: m for m in changed}

    # Survivor is mb (higher confidence).
    assert "mb" in changed_by_id
    # Merged feedback is 0.2 + 0.3 = 0.5; confidence is max(0.8, 0.6) = 0.8.
    # Note: promote may also run if feedback >= 0.3 threshold, bumping confidence further.
    assert changed_by_id["mb"].confidence >= 0.8
    assert changed_by_id["mb"].feedback_score == pytest.approx(0.5)


# ── promote / demote ──────────────────────────────────────────────────────────


def test_promote_high_feedback_memory(sample_repo: Path) -> None:
    mem = _make_memory(
        mid="mem-promo",
        title="High feedback memory",
        summary="This memory received positive feedback.",
        confidence=0.7,
        feedback_score=0.4,
        source_ref="src/cache.py",
    )

    changed, _, result = consolidate_memories([mem], sample_repo)
    changed_by_id = {m.id: m for m in changed}

    assert result.promoted >= 1
    assert "mem-promo" in changed_by_id
    assert changed_by_id["mem-promo"].confidence > 0.7


def test_demote_does_not_affect_protected_memories(sample_repo: Path) -> None:
    """MANUAL memories are never demoted even if their anchor file is gone."""
    mem = _make_memory(
        mid="mem-manual-safe",
        title="Manual preference",
        summary="A user preference that should not be demoted.",
        source_type=SourceType.MANUAL,
        source_ref="nonexistent_file.py",  # anchor missing -> would be orphaned
        confidence=0.9,
    )

    changed, _, result = consolidate_memories([mem], sample_repo)
    changed_by_id = {m.id: m for m in changed}

    # Protected memory must not be demoted.
    if "mem-manual-safe" in changed_by_id:
        assert changed_by_id["mem-manual-safe"].confidence >= 0.9


# ── contradiction edges ───────────────────────────────────────────────────────


def test_contradiction_edge_for_opposing_invariants(sample_repo: Path) -> None:
    # Use different source_refs and different summaries so dedup does not fire,
    # but the same title token set so topic-overlap is high.
    mem_do = _make_memory(
        mid="mem-do",
        kind=MemoryKind.INVARIANT,
        title="Cache boundary rule for workers in the system",
        # Unique enough summary: no shared tokens with mem_dont except in title.
        summary="Always route all worker updates through the centralized cache boundary layer.",
        details="Always route all worker updates through the centralized cache boundary layer.",
        source_ref="docs/architecture.md",
        confidence=0.6,
    )
    mem_dont = _make_memory(
        mid="mem-dont",
        kind=MemoryKind.INVARIANT,
        title="Cache boundary rule for workers in the system",
        # Contains negation marker; enough different tokens so not a near-dup.
        summary=(
            "Never allow workers to bypass the cache boundary under any circumstances whatsoever."
        ),
        details=(
            "Never allow workers to bypass the cache boundary under any circumstances whatsoever."
        ),
        source_ref="docs/architecture.md",
        confidence=0.6,
    )

    _, edges, result = consolidate_memories([mem_do, mem_dont], sample_repo)
    contra_edges = [e for e in edges if e.edge_type == EdgeType.CONTRADICTS]

    edge_summary = [(e.edge_type, e.from_memory_id, e.to_memory_id) for e in edges]
    assert len(contra_edges) >= 1, (
        f"Expected at least one CONTRADICTS edge, got edges: {edge_summary}"
    )
    assert result.edges_added[EdgeType.CONTRADICTS.value] >= 1


# ── relates edges ─────────────────────────────────────────────────────────────


def test_relates_edge_for_shared_source_ref(sample_repo: Path) -> None:
    mem_a = _make_memory(
        mid="mem-ra",
        kind=MemoryKind.DECISION,
        title="Design decision alpha",
        summary="We chose approach alpha for the cache module.",
        source_ref="src/cache.py",
    )
    mem_b = _make_memory(
        mid="mem-rb",
        kind=MemoryKind.GOTCHA,
        title="Gotcha about cache",
        summary="Cache module has a subtle flush ordering issue.",
        source_ref="src/cache.py",
    )

    _, edges, result = consolidate_memories([mem_a, mem_b], sample_repo)
    relates_edges = [e for e in edges if e.edge_type == EdgeType.RELATES]

    assert len(relates_edges) >= 1
    assert result.edges_added[EdgeType.RELATES.value] >= 1


# ── dry-run mode ──────────────────────────────────────────────────────────────


def test_consolidate_dry_run_makes_no_writes(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    # Seed two memories with the same source_ref so a RELATES edge will be generated.
    # They must have different content to produce distinct stable IDs.
    service.add_memory(
        kind=MemoryKind.DECISION,
        title="Cache invalidation rule",
        summary="Always invalidate cache when worker updates state.",
        source_ref="src/cache.py",
    )
    service.add_memory(
        kind=MemoryKind.GOTCHA,
        title="Cache flush ordering gotcha",
        summary="Flush ordering matters for correctness in the cache module invalidation path.",
        source_ref="src/cache.py",
    )

    _, result_dry = service.consolidate(dry_run=True)
    # Dry-run: no edges should be in the DB.
    from oh_no_my_claudecode.config import database_path, load_config
    from oh_no_my_claudecode.core.repo import discover_repo_root
    repo_root = discover_repo_root(sample_repo)
    config = load_config(repo_root)
    storage = SQLiteStorage(database_path(config, repo_root))
    storage.initialize()
    assert storage.list_memory_edges() == []

    # Now run for real — the two memories share source_ref so RELATES should fire.
    _, result_real = service.consolidate(dry_run=False)
    # Edges should now be persisted.
    assert len(storage.list_memory_edges()) > 0


# ── CLI consolidate command ───────────────────────────────────────────────────


def test_cli_consolidate_dry_run(sample_repo: Path, monkeypatch: object) -> None:
    runner = _runner()
    monkeypatch.chdir(sample_repo)
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["ingest"]).exit_code == 0

    result = runner.invoke(app, ["consolidate", "--dry-run"])
    assert result.exit_code == 0
    assert "dry-run" in result.output.lower() or "Memory consolidation" in result.output


def test_cli_consolidate_writes(sample_repo: Path, monkeypatch: object) -> None:
    runner = _runner()
    monkeypatch.chdir(sample_repo)
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["ingest"]).exit_code == 0

    result = runner.invoke(app, ["consolidate"])
    assert result.exit_code == 0
    assert "Memory consolidation" in result.output


# ── service consolidate ───────────────────────────────────────────────────────


def test_service_consolidate_returns_result(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    repo_root, result = service.consolidate(dry_run=False)
    assert isinstance(result, ConsolidationResult)
    assert repo_root.exists()
    assert result.total_edges() >= 0  # may be 0 on a fresh store with no duplicates


# ── ConsolidationResult summary ───────────────────────────────────────────────


def test_consolidation_result_summary_lines() -> None:
    result = ConsolidationResult(
        duplicates_detected=2,
        merged=1,
        promoted=3,
        demoted=1,
    )
    result.edges_added[EdgeType.DUPLICATE_OF.value] = 2
    result.edges_added[EdgeType.CONTRADICTS.value] = 1

    lines = result.summary_lines()
    assert any("2" in line for line in lines)  # duplicates
    assert any("Promoted" in line for line in lines)
    total = result.total_edges()
    assert total == 3
