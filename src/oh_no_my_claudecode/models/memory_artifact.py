from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MemoryArtifactType(StrEnum):
    FIX = "fix"
    DID_NOT_WORK = "did_not_work"
    DESIGN_CONFLICT = "design_conflict"
    GOTCHA = "gotcha"
    INVARIANT = "invariant"
    VALIDATION = "validation"


class MemoryArtifactRecord(BaseModel):
    memory_id: str
    task_id: str
    type: MemoryArtifactType
    title: str
    summary: str
    why_it_matters: str
    apply_when: str | None = None
    avoid_when: str | None = None
    evidence: str
    related_files: list[str] = Field(default_factory=list)
    related_modules: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime
