from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CompactionSnapshotRecord(BaseModel):
    id: str
    task_id: str | None = None
    timestamp: datetime
    active_files: list[str] = Field(default_factory=list)
    recent_decisions: list[str] = Field(default_factory=list)
    working_hypothesis: str | None = None
    last_error_trace: str | None = None
    next_step: str | None = None
    brief_token_count: int | None = None
    continuation_brief_md: str | None = None


class HookStatus(BaseModel):
    installed: bool
    backup_path: str
    settings_path: str
    latest_snapshot_id: str | None = None
    last_pre_compact_at: str | None = None
    last_post_compact_at: str | None = None
