from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now


def test_storage_round_trip(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "memory.db")
    storage.initialize()
    now = utc_now()
    memory = MemoryEntry(
        id="doc-1",
        kind=MemoryKind.DOC_FACT,
        title="README fact",
        summary="A useful fact",
        details="Details",
        source_type=SourceType.DOC,
        source_ref="README.md",
        tags=["readme"],
        confidence=0.7,
        created_at=now,
        updated_at=now,
    )

    new_count, updated_count = storage.upsert_memories([memory])

    assert new_count == 1
    assert updated_count == 0
    assert storage.memory_count() == 1
    assert storage.get_memory("doc-1") is not None
    storage.set_meta("last_ingest_at", "2026-03-24T00:00:00+00:00")
    assert storage.get_meta("last_ingest_at") == "2026-03-24T00:00:00+00:00"


def test_replace_generated_memories_preserves_manual_entries(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "memory.db")
    storage.initialize()
    now = utc_now()
    manual = MemoryEntry(
        id="manual-1",
        kind=MemoryKind.INVARIANT,
        title="Manual note",
        summary="Keep this",
        details="Keep this",
        source_type=SourceType.MANUAL,
        source_ref="manual",
        tags=[],
        confidence=1.0,
        created_at=now,
        updated_at=now,
    )
    generated = MemoryEntry(
        id="doc-1",
        kind=MemoryKind.DOC_FACT,
        title="Generated note",
        summary="Replace this",
        details="Replace this",
        source_type=SourceType.DOC,
        source_ref="README.md",
        tags=[],
        confidence=0.7,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([manual, generated])

    replacement = MemoryEntry(
        id="doc-2",
        kind=MemoryKind.DOC_FACT,
        title="New generated note",
        summary="New note",
        details="New note",
        source_type=SourceType.DOC,
        source_ref="docs/architecture.md",
        tags=[],
        confidence=0.8,
        created_at=now,
        updated_at=now,
    )
    storage.replace_generated_memories([replacement])

    ids = {memory.id for memory in storage.list_memories()}
    assert ids == {"manual-1", "doc-2"}
