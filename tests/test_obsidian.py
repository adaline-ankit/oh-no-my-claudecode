from __future__ import annotations

import uuid
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import MemoryKind, SourceType
from oh_no_my_claudecode.models.memory import MemoryEntry
from oh_no_my_claudecode.models.memory_edge import EdgeType, MemoryEdge
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now
from oh_no_my_claudecode.wiki import build_obsidian_vault


def _memory(title: str, *, kind: MemoryKind, source_ref: str) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=str(uuid.uuid4()),
        kind=kind,
        title=title,
        summary=f"Summary for {title}.",
        details=f"Detailed evidence for {title}.",
        source_type=SourceType.CODE,
        source_ref=source_ref,
        tags=["cache", "agent-memory"],
        confidence=0.9,
        feedback_score=0.0,
        created_at=now,
        updated_at=now,
    )


def _vault_storage(tmp_path: Path) -> tuple[SQLiteStorage, list[MemoryEntry]]:
    storage = SQLiteStorage(tmp_path / "memory.db")
    storage.initialize()
    memories = [
        _memory(
            "Keep cache boundary",
            kind=MemoryKind.INVARIANT,
            source_ref="src/cache.py",
        ),
        _memory(
            "Direct writes failed",
            kind=MemoryKind.FAILED_APPROACH,
            source_ref="src/worker.py",
        ),
    ]
    storage.upsert_memories(memories)
    storage.upsert_memory_edge(
        MemoryEdge(
            id=str(uuid.uuid4()),
            from_memory_id=memories[0].id,
            to_memory_id=memories[1].id,
            edge_type=EdgeType.RELATES,
            confidence=0.8,
            created_at=utc_now(),
        )
    )
    return storage, memories


def test_obsidian_vault_has_home_graph_and_memory_notes(
    tmp_path: Path,
    sample_repo: Path,
) -> None:
    storage, memories = _vault_storage(tmp_path)

    pages = build_obsidian_vault(storage, sample_repo)

    assert "Home.md" in pages
    assert "Graph.md" in pages
    memory_pages = {path: body for path, body in pages.items() if path.startswith("Memories/")}
    assert len(memory_pages) == len(memories)
    assert all(body.startswith("---\n") for body in memory_pages.values())
    assert all("onmc-memory" in body for body in memory_pages.values())


def test_obsidian_memory_notes_link_relationships(
    tmp_path: Path,
    sample_repo: Path,
) -> None:
    storage, _ = _vault_storage(tmp_path)

    pages = build_obsidian_vault(storage, sample_repo)

    invariant_note = next(
        body for path, body in pages.items() if path.startswith("Memories/keep-cache-boundary-")
    )
    failed_note_path = next(
        path
        for path, body in pages.items()
        if path.startswith("Memories/") and "Direct writes" in body
    )
    failed_note_name = Path(failed_note_path).stem
    assert f"[[{failed_note_name}|Direct writes failed]]" in invariant_note
    assert "relates" in invariant_note


def test_obsidian_duplicate_titles_get_unique_note_paths(
    tmp_path: Path,
    sample_repo: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "memory.db")
    storage.initialize()
    first = _memory("Same decision", kind=MemoryKind.DECISION, source_ref="src/a.py")
    second = _memory("Same decision", kind=MemoryKind.DECISION, source_ref="src/b.py")
    storage.upsert_memories(
        [
            first.model_copy(update={"id": "decision-aaaaaaaa11111111"}),
            second.model_copy(update={"id": "decision-bbbbbbbb22222222"}),
        ]
    )

    pages = build_obsidian_vault(storage, sample_repo)

    note_paths = [path for path in pages if path.startswith("Memories/")]
    assert len(note_paths) == 2
    assert len(set(note_paths)) == 2


def test_generate_wiki_obsidian_defaults_to_private_vault(sample_repo: Path) -> None:
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest(no_llm=True)

    _, written = service.generate_wiki(format="obsidian")

    vault_dir = sample_repo / ".onmc" / "obsidian"
    assert (vault_dir / "Home.md").exists()
    assert all(path.is_relative_to(vault_dir) for path in written)


def test_wiki_cli_exports_obsidian_vault(
    sample_repo: Path,
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest(no_llm=True)
    output = tmp_path / "repo-brain"

    result = CliRunner().invoke(
        app,
        ["wiki", "--format", "obsidian", "--output", str(output)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert (output / "Home.md").exists()
    assert "Obsidian vault generated" in result.output
