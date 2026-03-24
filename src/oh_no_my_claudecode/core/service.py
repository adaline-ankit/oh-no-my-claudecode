from __future__ import annotations

import secrets
from pathlib import Path

from oh_no_my_claudecode.brief.compiler import compile_brief
from oh_no_my_claudecode.config import (
    compiled_dir,
    config_exists,
    create_state_dirs,
    database_path,
    default_config,
    load_config,
    state_dir,
    write_config,
)
from oh_no_my_claudecode.core.repo import current_branch, discover_repo_root
from oh_no_my_claudecode.ingest.pipeline import run_ingest
from oh_no_my_claudecode.llm import default_api_key_env_var, llm_status, provider_from_settings
from oh_no_my_claudecode.llm.base import BaseLLMProvider
from oh_no_my_claudecode.memory.catalog import MemoryCatalog
from oh_no_my_claudecode.models import (
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_TASK_STATUSES,
    AgentMode,
    AttemptKind,
    AttemptRecord,
    AttemptStatus,
    BriefArtifact,
    CompiledPrompt,
    IngestResult,
    LLMProviderType,
    LLMSettings,
    LLMStatus,
    MemoryArtifactRecord,
    MemoryArtifactType,
    MemoryEntry,
    MemoryKind,
    ProjectConfig,
    TaskLifecycleError,
    TaskRecord,
    TaskStatus,
)
from oh_no_my_claudecode.prompt import compile_prompt
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now


