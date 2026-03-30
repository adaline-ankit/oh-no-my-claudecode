from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from oh_no_my_claudecode.models import AttemptRecord, MemoryArtifactRecord, MemoryEntry, TaskRecord


class ExportCounts(BaseModel):
    memories: int
    tasks: int
    attempts: int
    artifacts: int


class SyncManifest(BaseModel):
    version: str = "1"
    repo_root: str
    exported_at: datetime
    onmc_version: str
    counts: ExportCounts


class ExportedMemoryRecord(BaseModel):
    memory: MemoryEntry


class ExportedTaskRecord(BaseModel):
    task: TaskRecord
    attempts: list[AttemptRecord] = Field(default_factory=list)
    artifacts: list[MemoryArtifactRecord] = Field(default_factory=list)


class SyncResult(BaseModel):
    output_dir: str
    memory_count: int
    task_count: int
    attempt_count: int
    artifact_count: int
    latest_brief_path: str | None = None
