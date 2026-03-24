from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RepoFileRecord(BaseModel):
    path: str
    extension: str | None = None
    is_test: bool = False
    size_bytes: int = 0


class FileStat(BaseModel):
    path: str
    change_count: int = 0
    recent_change_count: int = 0
    last_modified_at: datetime | None = None
    is_test: bool = False
    top_level_dir: str = "."


class ProjectHints(BaseModel):
    python_tools: list[str] = Field(default_factory=list)
    package_scripts: list[str] = Field(default_factory=list)
    ci_workflows: list[str] = Field(default_factory=list)
    test_directories: list[str] = Field(default_factory=list)
    source_directories: list[str] = Field(default_factory=list)


class IngestResult(BaseModel):
    memory_count: int
    new_memory_count: int
    updated_memory_count: int
    repo_file_count: int
    file_stat_count: int
    doc_count: int
    commit_count: int
    generated_at: datetime
    notes: list[str] = Field(default_factory=list)
