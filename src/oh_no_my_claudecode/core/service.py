from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar, cast

from oh_no_my_claudecode.brief.compiler import compile_brief, score_memories
from oh_no_my_claudecode.claude_md import (
    claude_md_path,
    generate_claude_md,
    load_claude_md_meta,
    update_claude_md,
    watch_claude_md,
)
from oh_no_my_claudecode.config import (
    compiled_dir,
    config_exists,
    create_state_dirs,
    database_path,
    default_config,
    ensure_state_dir_gitignored,
    load_config,
    logs_dir,
    state_dir,
    write_config,
)
from oh_no_my_claudecode.core.repo import current_branch, discover_repo_root, path_bucket
from oh_no_my_claudecode.hooks import (
    HookInstallResult,
    build_compaction_snapshot,
    compile_boot_digest,
    compile_continuation_brief,
    hooks_installed,
    install_claude_hooks,
    legacy_global_hooks_present,
    mcp_config_path,
    mcp_registered,
    project_settings_backup_path,
    project_settings_path,
    uninstall_claude_hooks,
    user_settings_path,
    write_boot_digest_artifact,
    write_continuation_brief_artifact,
)
from oh_no_my_claudecode.ingest.pipeline import run_ingest, run_ingest_files
from oh_no_my_claudecode.llm import (
    MarkdownEnvelope,
    default_api_key_env_var,
    generate_structured_logged,
    llm_status,
    provider_from_settings,
)
from oh_no_my_claudecode.llm.base import BaseLLMProvider
from oh_no_my_claudecode.llm.providers import validate_provider_api_key
from oh_no_my_claudecode.memory.catalog import MemoryCatalog
from oh_no_my_claudecode.mine import mine_github_prs, mine_transcripts
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
    FileStat,
    HookStatus,
    IngestResult,
    LLMGenerationRequest,
    LLMProviderType,
    LLMSettings,
    LLMStatus,
    MemoryArtifactRecord,
    MemoryArtifactType,
    MemoryEntry,
    MemoryKind,
    ProjectConfig,
    RepoFileRecord,
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
from oh_no_my_claudecode.why.compiler import WhyReport, compile_why, why_report_to_markdown

StructuredOutputT = TypeVar(
    "StructuredOutputT",
    SolveModeOutput,
    ReviewModeOutput,
    TeachModeOutput,
)
MAX_PROMPT_CHARS = 24_000
HEALTH_SECTION_ORDER = ("repo", "memory", "provider", "claude", "sync")


@dataclass(slots=True)
class AgentReadinessSummary:
    ok: bool
    readiness_label: str
    generated_at: str
    repo_name: str
    repo_root: str
    branch: str
    passed_checks: int
    total_checks: int
    health: dict[str, list[str]]
    health_sections: list[str]
    warnings: list[str]
    errors: list[str]
    memory_count: int
    task_count: int
    attempt_count: int
    memory_artifact_count: int
    task_output_count: int
    last_ingest_at: str
    active_tasks: list[TaskRecord]
    claude_md_exists: bool
    hooks: HookStatus
    manifest_exists: bool
    sync_hook_installed: bool
    provider_label: str


