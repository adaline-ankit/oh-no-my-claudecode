from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

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


class FederationSource(BaseModel):
    """A single configured federation source (local path or git URL).

    Accepts either a bare string (resolved to ``source``) or an object with
    optional ``label`` and ``ref`` fields::

        # bare string form in config.yaml:
        federation:
          sources:
            - ../sibling-repo
            - https://github.com/org/shared-brain

        # object form with overrides:
        federation:
          sources:
            - path_or_url: ../sibling-repo
              label: sibling
            - path_or_url: https://github.com/org/shared-brain
              label: shared
              ref: main
    """

    path_or_url: str
    """Local filesystem path or remote git URL."""

    label: str | None = None
    """Optional override for the ``federated:<label>`` tag."""

    ref: str | None = None
    """Branch/tag/commit to check out when cloning (git URLs only)."""


class FederationSettings(BaseModel):
    """Federation configuration block in config.yaml.

    Example::

        federation:
          sources:
            - ../sibling-repo
            - path_or_url: https://github.com/org/brain
              label: shared-brain
              ref: main
    """

    sources: list[FederationSource] = Field(default_factory=list)
    """Ordered list of federation sources to pull when ``onmc pull --all`` is run."""

    @model_validator(mode="before")
    @classmethod
    def _coerce_bare_strings(cls, data: object) -> object:
        """Allow a source list entry to be a plain string (treated as path_or_url)."""
        if not isinstance(data, dict):
            return data
        raw_sources = data.get("sources")
        if not isinstance(raw_sources, list):
            return data
        coerced: list[object] = []
        for item in raw_sources:
            if isinstance(item, str):
                coerced.append({"path_or_url": item})
            else:
                coerced.append(item)
        return {**data, "sources": coerced}


class ProjectConfig(BaseModel):
    version: int = 1
    repo_root: str
    storage: StorageSettings = Field(default_factory=StorageSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    brief: BriefSettings = Field(default_factory=BriefSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    notify: NotifySettings = Field(default_factory=NotifySettings)
    federation: FederationSettings = Field(default_factory=FederationSettings)
