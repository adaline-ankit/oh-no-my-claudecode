from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

StalenessLabel = Literal["fresh", "stale", "orphaned", "unanchored"]


class MemoryKind(StrEnum):
    DOC_FACT = "doc_fact"
    DECISION = "decision"
    INVARIANT = "invariant"
    HOTSPOT = "hotspot"
    GIT_PATTERN = "git_pattern"
    VALIDATION_RULE = "validation_rule"
    FAILED_APPROACH = "failed_approach"
    DESIGN_CONFLICT = "design_conflict"
    GOTCHA = "gotcha"


class SourceType(StrEnum):
    GIT = "git"
    DOC = "doc"
    CODE = "code"
    MANUAL = "manual"
    MANUAL_SEED = "manual_seed"
    LLM_EXTRACTED = "llm_extracted"
    TRANSCRIPT = "transcript"
    GITHUB_PR = "github_pr"
    SESSION = "session"


class MemoryEntry(BaseModel):
    id: str
    kind: MemoryKind
    title: str
    summary: str
    details: str
    source_type: SourceType
    source_ref: str
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    feedback_score: float = 0.0
    created_at: datetime
    updated_at: datetime
    staleness: StalenessLabel | None = None
    last_verified_at: datetime | None = None
