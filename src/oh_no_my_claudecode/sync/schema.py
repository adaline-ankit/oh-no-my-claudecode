from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from oh_no_my_claudecode.models import AttemptRecord, MemoryArtifactRecord, MemoryEntry, TaskRecord
from oh_no_my_claudecode.models.skill import Skill, SkillProvenanceItem


class ExportCounts(BaseModel):
    memories: int
    tasks: int
    attempts: int
    artifacts: int
    skills: int = 0


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


class ExportedSkillRecord(BaseModel):
    """A single skill exported to .agent-memory/skills/<id>.json."""

    skill: Skill
    # Provenance items reconstructed from source_memory_ids for any reader that
    # does not have direct access to this repo's memory database.
    provenance: list[SkillProvenanceItem] = Field(default_factory=list)


class SyncResult(BaseModel):
    output_dir: str
    memory_count: int
    task_count: int
    attempt_count: int
    artifact_count: int
    skill_count: int = 0
    latest_brief_path: str | None = None