class OnmcService:
    def __init__(self, cwd: Path | None = None) -> None:
        self.cwd = cwd or Path.cwd()

    def init_project(self) -> tuple[Path, ProjectConfig]:
        repo_root = discover_repo_root(self.cwd)
        config = load_config(repo_root) if config_exists(repo_root) else default_config(repo_root)
        create_state_dirs(config, repo_root)
        write_config(config, repo_root)
        storage = SQLiteStorage(database_path(config, repo_root))
        storage.initialize()
        storage.set_meta("initialized_at", isoformat_utc(utc_now()))
        return repo_root, config

    def ingest(self) -> tuple[Path, IngestResult]:
        repo_root, config, storage = self._load_context()
        return repo_root, run_ingest(repo_root, config, storage)

    def compile_brief(self, task: str) -> tuple[Path, BriefArtifact]:
        repo_root, config, storage = self._load_context()
        artifact = compile_brief(repo_root, config, storage, task)
        output_name = f"{utc_now().strftime('%Y%m%d-%H%M%S')}-brief.md"
        output_path = compiled_dir(config, repo_root) / output_name
        output_path.write_text(artifact.to_markdown(), encoding="utf-8")
        artifact.output_path = output_path.as_posix()
        return repo_root, artifact

    def list_memories(self, *, kind: MemoryKind | None = None) -> list[MemoryEntry]:
        _, _, storage = self._load_context()
        return MemoryCatalog(storage).list(kind=kind)

    def get_memory(self, memory_id: str) -> MemoryEntry | None:
        _, _, storage = self._load_context()
        return MemoryCatalog(storage).get(memory_id)

    def configure_llm(
        self,
        *,
        provider: LLMProviderType,
        model: str,
        api_key_env_var: str | None,
        temperature: float,
        max_tokens: int,
    ) -> tuple[Path, LLMSettings]:
        repo_root, config, _ = self._load_context()
        settings = LLMSettings(
            provider=provider,
            model=model,
            api_key_env_var=api_key_env_var or default_api_key_env_var(provider),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        updated_config = config.model_copy(update={"llm": settings})
        write_config(updated_config, repo_root)
        return repo_root, settings

    def llm_status(self) -> tuple[Path, LLMStatus]:
        repo_root, config, _ = self._load_context()
        return repo_root, llm_status(config.llm)

    def llm_provider(self) -> BaseLLMProvider:
        _, config, _ = self._load_context()
        return provider_from_settings(config.llm)

    def compile_task_prompt(self, task_id: str, mode: AgentMode) -> CompiledPrompt:
        repo_root, config, storage = self._load_context()
        task = self._require_task(storage, task_id)
        attempts = storage.list_attempts_for_task(task_id)
        memory_artifacts = storage.list_memory_artifacts_for_task(task_id)
        brief_task = f"{task.title}. {task.description}"
        brief = compile_brief(repo_root, config, storage, brief_task)
        return compile_prompt(
            mode=mode,
            task=task,
            brief=brief,
            attempts=attempts,
            memory_artifacts=memory_artifacts,
        )

    def add_memory_artifact(
        self,
        task_id: str,
        *,
        artifact_type: MemoryArtifactType,
        title: str,
        summary: str,
        why_it_matters: str,
        apply_when: str | None,
        avoid_when: str | None,
        evidence: str,
        related_files: list[str],
        related_modules: list[str],
        confidence: float,
    ) -> MemoryArtifactRecord:
        _, _, storage = self._load_context()
        self._require_task(storage, task_id)
        artifact = MemoryArtifactRecord(
            memory_id=f"artifact-{secrets.token_hex(5)}",
            task_id=task_id,
            type=artifact_type,
            title=title,
            summary=summary,
            why_it_matters=why_it_matters,
            apply_when=apply_when,
            avoid_when=avoid_when,
            evidence=evidence,
            related_files=related_files,
            related_modules=related_modules,
            confidence=confidence,
            created_at=utc_now(),
        )
        storage.create_memory_artifact(artifact)
        return artifact

    def list_memory_artifacts(
        self,
        *,
        artifact_type: MemoryArtifactType | None = None,
    ) -> list[MemoryArtifactRecord]:
        _, _, storage = self._load_context()
        return storage.list_memory_artifacts(artifact_type=artifact_type)

    def list_memory_artifacts_for_task(self, task_id: str) -> list[MemoryArtifactRecord]:
        _, _, storage = self._load_context()
        self._require_task(storage, task_id)
        return storage.list_memory_artifacts_for_task(task_id)

    def get_memory_artifact(self, memory_id: str) -> MemoryArtifactRecord | None:
        _, _, storage = self._load_context()
        return storage.get_memory_artifact(memory_id)

    def add_attempt(
        self,
        task_id: str,
        *,
        summary: str,
        kind: AttemptKind,
        status: AttemptStatus,
        reasoning_summary: str | None,
        evidence_for: str | None,
        evidence_against: str | None,
        files_touched: list[str],
    ) -> AttemptRecord:
        _, _, storage = self._load_context()
        self._require_task(storage, task_id)
        now = utc_now()
        attempt = AttemptRecord(
            attempt_id=f"attempt-{secrets.token_hex(5)}",
            task_id=task_id,
            summary=summary,
            kind=kind,
            status=status,
            reasoning_summary=reasoning_summary,
            evidence_for=evidence_for,
            evidence_against=evidence_against,
            files_touched=files_touched,
            created_at=now,
            closed_at=now if status in TERMINAL_ATTEMPT_STATUSES else None,
        )
        storage.create_attempt(attempt)
        return attempt

    def list_attempts_for_task(self, task_id: str) -> list[AttemptRecord]:
        _, _, storage = self._load_context()
        self._require_task(storage, task_id)
        return storage.list_attempts_for_task(task_id)

    def get_attempt(self, attempt_id: str) -> AttemptRecord | None:
        _, _, storage = self._load_context()
        return storage.get_attempt(attempt_id)

    def update_attempt(
        self,
        attempt_id: str,
        *,
        status: AttemptStatus | None = None,
        summary: str | None = None,
        reasoning_summary: str | None = None,
        evidence_for: str | None = None,
        evidence_against: str | None = None,
        files_touched: list[str] | None = None,
    ) -> AttemptRecord:
        _, _, storage = self._load_context()
        attempt = self._require_attempt(storage, attempt_id)
        updated = attempt.update(
            changed_at=utc_now(),
            status=status,
            summary=summary,
            reasoning_summary=reasoning_summary,
            evidence_for=evidence_for,
            evidence_against=evidence_against,
            files_touched=files_touched,
        )
        storage.update_attempt(updated)
        return updated

    def start_task(
        self,
        *,
        title: str,
        description: str,
        labels: list[str],
    ) -> TaskRecord:
        repo_root, _, storage = self._load_context()
        now = utc_now()
        task = TaskRecord(
            task_id=f"task-{secrets.token_hex(5)}",
            title=title,
            description=description,
            status=TaskStatus.ACTIVE,
            created_at=now,
            started_at=now,
            ended_at=None,
            repo_root=repo_root.as_posix(),
            branch=current_branch(repo_root),
            labels=labels,
            final_summary=None,
            final_outcome=None,
            confidence=None,
        )
        storage.create_task(task)
        return task

    def list_tasks(self) -> list[TaskRecord]:
        _, _, storage = self._load_context()
        return storage.list_tasks()

    def get_task(self, task_id: str) -> TaskRecord | None:
        _, _, storage = self._load_context()
        return storage.get_task(task_id)

    def attempt_counts_by_task(self) -> dict[str, int]:
        _, _, storage = self._load_context()
        return storage.list_attempt_counts_by_task()

    def memory_artifact_counts_by_task(self) -> dict[str, int]:
        _, _, storage = self._load_context()
        return storage.list_memory_artifact_counts_by_task()

    def update_task_status(self, task_id: str, status: TaskStatus) -> TaskRecord:
        if status == TaskStatus.OPEN:
            msg = (
                "Task status updates do not support `open`; use active, blocked, "
                "solved, or abandoned."
            )
            raise TaskLifecycleError(msg)
        _, _, storage = self._load_context()
        task = self._require_task(storage, task_id)
        updated = task.transition(status, changed_at=utc_now())
        storage.update_task(updated)
        return updated

    def end_task(
        self,
        task_id: str,
        *,
        status: TaskStatus,
        summary: str,
    ) -> TaskRecord:
        if status not in TERMINAL_TASK_STATUSES:
            msg = "Task end only supports terminal statuses: solved or abandoned."
            raise TaskLifecycleError(msg)
        _, _, storage = self._load_context()
        task = self._require_task(storage, task_id)
        updated = task.transition(
            status,
            changed_at=utc_now(),
            final_summary=summary,
        )
        storage.update_task(updated)
        return updated

    def status(self) -> dict[str, str]:
        repo_root, config, storage = self._load_context()
        meta = storage.all_meta()
        return {
            "repo_root": repo_root.as_posix(),
            "memories": str(storage.memory_count()),
            "tasks": str(storage.task_count()),
            "attempts": str(storage.attempt_count()),
            "memory_artifacts": str(storage.memory_artifact_count()),
            "last_ingest_at": meta.get("last_ingest_at", "never"),
            "storage_path": database_path(config, repo_root).as_posix(),
            "state_dir": state_dir(config, repo_root).as_posix(),
            "doc_globs": ", ".join(config.ingest.doc_globs),
            "max_brief_memories": str(config.brief.max_memories),
        }

    def _load_context(self) -> tuple[Path, ProjectConfig, SQLiteStorage]:
        repo_root = discover_repo_root(self.cwd)
        if not config_exists(repo_root):
            msg = "ONMC is not initialized. Run `onmc init` first."
            raise FileNotFoundError(msg)
        config = load_config(repo_root)
        create_state_dirs(config, repo_root)
        storage = SQLiteStorage(database_path(config, repo_root))
        storage.initialize()
        return repo_root, config, storage

    @staticmethod
    def _require_task(storage: SQLiteStorage, task_id: str) -> TaskRecord:
        task = storage.get_task(task_id)
        if task is None:
            msg = f"Task not found: {task_id}"
            raise LookupError(msg)
        return task

    @staticmethod
    def _require_attempt(storage: SQLiteStorage, attempt_id: str) -> AttemptRecord:
        attempt = storage.get_attempt(attempt_id)
        if attempt is None:
            msg = f"Attempt not found: {attempt_id}"
            raise LookupError(msg)
        return attempt
