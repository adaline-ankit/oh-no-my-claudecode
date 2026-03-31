from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


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
    created_at: datetime
    updated_at: datetime
