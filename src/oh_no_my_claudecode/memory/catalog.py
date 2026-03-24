from __future__ import annotations

from oh_no_my_claudecode.models import MemoryEntry, MemoryKind
from oh_no_my_claudecode.storage import SQLiteStorage


class MemoryCatalog:
    def __init__(self, storage: SQLiteStorage) -> None:
        self.storage = storage

    def list(self, *, kind: MemoryKind | None = None) -> list[MemoryEntry]:
        return self.storage.list_memories(kind=kind)

    def get(self, memory_id: str) -> MemoryEntry | None:
        return self.storage.get_memory(memory_id)
