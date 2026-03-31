from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import TypeVar

from oh_no_my_claudecode.brief.compiler import compile_brief, score_memories
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
from oh_no_my_claudecode.hooks import (
    build_compaction_snapshot,
    claude_settings_backup_path,
    claude_settings_path,
    compile_continuation_brief,
    install_claude_hooks,
    uninstall_claude_hooks,
    write_continuation_brief,
)
from oh_no_my_claudecode.ingest.pipeline import run_ingest, run_ingest_files
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
    CompactionSnapshotRecord,
    CompiledPrompt,
    HookStatus,
    IngestResult,
    LLMProviderType,
    LLMSettings,
    LLMStatus,
    MemoryArtifactRecord,
    MemoryArtifactType,
    MemoryEntry,
    MemoryKind,
    ProjectConfig,
    ReviewModeOutput,
    SolveModeOutput,
    SourceType,
    TaskLifecycleError,
    TaskOutputRecord,
    TaskOutputType,
    TaskRecord,
    TaskStatus,
    TeachModeOutput,
)
from oh_no_my_claudecode.prompt import compile_prompt
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.sync import export_agent_memory, restore_agent_memory
from oh_no_my_claudecode.sync.schema import SyncResult
from oh_no_my_claudecode.utils.text import shorten, stable_id, tokenize, unique_preserve
from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now

