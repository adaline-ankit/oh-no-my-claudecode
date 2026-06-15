from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PlaybookProvenanceItem(BaseModel):
    """A single memory that grounds a playbook."""

    memory_id: str
    title: str
    kind: str


class Playbook(BaseModel):
    """A reusable, provenance-tracked playbook synthesized from confirmed memory."""

    id: str
    title: str
    # "When to use this" — short trigger sentence
    trigger: str
    # Ordered list of concrete actions
    steps: list[str] = Field(default_factory=list)
    # Provenance: source memory records
    grounded_in: list[PlaybookProvenanceItem] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    # Derived from backing memories (0.0–1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime
