from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class EdgeType(StrEnum):
    """Directed relationship types between memory entries."""

    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    RELATES = "relates"
    DUPLICATE_OF = "duplicate_of"


class MemoryEdge(BaseModel):
    """A directed edge in the memory relationship graph."""

    id: str
    from_memory_id: str
    to_memory_id: str
    edge_type: EdgeType
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    created_at: datetime