class OnmcService:
    def __init__(self, cwd: Path | None = None) -> None:
        self.cwd = cwd or Path.cwd()

    def init_project(self) -> tuple[Path, ProjectConfig]:
        repo_root = discover_repo_root(self.cwd)
        config = load_config(repo_root) if config_exists(repo_root) else default_config(repo_root)
        create_state_dirs(config, repo_root)
        ensure_state_dir_gitignored(config, repo_root)
        write_config(config, repo_root)
        storage = SQLiteStorage(database_path(config, repo_root))
        storage.initialize()
        storage.set_meta("initialized_at", isoformat_utc(utc_now()))
        return repo_root, config

    def ingest(self, *, no_llm: bool = False) -> tuple[Path, IngestResult]:
        repo_root, config, storage = self._load_context()
        provider = self._optional_provider(config=config, no_llm=no_llm)
        return repo_root, run_ingest(
            repo_root,
            config,
            storage,
            provider=provider,
            log_path=self._llm_log_path(repo_root, config),
        )

    def ingest_files(self, paths: list[str], *, no_llm: bool = False) -> tuple[Path, IngestResult]:
        """Ingest only the specified repo-relative files."""
        repo_root, config, storage = self._load_context()
        provider = self._optional_provider(config=config, no_llm=no_llm)
        return repo_root, run_ingest_files(
            repo_root,
            config,
            storage,
            paths,
            provider=provider,
            log_path=self._llm_log_path(repo_root, config),
        )

    def compile_brief(self, task: str, *, no_llm: bool = False) -> tuple[Path, BriefArtifact]:
        repo_root, config, storage = self._load_context()
        artifact = compile_brief(
            repo_root,
            config,
            storage,
            task,
            provider=self._optional_provider(config=config, no_llm=no_llm),
            log_path=self._llm_log_path(repo_root, config),
        )
        output_name = f"{utc_now().strftime('%Y%m%d-%H%M%S')}-brief.md"
        output_path = compiled_dir(config, repo_root) / output_name
        output_path.write_text(artifact.to_markdown(), encoding="utf-8")
        artifact.output_path = output_path.as_posix()
        return repo_root, artifact

    def why(self, path: str, *, no_llm: bool = False) -> tuple[Path, WhyReport]:
        """Compile a `why` report for a file from stored memory + git history."""
        repo_root, config, storage = self._load_context()
        report = compile_why(repo_root, storage, path)
        if report.has_data and not no_llm:
            report.llm_narrative = self._why_narrative(
                report=report, config=config, repo_root=repo_root, no_llm=no_llm
            )
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", report.path)
        output_name = f"{utc_now().strftime('%Y%m%d-%H%M%S')}-why-{safe_name}.md"
        output_path = compiled_dir(config, repo_root) / output_name
        output_path.write_text(why_report_to_markdown(report), encoding="utf-8")
        report.output_path = output_path.as_posix()
        return repo_root, report

    def _why_narrative(
        self,
        *,
        report: WhyReport,
        config: ProjectConfig,
        repo_root: Path,
        no_llm: bool,
    ) -> str:
        """Best-effort LLM narrative for a why report; never raises."""
        provider = self._optional_provider(config=config, no_llm=no_llm)
        if provider is None:
            return ""
        try:
            return generate_structured_logged(
                provider,
                LLMGenerationRequest(
                    system_prompt="Return valid JSON with a single `markdown` key.",
                    prompt=(
                        "Write a 2-3 sentence narrative explaining why this file looks the "
                        "way it does, grounded ONLY in the report below. Do not invent "
                        "facts or cite anything not present.\n\n"
                        f"{why_report_to_markdown(report)}"
                    ),
                    temperature=0.0,
                    max_tokens=400,
                ),
                MarkdownEnvelope,
                log_path=self._llm_log_path(repo_root, config),
                operation="why.narrative",
            ).markdown
        except Exception:
            return ""

    def install_hooks(
        self,
        *,
        home: Path | None = None,
        add_mcp_server: bool = False,
    ) -> tuple[HookInstallResult, HookStatus]:
        """Install project-scoped Claude Code hooks (and optionally .mcp.json)."""
        repo_root = discover_repo_root(self.cwd)
        result = install_claude_hooks(
            repo_root=repo_root,
            register_mcp=add_mcp_server,
            global_settings_path=user_settings_path(home),
        )
        return result, self.hooks_status(home=home)

    def uninstall_hooks(self, *, home: Path | None = None) -> HookStatus:
        """Surgically remove onmc hooks from project settings, .mcp.json, and legacy global."""
        repo_root = discover_repo_root(self.cwd)
        uninstall_claude_hooks(
            repo_root=repo_root,
            global_settings_path=user_settings_path(home),
        )
        return self.hooks_status(home=home)

    def hooks_status(self, *, home: Path | None = None) -> HookStatus:
        """Return the project-scoped hook installation and snapshot status."""
        repo_root, _, storage = self._load_context()
        meta = storage.all_meta()
        latest_snapshot = storage.latest_compaction_snapshot()
        settings_path = project_settings_path(repo_root)
        mcp_path = mcp_config_path(repo_root)
        return HookStatus(
            installed=hooks_installed(settings_path=settings_path),
            backup_path=project_settings_backup_path(repo_root).as_posix(),
            settings_path=settings_path.as_posix(),
            mcp_path=mcp_path.as_posix(),
            mcp_registered=mcp_registered(mcp_path=mcp_path),
            legacy_global_hooks=legacy_global_hooks_present(
                settings_path=user_settings_path(home)
            ),
            latest_snapshot_id=latest_snapshot.id if latest_snapshot else None,
            last_pre_compact_at=meta.get("last_pre_compact_at"),
            last_session_start_at=meta.get("last_session_start_at"),
        )

    def pre_compact(self, *, transcript_path: Path | None = None) -> CompactionSnapshotRecord:
        """Capture task state (plus live transcript context) into a compaction snapshot."""
        repo_root, _, storage = self._load_context()
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
            transcript_path=transcript_path,
            repo_root=repo_root,
        )
        storage.create_compaction_snapshot(snapshot)
        storage.set_meta("last_pre_compact_at", isoformat_utc(snapshot.timestamp))
        return snapshot

    def session_start(self, *, home: Path | None = None) -> tuple[CompactionSnapshotRecord, str]:
        """Compile the continuation brief for the SessionStart("compact") hook.

        Returns the updated snapshot and the brief markdown. The CLI emits the
        hook stdout JSON; the markdown is also written to
        ``.onmc/continuation-brief.md`` as a debug artifact.
        """
        repo_root, config, storage = self._load_context()
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
        _, updated_snapshot = write_continuation_brief_artifact(
            state_dir=state_dir(config, repo_root),
            snapshot=snapshot,
            continuation_brief_md=brief_md,
            token_count=token_count,
        )
        storage.update_compaction_snapshot(updated_snapshot)
        storage.set_meta("last_session_start_at", isoformat_utc(utc_now()))
        self._refresh_claude_md_if_stale(storage=storage, home=home)
        return updated_snapshot, brief_md

    def boot_digest(self) -> tuple[str, int]:
        """Compile a boot digest for session startup/resume/clear injection.

        Returns ``(digest_md, token_count)``. When the store has no meaningful
        memory, returns ``("", 0)`` — callers must emit nothing on stdout in
        that case so the session is never blocked.

        The digest is also written to ``.onmc/boot-digest.md`` as a debug
        artifact.
        """
        repo_root, config, storage = self._load_context()
        memories = storage.list_memories()
        tasks = storage.list_tasks()
        digest_md, token_count = compile_boot_digest(
            memories=memories,
            tasks=tasks,
            repo_name=repo_root.name,
        )
        if digest_md:
            write_boot_digest_artifact(
                state_dir=state_dir(config, repo_root),
                boot_digest_md=digest_md,
            )
        storage.set_meta("last_session_start_at", isoformat_utc(utc_now()))
        return digest_md, token_count

    def latest_compaction_snapshot(self) -> CompactionSnapshotRecord | None:
        """Return the most recent compaction snapshot."""
        _, _, storage = self._load_context()
        return storage.latest_compaction_snapshot()

    def provider_available(self) -> bool:
        """Return whether a configured provider can be instantiated."""
        try:
            _, config, _ = self._load_context()
            self._optional_provider(config=config, no_llm=False)
        except Exception:
            return False
        return True

    def generate_claude_md(self, *, no_llm: bool = False, write: bool = True) -> str:
        """Generate CLAUDE.md from stored memory and active task state."""
        repo_root, config, storage = self._load_context()
        markdown, _ = generate_claude_md(
            repo_root=repo_root,
            storage=storage,
            provider=self._optional_provider(config=config, no_llm=no_llm),
            log_path=self._llm_log_path(repo_root, config),
            write=write,
        )
        return markdown

    def update_claude_md(
        self,
        *,
        no_llm: bool = False,
        write: bool = True,
    ) -> tuple[str, list[str]]:
        """Update stale CLAUDE.md sections while preserving user-written sections."""
        repo_root, config, storage = self._load_context()
        return update_claude_md(
            repo_root=repo_root,
            storage=storage,
            provider=self._optional_provider(config=config, no_llm=no_llm),
            log_path=self._llm_log_path(repo_root, config),
            write=write,
        )

    def watch_claude_md(self, *, no_llm: bool = False) -> None:
        """Watch the ONMC state directory and regenerate CLAUDE.md on updates."""
        repo_root, config, storage = self._load_context()
        watch_claude_md(
            repo_root=repo_root,
            storage=storage,
            provider=self._optional_provider(config=config, no_llm=no_llm),
            log_path=self._llm_log_path(repo_root, config),
        )

    def mine(
        self,
        *,
        dry_run: bool = False,
        session_id: str | None = None,
        since: str | None = None,
        no_llm: bool = False,
        github: bool = False,
    ) -> dict[str, object]:
        """Mine Claude Code transcripts for attempts and memory findings."""
        repo_root, config, storage = self._load_context()
        provider = self._optional_provider(config=config, no_llm=no_llm)
        if github:
            return mine_github_prs(
                repo_root=repo_root,
                storage=storage,
                provider=provider,
                log_path=self._llm_log_path(repo_root, config),
                dry_run=dry_run,
            )
        return mine_transcripts(
            repo_root=repo_root,
            storage=storage,
            provider=provider,
            log_path=self._llm_log_path(repo_root, config),
            dry_run=dry_run,
            session_id=session_id,
            since=since,
        )

    def doctor(self) -> tuple[bool, dict[str, list[str]]]:
        """Run a health check over the repo, memory store, and agent integrations."""
        repo_root, config, storage = self._load_context()
        report: dict[str, list[str]] = {
            "repo": [],
            "memory": [],
            "provider": [],
            "claude": [],
            "sync": [],
            "errors": [],
            "warnings": [],
        }
        commit_count = _git_count(repo_root)
        report["repo"].append(f"Git repo detected ({commit_count} commits)")
        report["repo"].append(".onmc initialized")
        meta = storage.all_meta()
        last_ingest = meta.get("last_ingest_at")
        if last_ingest:
            report["repo"].append(f"Last ingested: {last_ingest}")
        else:
            report["warnings"].append("No ingest metadata found — run `onmc ingest`.")
        if last_ingest:
            commits_since = _git_commits_since(repo_root, last_ingest)
            if commits_since > 0:
                report["warnings"].append(
                    f"{commits_since} commits since last ingest — run `onmc ingest`."
                )
        memories = storage.list_memories()
        llm_extracted = len(
            [item for item in memories if item.source_type == SourceType.LLM_EXTRACTED]
        )
        heuristic = len(memories) - llm_extracted
        active_task_count = len(
            [task for task in storage.list_tasks() if task.status == TaskStatus.ACTIVE]
        )
        report["memory"].append(
            f"{len(memories)} memory records "
            f"({llm_extracted} LLM-extracted, {heuristic} heuristic)"
        )
        report["memory"].append(f"{storage.task_count()} tasks ({active_task_count} active)")
        if (repo_root / ".agent-memory" / "manifest.json").exists():
            report["sync"].append(".agent-memory/ export present")
        else:
            report["warnings"].append(".agent-memory/ not found — run `onmc sync --commit`.")
        if config.llm.provider is None or config.llm.model is None:
            report["warnings"].append("LLM provider is not fully configured.")
        else:
            provider_name = config.llm.provider.value
            model_name = config.llm.model
            key_var = config.llm.api_key_env_var or default_api_key_env_var(config.llm.provider)
            report["provider"].append(f"Provider: {provider_name} ({model_name})")
            if not key_var:
                report["warnings"].append(
                    f"No API key environment variable is configured for {provider_name}."
                )
            else:
                key_value = os.environ.get(key_var)
                if not key_value:
                    report["warnings"].append(
                        f"{key_var} not set in current environment. "
                        f"Set {key_var} to enable LLM features."
                    )
                else:
                    valid, detail = validate_provider_api_key(config.llm.provider, key_value)
                    if valid:
                        report["provider"].append(f"API key env var: {key_var} valid")
                    elif detail == "invalid credentials":
                        report["errors"].append(
                            f"{provider_name} key is invalid. Check {key_var}."
                        )
                    else:
                        report["warnings"].append(
                            f"Could not validate {key_var}: {detail}."
                        )
        hook_status = self.hooks_status()
        report["claude"].append(
            "Compaction hooks "
            f"{'installed' if hook_status.installed else 'not installed'} "
            "(.claude/settings.json)"
        )
        report["claude"].append(
            f"MCP server {'registered' if hook_status.mcp_registered else 'not registered'} "
            "(.mcp.json)"
        )
        if hook_status.legacy_global_hooks:
            report["warnings"].append(
                "Legacy onmc hooks found in ~/.claude/settings.json — "
                "run `onmc hooks install` to migrate or `onmc hooks uninstall` to remove."
            )
        if hook_status.last_pre_compact_at:
            report["claude"].append(f"Last pre-compact: {hook_status.last_pre_compact_at}")
        if claude_md_path(repo_root).exists():
            report["claude"].append("CLAUDE.md present")
        else:
            report["warnings"].append("CLAUDE.md not found — run `onmc claude-md generate`.")
        post_commit = repo_root / ".git" / "hooks" / "post-commit"
        if post_commit.exists():
            report["sync"].append("Post-commit hook installed")
        else:
            report["warnings"].append("Post-commit hook not installed.")
        report["warnings"].extend(_detect_leaked_keys(state_dir(config, repo_root)))
        return not report["errors"], report

    def agent_readiness_report(self) -> str:
        """Generate a shareable markdown report for agent readiness."""
        return _agent_readiness_markdown(self._build_agent_readiness_summary())

    def codegraph(self, *, max_files: int = 40, max_dirs: int = 12) -> str:
        """Generate a compact repo codegraph from ingested file metadata."""
        repo_root, _, storage = self._load_context()
        repo_files = storage.list_repo_files()
        if not repo_files:
            msg = "No repo file index found. Run `onmc ingest` first."
            raise FileNotFoundError(msg)
        file_stats = storage.list_file_stats()
        stats_by_path = {stat.path: stat for stat in file_stats}
        dir_stats = _codegraph_dirs(repo_files, file_stats)
        hot_files = sorted(
            repo_files,
            key=lambda record: _codegraph_file_score(record, stats_by_path.get(record.path)),
            reverse=True,
        )[:max_files]

        lines = [
            "# ONMC Codegraph",
            "",
            f"- Repo: `{repo_root.name}`",
            f"- Files indexed: {len(repo_files)}",
            f"- Hot files shown: {len(hot_files)}",
            "",
            "## Directories",
            "",
        ]
        for item in dir_stats[:max_dirs]:
            lines.append(
                "- "
                f"`{item['path']}` files={item['files']} tests={item['tests']} "
                f"churn={item['churn']} bytes={item['bytes']}"
            )
        lines.extend(["", "## Hot Files", ""])
        for record in hot_files:
            stat = stats_by_path.get(record.path)
            change_count = stat.change_count if stat else 0
            recent_count = stat.recent_change_count if stat else 0
            kind = "test" if record.is_test else "src"
            lines.append(
                f"- `{record.path}` {kind} churn={change_count} "
                f"recent={recent_count} bytes={record.size_bytes}"
            )
        lines.extend(
            [
                "",
                "## Codex Use",
                "",
                "- Read hot files first; avoid dumping entire repo.",
                "- Pair source file with nearby test file before broad search.",
                "- Use `onmc brief --style caveman --max-tokens 400 --stdout` for paste budget.",
                "",
            ]
        )
        return "\n".join(lines)

    def _build_agent_readiness_summary(self) -> AgentReadinessSummary:
        repo_root, config, storage = self._load_context()
        ok, health = self.doctor()
        tasks = storage.list_tasks()
        active_tasks = [task for task in tasks if task.status == TaskStatus.ACTIVE]
        warnings = health.get("warnings", [])
        errors = health.get("errors", [])
        health_sections = _health_sections(health)
        passed_checks = sum(len(health.get(section, [])) for section in health_sections)
        issue_count = len(warnings) + len(errors)
        total_checks = passed_checks + issue_count
        manifest_path = repo_root / ".agent-memory" / "manifest.json"
        sync_hook_path = repo_root / ".git" / "hooks" / "post-commit"
        return AgentReadinessSummary(
            ok=ok,
            readiness_label="ready" if ok and not warnings else "needs attention",
            generated_at=isoformat_utc(utc_now()),
            repo_name=repo_root.name,
            repo_root=repo_root.as_posix(),
            branch=current_branch(repo_root),
            passed_checks=passed_checks,
            total_checks=total_checks,
            health=health,
            health_sections=health_sections,
            warnings=warnings,
            errors=errors,
            memory_count=storage.memory_count(),
            task_count=storage.task_count(),
            attempt_count=storage.attempt_count(),
            memory_artifact_count=storage.memory_artifact_count(),
            task_output_count=storage.task_output_count(),
            last_ingest_at=storage.all_meta().get("last_ingest_at", "never"),
            active_tasks=active_tasks,
            claude_md_exists=claude_md_path(repo_root).exists(),
            hooks=self.hooks_status(),
            manifest_exists=manifest_path.exists(),
            sync_hook_installed=sync_hook_path.exists(),
            provider_label=_provider_label(config),
        )

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

    def list_memories(
        self,
        *,
        kind: MemoryKind | None = None,
        source_type: SourceType | None = None,
        min_confidence: float | None = None,
        confirmed_only: bool = False,
    ) -> list[MemoryEntry]:
        _, _, storage = self._load_context()
        if source_type is not None:
            memories = storage.list_memories(kind=kind, source_type=source_type)
        else:
            memories = MemoryCatalog(storage).list(kind=kind)
        if min_confidence is not None:
            memories = [memory for memory in memories if memory.confidence >= min_confidence]
        if confirmed_only:
            memories = [memory for memory in memories if memory.feedback_score > 0]
        return memories

    def add_manual_memory(
        self,
        *,
        kind: MemoryKind,
        title: str,
        summary: str,
        task_id: str | None = None,
        source_type: SourceType = SourceType.MANUAL,
        confidence: float = 0.75,
        source_ref: str | None = None,
    ) -> MemoryEntry:
        """Create or update a manual memory entry."""
        _, _, storage = self._load_context()
        now = utc_now()
        resolved_source_ref = source_ref or (f"task:{task_id}" if task_id else "manual:api")
        tags = [kind.value]
        if task_id:
            tags.append(task_id)
        entry = MemoryEntry(
            id=stable_id(kind.value, title, summary, resolved_source_ref, prefix="manual"),
            kind=kind,
            title=title,
            summary=summary,
            details=summary,
            source_type=source_type,
            source_ref=resolved_source_ref,
            tags=unique_preserve(tags),
            confidence=confidence,
            created_at=now,
            updated_at=now,
        )
        storage.upsert_memories([entry])
        return storage.get_memory(entry.id) or entry

    def add_memory(
        self,
        *,
        kind: MemoryKind | str,
        title: str,
        summary: str,
        task_id: str | None = None,
        source_type: SourceType | str = SourceType.MANUAL,
        confidence: float = 0.75,
        source_ref: str | None = None,
    ) -> MemoryEntry:
        """Create or update a memory entry with explicit source metadata."""
        resolved_kind = kind if isinstance(kind, MemoryKind) else MemoryKind(kind)
        resolved_source = (
            source_type if isinstance(source_type, SourceType) else SourceType(source_type)
        )
        return self.add_manual_memory(
            kind=resolved_kind,
            title=title,
            summary=summary,
            task_id=task_id,
            source_type=resolved_source,
            confidence=confidence,
            source_ref=source_ref,
        )

    def get_memory(self, memory_id: str) -> MemoryEntry | None:
        _, _, storage = self._load_context()
        return MemoryCatalog(storage).get(memory_id)

    def confirm_memory(self, memory_id: str) -> MemoryEntry:
        """Mark a memory as explicitly useful."""
        _, _, storage = self._load_context()
        memory = self.get_memory(memory_id)
        if memory is None:
            msg = f"Memory not found: {memory_id}"
            raise LookupError(msg)
        updated = memory.model_copy(
            update={
                "feedback_score": min(memory.feedback_score + 0.3, 1.0),
                "updated_at": utc_now(),
            }
        )
        storage.update_memory(updated)
        return updated

    def reject_memory(self, memory_id: str) -> MemoryEntry:
        """Mark a memory as explicitly wrong or stale."""
        _, _, storage = self._load_context()
        memory = self.get_memory(memory_id)
        if memory is None:
            msg = f"Memory not found: {memory_id}"
            raise LookupError(msg)
        updated = memory.model_copy(
            update={
                "feedback_score": max(memory.feedback_score - 0.5, -1.0),
                "updated_at": utc_now(),
            }
        )
        storage.update_memory(updated)
        return updated

    def edit_memory(self, memory_id: str, new_summary: str) -> MemoryEntry:
        """Replace a memory summary and reset its feedback score."""
        _, _, storage = self._load_context()
        memory = self.get_memory(memory_id)
        if memory is None:
            msg = f"Memory not found: {memory_id}"
            raise LookupError(msg)
        updated = memory.model_copy(
            update={
                "summary": new_summary,
                "details": new_summary,
                "feedback_score": 0.0,
                "updated_at": utc_now(),
            }
        )
        storage.update_memory(updated)
        return updated

    def edit_memory_in_editor(self, memory_id: str) -> str | None:
        """Open a memory summary in $EDITOR and return the edited value."""
        editor = os.environ.get("EDITOR")
        if not editor:
            return None
        memory = self.get_memory(memory_id)
        if memory is None:
            msg = f"Memory not found: {memory_id}"
            raise LookupError(msg)
        with tempfile.NamedTemporaryFile(
            "w+",
            encoding="utf-8",
            suffix=".md",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(memory.summary)
            handle.flush()
        try:
            subprocess.run([editor, temp_path.as_posix()], check=True)
            return temp_path.read_text(encoding="utf-8").strip()
        finally:
            temp_path.unlink(missing_ok=True)

    def search_memories(self, files: list[str]) -> list[MemoryEntry]:
        """Return repo memories ranked for the provided file paths."""
        _, _, storage = self._load_context()
        query = " ".join(files)
        candidates = storage.list_memories()
        ranked: list[tuple[float, MemoryEntry]] = []
        file_tokens = set(tokenize(query))
        for memory in candidates:
            if memory.feedback_score <= -0.5:
                continue
            source_text = " ".join([memory.source_ref, *memory.tags, memory.title, memory.summary])
            source_tokens = set(tokenize(source_text))
            score = (
                float(len(file_tokens & source_tokens) * 4)
                + memory.confidence
                + (memory.feedback_score * 0.2)
            )
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
        no_llm: bool = False,
    ) -> tuple[Path, TaskOutputRecord, SolveModeOutput]:
        repo_root, record, output = self._run_llm_mode(
            mode=AgentMode.SOLVE,
            task=task,
            task_id=task_id,
            response_model=SolveModeOutput,
            no_llm=no_llm,
        )
        return repo_root, record, cast(SolveModeOutput, output)

    def review(
        self,
        *,
        task: str,
        external_input: str | None = None,
        no_llm: bool = False,
    ) -> tuple[Path, TaskOutputRecord, ReviewModeOutput]:
        repo_root, record, output = self._run_llm_mode(
            mode=AgentMode.REVIEW,
            task=task,
            task_id=None,
            response_model=ReviewModeOutput,
            external_input=external_input,
            no_llm=no_llm,
        )
        return repo_root, record, cast(ReviewModeOutput, output)

    def teach(
        self,
        *,
        task: str,
        task_id: str | None = None,
        no_llm: bool = False,
    ) -> tuple[Path, TaskOutputRecord, TeachModeOutput]:
        repo_root, record, output = self._run_llm_mode(
            mode=AgentMode.TEACH,
            task=task,
            task_id=task_id,
            response_model=TeachModeOutput,
            no_llm=no_llm,
        )
        return repo_root, record, cast(TeachModeOutput, output)

    def teach_followup(
        self,
        *,
        task: str,
        question: str,
        task_id: str | None = None,
    ) -> str:
        """Answer a follow-up teaching question using the same repo memory spine."""
        repo_root, config, storage = self._load_context()
        provider = provider_from_settings(config.llm)
        brief = compile_brief(
            repo_root,
            config,
            storage,
            task,
            provider=self._optional_provider(config=config, no_llm=False),
            log_path=self._llm_log_path(repo_root, config),
        )
        return generate_structured_logged(
            provider,
            LLMGenerationRequest(
                system_prompt="Return valid JSON with a single `markdown` key.",
                prompt=(
                    "Use the repo brief below to answer the follow-up teaching question "
                    "concisely and concretely.\n\n"
                    f"Task: {task}\n"
                    f"Follow-up question: {question}\n\n"
                    f"Brief:\n{brief.to_markdown()}"
                ),
                temperature=0.0,
                max_tokens=800,
            ),
            MarkdownEnvelope,
            log_path=self._llm_log_path(repo_root, config),
            operation="teach.followup",
        ).markdown

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
        no_llm: bool = False,
    ) -> tuple[Path, TaskOutputRecord, SolveModeOutput | ReviewModeOutput | TeachModeOutput]:
        repo_root, config, storage = self._load_context()
        provider = None if no_llm else self.llm_provider()
        task_record = self._resolve_task_context(
            repo_root=repo_root,
            storage=storage,
            task_text=task,
            task_id=task_id,
        )
        attempts = storage.list_attempts_for_task(task_id) if task_id else []
        memory_artifacts = storage.list_memory_artifacts_for_task(task_id) if task_id else []
        brief = compile_brief(
            repo_root,
            config,
            storage,
            task,
            provider=provider,
            log_path=self._llm_log_path(repo_root, config),
        )
        prompt = compile_prompt(
            mode=mode,
            task=task_record,
            brief=brief,
            attempts=attempts,
            memory_artifacts=memory_artifacts,
            supplemental_input=external_input,
        )
        self._ensure_prompt_size(prompt)
        if provider is None:
            structured = _fallback_mode_output(
                mode=mode,
                brief=brief,
                attempts=attempts,
                memory_artifacts=memory_artifacts,
            )
            provider_name = "heuristic"
            model_name = "none"
        else:
            structured = generate_structured_logged(
                provider,
                prompt.to_generation_request(),
                response_model,
                log_path=self._llm_log_path(repo_root, config),
                operation=f"{mode.value}.structured",
            )
            provider_name = config.llm.provider.value if config.llm.provider else "unconfigured"
            model_name = config.llm.model or "unknown"
        output_path = self._write_llm_output_markdown(
            repo_root=repo_root,
            config=config,
            mode=mode,
            task=task,
            prompt=prompt,
            brief=brief,
            structured=cast(StructuredOutputT, structured),
        )
        output = TaskOutputRecord(
            output_id=f"output-{secrets.token_hex(5)}",
            task_id=task_id,
            type=_output_type_for_mode(mode),
            task_text=task,
            provider=provider_name,
            model=model_name,
            summary=_summary_for_structured_output(mode, cast(StructuredOutputT, structured)),
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
    def _llm_log_path(repo_root: Path, config: ProjectConfig) -> Path:
        return logs_dir(config, repo_root) / "llm-calls.jsonl"

    @staticmethod
    def _optional_provider(
        *,
        config: ProjectConfig,
        no_llm: bool,
    ) -> BaseLLMProvider | None:
        if no_llm or config.llm.provider is None or config.llm.model is None:
            return None
        try:
            return provider_from_settings(config.llm)
        except Exception:
            return None

    def _refresh_claude_md_if_stale(
        self,
        *,
        storage: SQLiteStorage,
        home: Path | None,
    ) -> None:
        repo_root, config, _ = self._load_context()
        meta = load_claude_md_meta(repo_root)
        generated_at = meta.get("generated_at")
        if generated_at:
            parsed = generated_at if isinstance(generated_at, str) else ""
            if parsed and _is_recent_enough(parsed):
                return
        try:
            generate_claude_md(
                repo_root=repo_root,
                storage=storage,
                provider=self._optional_provider(config=config, no_llm=False),
                log_path=self._llm_log_path(repo_root, config),
                write=True,
            )
        except Exception:
            return

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
        return shorten(structured.approach_chosen_and_why, max_length=180)
    msg = f"Unsupported structured output for mode {mode.value}."
    raise TypeError(msg)


def _fallback_mode_output(
    *,
    mode: AgentMode,
    brief: BriefArtifact,
    attempts: list[AttemptRecord],
    memory_artifacts: list[MemoryArtifactRecord],
) -> SolveModeOutput | ReviewModeOutput | TeachModeOutput:
    if mode == AgentMode.SOLVE:
        return SolveModeOutput(
            approach_summary=(
                "Start with the highest-signal files from the brief, preserve recorded "
                "invariants, and avoid any documented failed approaches."
            ),
            files_to_inspect=brief.files_to_inspect[:5],
            risks=brief.risk_notes[:4],
            validations=brief.validation_checklist[:5],
            confidence="heuristic",
        )
    if mode == AgentMode.REVIEW:
        return ReviewModeOutput(
            concerns=brief.risk_notes[:4]
            or ["No major historical risks were identified by the heuristic fallback."],
            assumptions=[
                "The proposed change respects the repo invariants surfaced in the brief."
            ],
            likely_regressions=brief.impacted_areas[:4],
            required_tests=brief.validation_checklist[:5],
        )
    return TeachModeOutput(
        problem_this_solves=brief.task_summary,
        approach_chosen_and_why=(
            brief.relevant_memories[0].summary
            if brief.relevant_memories
            else "Use the repo brief to recover the relevant subsystem and validation path."
        ),
        what_was_tried_first=[attempt.summary for attempt in attempts[:4]],
        current_implementation="\n".join(brief.files_to_inspect[:5]) or "No files were ranked.",
        what_would_break=brief.risk_notes[:4],
        open_questions=[artifact.summary for artifact in memory_artifacts[:3]],
        validation=brief.validation_checklist[:5],
        reasoning_map=brief.files_to_inspect[:5],
        system_lesson=(
            "Start at the system boundary the repo memory keeps pointing to, not the first "
            "local symptom."
        ),
        false_lead_analysis=[attempt.summary for attempt in attempts[:3]],
        mental_model_upgrade=(
            "Use repo memory to trace shared boundaries before optimizing a local implementation."
        ),
    )


def _active_task_line(active_tasks: list[TaskRecord]) -> str:
    if not active_tasks:
        return "- Active tasks: 0"
    if len(active_tasks) == 1:
        task = active_tasks[0]
        return f"- Active tasks: 1 (`{task.task_id}`) {task.title}"
    task_ids = ", ".join(f"`{task.task_id}`" for task in active_tasks[:3])
    suffix = "" if len(active_tasks) <= 3 else f", +{len(active_tasks) - 3} more"
    return f"- Active tasks: {len(active_tasks)} ({task_ids}{suffix})"


def _provider_label(config: ProjectConfig) -> str:
    if config.llm.provider is None or config.llm.model is None:
        return "not configured"
    return f"{config.llm.provider.value} ({config.llm.model})"


def _codegraph_file_score(record: RepoFileRecord, stat: FileStat | None) -> float:
    churn = float(stat.change_count if stat else 0)
    recent = float(stat.recent_change_count if stat else 0)
    size_weight = min(record.size_bytes / 4096.0, 8.0)
    source_weight = 0.0 if record.is_test else 2.0
    return recent * 5.0 + churn * 3.0 + size_weight + source_weight


def _codegraph_dirs(
    repo_files: list[RepoFileRecord],
    file_stats: list[FileStat],
) -> list[dict[str, int | str]]:
    churn_by_path = {stat.path: stat.change_count + stat.recent_change_count for stat in file_stats}
    grouped: dict[str, dict[str, int | str]] = {}
    for record in repo_files:
        bucket = path_bucket(record.path)
        current = grouped.setdefault(
            bucket,
            {"path": bucket, "files": 0, "tests": 0, "churn": 0, "bytes": 0},
        )
        current["files"] = int(current["files"]) + 1
        current["tests"] = int(current["tests"]) + (1 if record.is_test else 0)
        current["churn"] = int(current["churn"]) + churn_by_path.get(record.path, 0)
        current["bytes"] = int(current["bytes"]) + record.size_bytes
    return sorted(
        grouped.values(),
        key=lambda item: (int(item["churn"]), int(item["files"]), int(item["bytes"])),
        reverse=True,
    )


def _health_sections(health: dict[str, list[str]]) -> list[str]:
    handled = {"warnings", "errors"}
    ordered = [section for section in HEALTH_SECTION_ORDER if section in health]
    remaining = sorted(section for section in health if section not in {*ordered, *handled})
    return ordered + remaining


def _agent_readiness_markdown(summary: AgentReadinessSummary) -> str:
    lines: list[str] = []
    _append_report_header(lines, summary)
    _append_report_memory_and_tasks(lines, summary)
    _append_report_agent_integration(lines, summary)
    _append_report_health_sections(lines, summary)
    _append_report_recommendations(lines, summary)
    _append_report_share_snippet(lines, summary)
    return "\n".join(lines) + "\n"


def _append_report_header(lines: list[str], summary: AgentReadinessSummary) -> None:
    lines.extend(
        [
            "# ONMC Agent Readiness Report",
            "",
            f"- Generated: {summary.generated_at}",
            f"- Repository: `{summary.repo_name}`",
            f"- Root: `{summary.repo_root}`",
            f"- Branch: `{summary.branch}`",
            (
                f"- Agent readiness: **{summary.readiness_label}** "
                f"({summary.passed_checks}/{summary.total_checks} checks passing)"
            ),
            "",
        ]
    )


def _append_report_memory_and_tasks(
    lines: list[str], summary: AgentReadinessSummary
) -> None:
    lines.extend(
        [
            "## Memory and Task State",
            "",
            f"- Memory records: {summary.memory_count}",
            f"- Tasks: {summary.task_count}",
            f"- Attempts: {summary.attempt_count}",
            f"- Memory artifacts: {summary.memory_artifact_count}",
            f"- Task outputs: {summary.task_output_count}",
            f"- Last ingest: {summary.last_ingest_at}",
            _active_task_line(summary.active_tasks),
            "",
        ]
    )


def _append_report_agent_integration(
    lines: list[str], summary: AgentReadinessSummary
) -> None:
    lines.extend(
        [
            "## Agent Integration",
            "",
            f"- CLAUDE.md: {'present' if summary.claude_md_exists else 'missing'}",
            (
                "- Claude hooks: "
                f"{'installed' if summary.hooks.installed else 'not installed'}"
            ),
            (
                "- MCP server: "
                f"{'registered' if summary.hooks.mcp_registered else 'not registered'}"
            ),
            f"- Portable export: {'present' if summary.manifest_exists else 'missing'}",
            (
                "- Sync hook: "
                f"{'installed' if summary.sync_hook_installed else 'not installed'}"
            ),
            f"- LLM provider: {summary.provider_label}",
            "",
        ]
    )


def _append_report_health_sections(
    lines: list[str], summary: AgentReadinessSummary
) -> None:
    lines.extend(["## Health Signals", ""])
    for section in summary.health_sections:
        items = summary.health.get(section, [])
        if not items:
            continue
        lines.extend([f"### {section.title()}", ""])
        lines.extend(f"- {item}" for item in items)
        lines.append("")


def _append_report_recommendations(
    lines: list[str], summary: AgentReadinessSummary
) -> None:
    if summary.errors:
        lines.extend(["### Errors", ""])
        lines.extend(f"- {item}" for item in summary.errors)
        lines.append("")

    lines.extend(["### Recommended Next Actions", ""])
    if summary.warnings:
        lines.extend(f"- {item}" for item in summary.warnings)
    else:
        lines.append("- No immediate action required.")
    lines.append("")


def _append_report_share_snippet(
    lines: list[str], summary: AgentReadinessSummary
) -> None:
    lines.extend(
        [
            "## Share Snippet",
            "",
            (
                f"ONMC-ready repo: {summary.passed_checks}/{summary.total_checks} "
                f"checks passing, {summary.memory_count} memories, "
                f"{summary.task_count} tasks, {len(summary.active_tasks)} active handoffs."
            ),
            "",
            "Generated by `onmc report`.",
        ]
    )


def _git_count(repo_root: Path) -> int:
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return 0
    return int(result.stdout.strip() or "0")


def _git_commits_since(repo_root: Path, since: str) -> int:
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"--since={since}", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return 0
    return int(result.stdout.strip() or "0")


LEAKED_KEY_PATTERNS = (
    re.compile(r"sk-ant-api\d{2}-[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-(?:proj|live|test)-[A-Za-z0-9_-]{20,}"),
)


def _detect_leaked_keys(onmc_dir: Path) -> list[str]:
    """Return warning messages for probable provider secrets stored in ONMC state."""
    if not onmc_dir.exists():
        return []
    warnings: list[str] = []
    for path in onmc_dir.rglob("*"):
        if not path.is_file() or path.suffix not in {".yaml", ".json", ".jsonl", ".log"}:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(pattern.search(content) for pattern in LEAKED_KEY_PATTERNS):
            warnings.append(f"Possible API key found in {path}. Rotate the key immediately.")
    return warnings


def _is_recent_enough(timestamp: str) -> bool:
    from oh_no_my_claudecode.utils.time import parse_datetime

    parsed = parse_datetime(timestamp)
    if parsed is None:
        return False
    return (utc_now() - parsed).days < 7
