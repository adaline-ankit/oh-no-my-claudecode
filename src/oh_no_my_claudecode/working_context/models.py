"""Versioned working-state and context-delivery contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NoteKind = Literal["decision", "hypothesis", "next_step"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkingConfig(StrictModel):
    schema_version: Literal[1] = 1
    enabled: bool = False
    budget_chars: int = Field(default=6000, ge=1000, le=32000)
    constraints: list[str] = Field(default_factory=list, max_length=32)


class AnchorBinding(StrictModel):
    memory_digest: str
    files: dict[str, str]


class WorkingNote(StrictModel):
    id: str
    kind: NoteKind
    text: str
    anchors: dict[str, str] = Field(default_factory=dict)


class WorkingSession(StrictModel):
    schema_version: Literal[1] = 1
    session_id: str
    goal: str
    constraints: list[str] = Field(default_factory=list)
    focus: str = ""
    active_files: list[str] = Field(default_factory=list)
    notes: list[WorkingNote] = Field(default_factory=list)
    pruned_notes: int = 0
    revision: int = 0
    bindings: dict[str, AnchorBinding] = Field(default_factory=dict)
    last_selected: list[str] = Field(default_factory=list)
    last_fingerprint: str = ""
    # Withdrawals remain visible until the source becomes eligible again.
    withdrawals: dict[str, str] = Field(default_factory=dict)


class ContextItem(StrictModel):
    id: str
    kind: str
    text: str
    source: str
    freshness: str
    score: float
    reason: str


class ContextExclusion(StrictModel):
    id: str
    reason: str


class ContextPacket(StrictModel):
    schema_version: Literal[1] = 1
    session_id: str
    revision: int
    markdown: str
    injection: str
    changed: bool
    budget_chars: int
    used_chars: int
    estimated_tokens: int
    selected: list[ContextItem]
    excluded: list[ContextExclusion]
    withdrawn: list[str]
    warnings: list[str]
