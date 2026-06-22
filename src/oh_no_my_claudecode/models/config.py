from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from oh_no_my_claudecode.models.llm import LLMSettings


class NotifySinkType(StrEnum):
    """Available sink types for the context firewall."""

    FILE = "file"
    DISCORD = "discord"
    SLACK = "slack"
    NONE = "none"


class NotifySettings(BaseModel):
    """Configuration for the context firewall notification subsystem.

    Precedence: env vars > config.yaml > these defaults.

    Env vars
    --------
    ``ONMC_NOTIFY_ENABLED`` — "0"/"false"/"no" to disable.
    ``ONMC_NOTIFY_SINK``    — "file" | "discord" | "slack" | "none".
    ``ONMC_DISCORD_WEBHOOK`` — Discord incoming webhook URL.
    ``ONMC_SLACK_WEBHOOK``  — Slack incoming webhook URL.
    """

    enabled: bool = True
    sink: NotifySinkType = NotifySinkType.FILE
    discord_webhook: str | None = None
    slack_webhook: str | None = None


class StorageSettings(BaseModel):
    state_dir: str = ".onmc"
    database_path: str = ".onmc/memory.db"
    compiled_dir: str = ".onmc/compiled"
    logs_dir: str = ".onmc/logs"


class IngestSettings(BaseModel):
    doc_globs: list[str] = Field(
        default_factory=lambda: [
            "README*",
            "docs/**/*.md",
            "AGENTS.md",
            "CLAUDE.md",
            "**/*architecture*.md",
        ]
    )
    source_extensions: list[str] = Field(
        default_factory=lambda: [
            ".py",
            ".pyi",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".go",
            ".rs",
            ".java",
            ".rb",
        ]
    )
    exclude_dirs: list[str] = Field(
        default_factory=lambda: [
            ".git",
            ".onmc",
            ".venv",
            "venv",
            "node_modules",
            "dist",
            "build",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
        ]
    )
    max_doc_section_chars: int = 1200
    max_git_commits: int = 300


class BriefSettings(BaseModel):
    max_memories: int = 8
    max_files: int = 10
    max_risks: int = 5
    max_patterns: int = 5


class ProjectConfig(BaseModel):
    version: int = 1
    repo_root: str
    storage: StorageSettings = Field(default_factory=StorageSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    brief: BriefSettings = Field(default_factory=BriefSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    notify: NotifySettings = Field(default_factory=NotifySettings)
