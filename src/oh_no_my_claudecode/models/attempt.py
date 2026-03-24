from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AttemptKind(StrEnum):
    FIX_ATTEMPT = "fix_attempt"
    INVESTIGATION = "investigation"
    TEST_STRATEGY = "test_strategy"
    REFACTOR_ATTEMPT = "refactor_attempt"
    OTHER = "other"


class AttemptStatus(StrEnum):
    PROPOSED = "proposed"
    TRIED = "tried"
    REJECTED = "rejected"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"


TERMINAL_ATTEMPT_STATUSES = {
    AttemptStatus.REJECTED,
    AttemptStatus.SUCCEEDED,
    AttemptStatus.PARTIAL,
}


class AttemptRecord(BaseModel):
    attempt_id: str
    task_id: str
    summary: str
    kind: AttemptKind
    status: AttemptStatus
    reasoning_summary: str | None = None
    evidence_for: str | None = None
    evidence_against: str | None = None
    files_touched: list[str] = Field(default_factory=list)
    created_at: datetime
    closed_at: datetime | None = None

    def update(
        self,
        *,
        changed_at: datetime,
        summary: str | None = None,
        kind: AttemptKind | None = None,
        status: AttemptStatus | None = None,
        reasoning_summary: str | None = None,
        evidence_for: str | None = None,
        evidence_against: str | None = None,
        files_touched: list[str] | None = None,
    ) -> AttemptRecord:
        next_status = status or self.status
        if status is None:
            closed_at = self.closed_at
        elif next_status in TERMINAL_ATTEMPT_STATUSES:
            closed_at = self.closed_at or changed_at
        else:
            closed_at = None

        return self.model_copy(
            update={
                "summary": summary if summary is not None else self.summary,
                "kind": kind if kind is not None else self.kind,
                "status": next_status,
                "reasoning_summary": (
                    reasoning_summary
                    if reasoning_summary is not None
                    else self.reasoning_summary
                ),
                "evidence_for": (
                    evidence_for if evidence_for is not None else self.evidence_for
                ),
                "evidence_against": (
                    evidence_against
                    if evidence_against is not None
                    else self.evidence_against
                ),
                "files_touched": (
                    files_touched if files_touched is not None else self.files_touched
                ),
                "closed_at": closed_at,
            }
        )
