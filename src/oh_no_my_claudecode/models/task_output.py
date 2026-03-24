from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class TaskOutputType(StrEnum):
    SOLVE_OUTPUT = "solve_output"
    REVIEW_OUTPUT = "review_output"
    TEACHING_OUTPUT = "teaching_output"


class TaskOutputRecord(BaseModel):
    output_id: str
    task_id: str | None = None
    type: TaskOutputType
    task_text: str
    provider: str
    model: str
    summary: str
    content_json: str
    markdown_path: str
    created_at: datetime
