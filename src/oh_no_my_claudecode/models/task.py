from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    OPEN = "open"
    ACTIVE = "active"
    BLOCKED = "blocked"
    SOLVED = "solved"
    ABANDONED = "abandoned"


TERMINAL_TASK_STATUSES = {
    TaskStatus.SOLVED,
    TaskStatus.ABANDONED,
}


class TaskLifecycleError(ValueError):
    """Raised when an invalid task status transition is requested."""


class TaskRecord(BaseModel):
    task_id: str
    title: str
    description: str
    status: TaskStatus
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    repo_root: str
    branch: str
    labels: list[str] = Field(default_factory=list)
    final_summary: str | None = None
    final_outcome: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    def transition(
        self,
        next_status: TaskStatus,
        *,
        changed_at: datetime,
        final_summary: str | None = None,
        final_outcome: str | None = None,
        confidence: float | None = None,
    ) -> TaskRecord:
        if not can_transition_task(self.status, next_status):
            msg = f"Cannot transition task from {self.status.value} to {next_status.value}."
            raise TaskLifecycleError(msg)

        started_at = self.started_at
        ended_at = self.ended_at
        if next_status == TaskStatus.ACTIVE and started_at is None:
            started_at = changed_at
        if next_status in TERMINAL_TASK_STATUSES:
            ended_at = ended_at or changed_at

        return self.model_copy(
            update={
                "status": next_status,
                "started_at": started_at,
                "ended_at": ended_at,
                "final_summary": final_summary
                if final_summary is not None
                else self.final_summary,
                "final_outcome": final_outcome
                if final_outcome is not None
                else self.final_outcome,
                "confidence": confidence if confidence is not None else self.confidence,
            }
        )


def can_transition_task(current: TaskStatus, next_status: TaskStatus) -> bool:
    if current == next_status:
        return True

    allowed_transitions = {
        TaskStatus.OPEN: {
            TaskStatus.ACTIVE,
            TaskStatus.BLOCKED,
            TaskStatus.SOLVED,
            TaskStatus.ABANDONED,
        },
        TaskStatus.ACTIVE: {
            TaskStatus.BLOCKED,
            TaskStatus.SOLVED,
            TaskStatus.ABANDONED,
        },
        TaskStatus.BLOCKED: {
            TaskStatus.ACTIVE,
            TaskStatus.SOLVED,
            TaskStatus.ABANDONED,
        },
        TaskStatus.SOLVED: set(),
        TaskStatus.ABANDONED: set(),
    }
    return next_status in allowed_transitions[current]