StructuredOutputT = TypeVar(
    "StructuredOutputT",
    SolveModeOutput,
    ReviewModeOutput,
    TeachModeOutput,
)
MAX_PROMPT_CHARS = 24_000


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

    def ingest_files(self, paths: list[str]) -> tuple[Path, IngestResult]:
        """Ingest only the specified repo-relative files."""
        repo_root, config, storage = self._load_context()
        return repo_root, run_ingest_files(repo_root, config, storage, paths)

    def compile_brief(self, task: str) -> tuple[Path, BriefArtifact]:
        repo_root, config, storage = self._load_context()
        artifact = compile_brief(repo_root, config, storage, task)
        output_name = f"{utc_now().strftime('%Y%m%d-%H%M%S')}-brief.md"
        output_path = compiled_dir(config, repo_root) / output_name
        output_path.write_text(artifact.to_markdown(), encoding="utf-8")
        artifact.output_path = output_path.as_posix()
        return repo_root, artifact

    def install_hooks(
        self,
        *,
        home: Path | None = None,
        add_mcp_server: bool = False,
    ) -> HookStatus:
        """Install Claude Code compaction hooks into settings.json."""
        settings_path = claude_settings_path(home)
        backup_path = claude_settings_backup_path(home)
        install_claude_hooks(
            settings_path=settings_path,
            backup_path=backup_path,
            add_mcp_server=add_mcp_server,
        )
        return self.hooks_status(home=home)

    def uninstall_hooks(self, *, home: Path | None = None) -> HookStatus:
        """Remove Claude Code compaction hooks from settings.json."""
        settings_path = claude_settings_path(home)
        backup_path = claude_settings_backup_path(home)
        uninstall_claude_hooks(settings_path=settings_path, backup_path=backup_path)
        return self.hooks_status(home=home)

    def hooks_status(self, *, home: Path | None = None) -> HookStatus:
        """Return the current Claude hook installation and snapshot status."""
        _, _, storage = self._load_context()
        meta = storage.all_meta()
        latest_snapshot = storage.latest_compaction_snapshot()
        settings_path = claude_settings_path(home)
        backup_path = claude_settings_backup_path(home)
        from oh_no_my_claudecode.hooks.installer import hooks_installed

        return HookStatus(
            installed=hooks_installed(settings_path=settings_path),
            backup_path=backup_path.as_posix(),
            settings_path=settings_path.as_posix(),
            latest_snapshot_id=latest_snapshot.id if latest_snapshot else None,
            last_pre_compact_at=meta.get("last_pre_compact_at"),
            last_post_compact_at=meta.get("last_post_compact_at"),
        )

    def pre_compact(self) -> CompactionSnapshotRecord:
        """Capture the latest task-scoped state into a compaction snapshot."""
        _, _, storage = self._load_context()
        task = self._latest_active_task(storage)
        attempts = storage.list_attempts_for_task(task.task_id) if task else []
        artifacts = storage.list_memory_artifacts_for_task(task.task_id) if task else []
        outputs = storage.list_task_outputs_for_task(task.task_id) if task else []
        memories = storage.list_memories()
        snapshot = build_compaction_snapshot(
            task=task,
            attempts=attempts,
            artifacts=artifacts,
            outputs=outputs,
            memories=memories,
        )
        storage.create_compaction_snapshot(snapshot)
        storage.set_meta("last_pre_compact_at", isoformat_utc(snapshot.timestamp))
        return snapshot

    def post_compact(self, *, home: Path | None = None) -> tuple[CompactionSnapshotRecord, Path]:
        """Compile and persist the latest continuation brief after compaction."""
        _, _, storage = self._load_context()
        snapshot = storage.latest_compaction_snapshot()
        if snapshot is None:
            msg = "No compaction snapshot is available."
            raise LookupError(msg)
        task = storage.get_task(snapshot.task_id) if snapshot.task_id else None
        decisions = [
            memory
            for memory in (storage.get_memory(memory_id) for memory_id in snapshot.recent_decisions)
            if memory is not None
        ]
        brief_md, token_count = compile_continuation_brief(
            snapshot=snapshot,
            task=task,
            decisions=decisions,
        )
        brief_path, updated_snapshot = write_continuation_brief(
            home=home or Path.home(),
            snapshot=snapshot,
            continuation_brief_md=brief_md,
            token_count=token_count,
        )
        storage.update_compaction_snapshot(updated_snapshot)
        storage.set_meta("last_post_compact_at", isoformat_utc(utc_now()))
        return updated_snapshot, brief_path

    def latest_compaction_snapshot(self) -> CompactionSnapshotRecord | None:
        """Return the most recent compaction snapshot."""
        _, _, storage = self._load_context()
        return storage.latest_compaction_snapshot()

    def sync_commit(self, output_dir: Path | None = None) -> tuple[Path, SyncResult]:
        """Export ONMC memory and task state to a git-portable directory."""
        repo_root, config, storage = self._load_context()
        target_dir = output_dir or repo_root / ".agent-memory"
        result = export_agent_memory(
            repo_root=repo_root,
            config=config,
            storage=storage,
            output_dir=target_dir,
        )
        return repo_root, result

    def sync_restore(self, input_dir: Path | None = None) -> tuple[Path, SyncResult]:
        """Restore ONMC memory and task state from a git-portable directory."""
        repo_root, _, storage = self._load_context()
        source_dir = input_dir or repo_root / ".agent-memory"
        manifest_path = source_dir / "manifest.json"
        if not manifest_path.exists():
            display_path = (
                ".agent-memory/manifest.json"
                if source_dir == repo_root / ".agent-memory"
                else manifest_path.as_posix()
            )
            msg = (
                f"Error: {display_path} not found.\n"
                "Run `onmc sync --commit` on a machine with an initialized repo first,\n"
                "then commit .agent-memory/ to git before restoring."
            )
            raise FileNotFoundError(msg)
        return repo_root, restore_agent_memory(input_dir=source_dir, storage=storage)

    def install_sync_hook(self) -> tuple[Path, Path]:
        """Install a post-commit hook that exports ONMC memory to .agent-memory."""
        repo_root = discover_repo_root(self.cwd)
        hook_path = repo_root / ".git" / "hooks" / "post-commit"
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        snippet = "#!/bin/sh\nonmc sync --commit\n"
        if hook_path.exists():
            existing = hook_path.read_text(encoding="utf-8")
            if "onmc sync --commit" not in existing:
                updated = existing.rstrip() + "\n" + snippet
                hook_path.write_text(updated, encoding="utf-8")
        else:
            hook_path.write_text(snippet, encoding="utf-8")
        hook_path.chmod(0o755)
        return repo_root, hook_path

    def install_ingest_hook(self) -> tuple[Path, Path]:
        """Install a post-commit hook that re-ingests changed files and exports sync state."""
        repo_root = discover_repo_root(self.cwd)
        hook_path = repo_root / ".git" / "hooks" / "post-commit"
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        snippet = "\n".join(
            [
                "#!/bin/sh",
                "# ONMC incremental ingest hook",
                "# Re-ingests only files changed in the last commit",
                'CHANGED=$(git diff HEAD~1 --name-only 2>/dev/null || echo "")',
                'if [ -n "$CHANGED" ]; then',
                "  echo \"$CHANGED\" | tr '\\n' '\\0' | xargs -0 onmc ingest --files",
                "fi",
                "onmc sync --commit 2>/dev/null || true",
                "",
            ]
        )
        if hook_path.exists():
            existing = hook_path.read_text(encoding="utf-8")
            if "# ONMC incremental ingest hook" not in existing:
                hook_path.write_text(existing.rstrip() + "\n" + snippet, encoding="utf-8")
        else:
            hook_path.write_text(snippet, encoding="utf-8")
        hook_path.chmod(0o755)
        return repo_root, hook_path

    def list_memories(self, *, kind: MemoryKind | None = None) -> list[MemoryEntry]:
        _, _, storage = self._load_context()
        return MemoryCatalog(storage).list(kind=kind)

    def add_manual_memory(
        self,
        *,
        kind: MemoryKind,
        title: str,
        summary: str,
        task_id: str | None = None,
    ) -> MemoryEntry:
        """Create or update a manual memory entry."""
        _, _, storage = self._load_context()
        now = utc_now()
        source_ref = f"task:{task_id}" if task_id else "manual:api"
        tags = [kind.value]
        if task_id:
            tags.append(task_id)
        entry = MemoryEntry(
            id=stable_id(kind.value, title, summary, source_ref, prefix="manual"),
            kind=kind,
            title=title,
            summary=summary,
            details=summary,
            source_type=SourceType.MANUAL,
            source_ref=source_ref,
            tags=unique_preserve(tags),
            confidence=0.75,
            created_at=now,
            updated_at=now,
        )
        storage.upsert_memories([entry])
        return storage.get_memory(entry.id) or entry

    def get_memory(self, memory_id: str) -> MemoryEntry | None:
        _, _, storage = self._load_context()
        return MemoryCatalog(storage).get(memory_id)

    def search_memories(self, files: list[str]) -> list[MemoryEntry]:
        """Return repo memories ranked for the provided file paths."""
        _, _, storage = self._load_context()
        query = " ".join(files)
        candidates = storage.list_memories()
        ranked: list[tuple[float, MemoryEntry]] = []
        file_tokens = set(tokenize(query))
        for memory in candidates:
            source_text = " ".join([memory.source_ref, *memory.tags, memory.title, memory.summary])
            source_tokens = set(tokenize(source_text))
            score = float(len(file_tokens & source_tokens) * 4) + memory.confidence
            if any(path == memory.source_ref or path in memory.source_ref for path in files):
                score += 4.0
            ranked.append((score, memory))

        ranked.sort(key=lambda item: (-item[0], item[1].title))
        selected = [memory for score, memory in ranked if score > 0][:8]
        if selected:
            return selected
        return score_memories(query, candidates)[:5]

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

    def solve(
        self,
        *,
        task: str,
        task_id: str | None = None,
    ) -> tuple[Path, TaskOutputRecord, SolveModeOutput]:
        return self._run_llm_mode(
            mode=AgentMode.SOLVE,
            task=task,
            task_id=task_id,
            response_model=SolveModeOutput,
        )

    def review(
        self,
        *,
        task: str,
        external_input: str | None = None,
    ) -> tuple[Path, TaskOutputRecord, ReviewModeOutput]:
        return self._run_llm_mode(
            mode=AgentMode.REVIEW,
            task=task,
            task_id=None,
            response_model=ReviewModeOutput,
            external_input=external_input,
        )

    def teach(
        self,
        *,
        task: str,
        task_id: str | None = None,
    ) -> tuple[Path, TaskOutputRecord, TeachModeOutput]:
        return self._run_llm_mode(
            mode=AgentMode.TEACH,
            task=task,
            task_id=task_id,
            response_model=TeachModeOutput,
        )

    def get_task_output(self, output_id: str) -> TaskOutputRecord | None:
        _, _, storage = self._load_context()
        return storage.get_task_output(output_id)

    def list_task_outputs_for_task(self, task_id: str) -> list[TaskOutputRecord]:
        _, _, storage = self._load_context()
        self._require_task(storage, task_id)
        return storage.list_task_outputs_for_task(task_id)

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

    def task_output_counts_by_task(self) -> dict[str, int]:
        _, _, storage = self._load_context()
        return storage.list_task_output_counts_by_task()

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
            "task_outputs": str(storage.task_output_count()),
            "last_ingest_at": meta.get("last_ingest_at", "never"),
            "storage_path": database_path(config, repo_root).as_posix(),
            "state_dir": state_dir(config, repo_root).as_posix(),
            "doc_globs": ", ".join(config.ingest.doc_globs),
            "max_brief_memories": str(config.brief.max_memories),
        }

    def _run_llm_mode(
        self,
        *,
        mode: AgentMode,
        task: str,
        task_id: str | None,
        response_model: type[StructuredOutputT],
        external_input: str | None = None,
    ) -> tuple[Path, TaskOutputRecord, StructuredOutputT]:
        repo_root, config, storage = self._load_context()
        provider = provider_from_settings(config.llm)
        task_record = self._resolve_task_context(
            repo_root=repo_root,
            storage=storage,
            task_text=task,
            task_id=task_id,
        )
        attempts = storage.list_attempts_for_task(task_id) if task_id else []
        memory_artifacts = storage.list_memory_artifacts_for_task(task_id) if task_id else []
        brief = compile_brief(repo_root, config, storage, task)
        prompt = compile_prompt(
            mode=mode,
            task=task_record,
            brief=brief,
            attempts=attempts,
            memory_artifacts=memory_artifacts,
            supplemental_input=external_input,
        )
        self._ensure_prompt_size(prompt)
        structured = provider.generate_structured(
            prompt.to_generation_request(),
            response_model,
        )
        output_path = self._write_llm_output_markdown(
            repo_root=repo_root,
            config=config,
            mode=mode,
            task=task,
            prompt=prompt,
            brief=brief,
            structured=structured,
            provider=provider,
        )
        output = TaskOutputRecord(
            output_id=f"output-{secrets.token_hex(5)}",
            task_id=task_id,
            type=_output_type_for_mode(mode),
            task_text=task,
            provider=config.llm.provider.value if config.llm.provider else "unconfigured",
            model=config.llm.model or "unknown",
            summary=_summary_for_structured_output(mode, structured),
            content_json=json.dumps(structured.model_dump(mode="json"), sort_keys=True),
            markdown_path=output_path.as_posix(),
            created_at=utc_now(),
        )
        storage.create_task_output(output)
        return repo_root, output, structured

    @staticmethod
    def _resolve_task_context(
        *,
        repo_root: Path,
        storage: SQLiteStorage,
        task_text: str,
        task_id: str | None,
    ) -> TaskRecord:
        if task_id is None:
            now = utc_now()
            return TaskRecord(
                task_id="adhoc-task",
                title=shorten(task_text, max_length=80),
                description=task_text,
                status=TaskStatus.OPEN,
                created_at=now,
                started_at=None,
                ended_at=None,
                repo_root=repo_root.as_posix(),
                branch=current_branch(repo_root),
                labels=[],
                final_summary=None,
                final_outcome=None,
                confidence=None,
            )
        task = OnmcService._require_task(storage, task_id)
        if not _task_matches_text(task, task_text):
            msg = (
                f"Provided task text does not appear to match task {task_id}. "
                "Use matching task text or omit --task-id."
            )
            raise ValueError(msg)
        return task

    @staticmethod
    def _ensure_prompt_size(prompt: CompiledPrompt) -> None:
        total_length = len(prompt.system_prompt) + len(prompt.prompt)
        if total_length > MAX_PROMPT_CHARS:
            msg = (
                "Compiled prompt is too large for the current P0 flow. "
                "Reduce the task scope or input file size."
            )
            raise ValueError(msg)

    def _write_llm_output_markdown(
        self,
        *,
        repo_root: Path,
        config: ProjectConfig,
        mode: AgentMode,
        task: str,
        prompt: CompiledPrompt,
        brief: BriefArtifact,
        structured: StructuredOutputT,
        provider: BaseLLMProvider,
    ) -> Path:
        output_name = f"{utc_now().strftime('%Y%m%d-%H%M%S')}-{mode.value}.md"
        output_path = compiled_dir(config, repo_root) / output_name
        markdown = "\n".join(
            [
                f"# ONMC {mode.value.title()} Output",
                "",
                f"- Task: {task}",
                (
                    "- Provider: "
                    f"{config.llm.provider.value if config.llm.provider else 'unconfigured'}"
                ),
                f"- Model: {config.llm.model or 'unknown'}",
                f"- Repo: `{repo_root.as_posix()}`",
                "",
                "## Summary",
                "",
                _summary_for_structured_output(mode, structured),
                "",
                "## Structured Output",
                "",
                "```json",
                json.dumps(structured.model_dump(mode="json"), indent=2, sort_keys=True),
                "```",
                "",
                "## Files To Inspect",
                "",
                *[f"1. `{path}`" for path in brief.files_to_inspect[:8]],
                "",
                "## Validation Checklist",
                "",
                *[f"- {item}" for item in brief.validation_checklist[:6]],
                "",
                "## Prompt Sections",
                "",
                *[f"- {title}" for title in prompt.section_titles],
            ]
        ).strip() + "\n"
        output_path.write_text(markdown, encoding="utf-8")
        return output_path

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

    @staticmethod
    def _latest_active_task(storage: SQLiteStorage) -> TaskRecord | None:
        candidates = [task for task in storage.list_tasks() if task.status == TaskStatus.ACTIVE]
        if not candidates:
            return None

        def recency(task: TaskRecord) -> tuple[str, str]:
            attempts = storage.list_attempts_for_task(task.task_id)
            artifacts = storage.list_memory_artifacts_for_task(task.task_id)
            outputs = storage.list_task_outputs_for_task(task.task_id)
            latest_markers = [task.started_at or task.created_at]
            latest_markers.extend(item.created_at for item in attempts[:1])
            latest_markers.extend(item.created_at for item in artifacts[:1])
            latest_markers.extend(item.created_at for item in outputs[:1])
            latest = max(marker for marker in latest_markers if marker is not None)
            return latest.isoformat(), task.task_id

        return sorted(candidates, key=recency, reverse=True)[0]


def _task_matches_text(task: TaskRecord, task_text: str) -> bool:
    candidate_tokens = set(tokenize(task_text))
    if not candidate_tokens:
        return False
    task_tokens = set(tokenize(f"{task.title} {task.description}"))
    overlap = candidate_tokens & task_tokens
    return len(overlap) >= min(3, len(candidate_tokens))


def _output_type_for_mode(mode: AgentMode) -> TaskOutputType:
    if mode == AgentMode.SOLVE:
        return TaskOutputType.SOLVE_OUTPUT
    if mode == AgentMode.REVIEW:
        return TaskOutputType.REVIEW_OUTPUT
    return TaskOutputType.TEACHING_OUTPUT


def _summary_for_structured_output(mode: AgentMode, structured: StructuredOutputT) -> str:
    if mode == AgentMode.SOLVE and isinstance(structured, SolveModeOutput):
        return shorten(structured.approach_summary, max_length=180)
    if mode == AgentMode.REVIEW and isinstance(structured, ReviewModeOutput):
        if structured.concerns:
            return shorten(structured.concerns[0], max_length=180)
        return "Review completed with no major concerns recorded."
    if isinstance(structured, TeachModeOutput):
        return shorten(structured.system_lesson, max_length=180)
    msg = f"Unsupported structured output for mode {mode.value}."
    raise TypeError(msg)
