from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast

if TYPE_CHECKING:
    from oh_no_my_claudecode.ask.compiler import AskResult
    from oh_no_my_claudecode.audit.scanner import AuditReport
    from oh_no_my_claudecode.autopilot.models import AutopilotResult
    from oh_no_my_claudecode.benchmark.suite import BenchmarkReport
    from oh_no_my_claudecode.codegraph.models import (
        CodeGraph,
        ContextSelection,
        Neighbors,
    )
    from oh_no_my_claudecode.coverage.compiler import CoverageReport, CoverageSuggestion
    from oh_no_my_claudecode.digest.compiler import DigestResult
    from oh_no_my_claudecode.evals.models import EvalCase, EvalComparison, EvalReport
    from oh_no_my_claudecode.evolution.compiler import EvolutionReport
    from oh_no_my_claudecode.federation.pull import PullResult
    from oh_no_my_claudecode.fleet import FleetDoctorReport, FleetStatus
    from oh_no_my_claudecode.guard.compiler import GuardResult
    from oh_no_my_claudecode.importers.base import ImportResult
    from oh_no_my_claudecode.integrations.gh_aw import GhAwInitResult
    from oh_no_my_claudecode.integrations.plug import PlugResult
    from oh_no_my_claudecode.ledger.accounting import LedgerSummary
    from oh_no_my_claudecode.loop.models import AgentRunner, LoopResult, VerifyRunner
    from oh_no_my_claudecode.mcp_trust.gateway import Decision as McpDecision
    from oh_no_my_claudecode.mcp_trust.gateway import ToolCall as McpToolCall
    from oh_no_my_claudecode.pack import ContextPack
    from oh_no_my_claudecode.preflight.runner import Executor as PreflightExecutor
    from oh_no_my_claudecode.preflight.runner import PreflightReport
    from oh_no_my_claudecode.profile.compiler import UserProfile
    from oh_no_my_claudecode.recall.compiler import RecallResult
    from oh_no_my_claudecode.release import ReleaseDraft
    from oh_no_my_claudecode.replay.models import ReplayComparison, ReplayReport
    from oh_no_my_claudecode.reuse.radar import ReuseHit
    from oh_no_my_claudecode.savings.compiler import SavingsResult
    from oh_no_my_claudecode.spec.validator import SpecValidationReport
    from oh_no_my_claudecode.stats.health import MemoryHealth
    from oh_no_my_claudecode.trace.models import TraceReport
    from oh_no_my_claudecode.verifydiff.checker import VerifyReport

from oh_no_my_claudecode.blame.compiler import BlameResult, blame_result_to_markdown, compile_blame
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
    user_database_path,
    write_config,
)
from oh_no_my_claudecode.conventions import (
    Conventions,
    conventions_path,
    detect_conventions,
    render_conventions_markdown,
)
from oh_no_my_claudecode.core.repo import (
    RepoDiscoveryError,
    current_branch,
    discover_repo_root,
    path_bucket,
    resolve_hooks_dir,
)
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
from oh_no_my_claudecode.hooks.prompt_recall import compile_prompt_recall
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
from oh_no_my_claudecode.memory.consolidation import ConsolidationResult, consolidate_memories
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
    Playbook,
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
from oh_no_my_claudecode.onboard.compiler import OnboardingTour, compile_onboarding
from oh_no_my_claudecode.playbook.compiler import compile_playbooks
from oh_no_my_claudecode.prompt import compile_prompt
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.sync import export_agent_memory, restore_agent_memory
from oh_no_my_claudecode.sync.schema import SyncResult
from oh_no_my_claudecode.timetravel.memory_diff import MemoryDiffResult, diff_memory_at_commits
from oh_no_my_claudecode.utils.text import shorten, stable_id, tokenize, unique_preserve
from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now
from oh_no_my_claudecode.why.compiler import WhyReport, compile_why, why_report_to_markdown
from oh_no_my_claudecode.wiki import WikiFormat, build_obsidian_vault, build_wiki

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

    def why(
        self,
        path: str,
        *,
        no_llm: bool = False,
        at_commit: str = "",
    ) -> tuple[Path, WhyReport]:
        """Compile a `why` report for a file from stored memory + git history.

        When *at_commit* is given, the git-history section is bounded to that
        commit-ish.  Memory entries are not time-bounded (they reflect the current
        store) — the report is labelled clearly when this flag is used.
        """
        repo_root, config, storage = self._load_context()
        report = compile_why(repo_root, storage, path, at_commit=at_commit)
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

    def onboard(self) -> tuple[Path, OnboardingTour]:
        """Compile a guided new-dev tour from stored memory.

        Entirely offline — no LLM calls, no network access.  Always returns a
        valid tour; an empty store is represented honestly in stop 1.
        """
        repo_root, config, storage = self._load_context()
        tour = compile_onboarding(storage, repo_root)
        output_name = f"{utc_now().strftime('%Y%m%d-%H%M%S')}-onboard.md"
        output_path = compiled_dir(config, repo_root) / output_name
        output_path.write_text(tour.to_markdown(), encoding="utf-8")
        return repo_root, tour

    def blame(self, path: str) -> tuple[Path, BlameResult]:
        """Compile a blame (governance map) for a file from stored memory.

        Maps each top-level symbol in the file to the memories that govern it
        (invariants, decisions, hotspots, gotchas, etc.).  Memories that
        reference the file but don't name a specific symbol land in the
        file-level bucket.

        Entirely offline — no LLM calls, no network access.
        """
        repo_root, config, storage = self._load_context()
        result = compile_blame(repo_root, storage, path)
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", result.path)
        output_name = f"{utc_now().strftime('%Y%m%d-%H%M%S')}-blame-{safe_name}.md"
        output_path = compiled_dir(config, repo_root) / output_name
        output_path.write_text(blame_result_to_markdown(result), encoding="utf-8")
        result.output_path = output_path.as_posix()
        return repo_root, result

    def memory_diff(
        self,
        commit_a: str,
        commit_b: str,
    ) -> tuple[Path, MemoryDiffResult]:
        """Diff committed `.agent-memory/` snapshots between two commits.

        Reads the ``.agent-memory/memories/`` JSON tree at each commit via
        ``git show`` — does not touch live SQLite storage.  When the snapshot
        is absent at either commit, falls back to a plain ``git diff --name-only``
        and marks ``result.fallback_mode=True``.
        """
        repo_root, config, _ = self._load_context()
        result = diff_memory_at_commits(repo_root, commit_a, commit_b)
        from oh_no_my_claudecode.timetravel.memory_diff import memory_diff_to_markdown

        output_name = (
            f"{utc_now().strftime('%Y%m%d-%H%M%S')}-memory-diff-{commit_a[:8]}-{commit_b[:8]}.md"
        )
        output_path = compiled_dir(config, repo_root) / output_name
        output_path.write_text(memory_diff_to_markdown(result), encoding="utf-8")
        return repo_root, result

    def digest(
        self,
        since_ref: str,
    ) -> tuple[Path, DigestResult]:
        """Compile a knowledge changelog for everything learned since *since_ref*.

        Prefers the committed ``.agent-memory/`` diff path; falls back to
        ``created_at`` filtering when the export is not committed at *since_ref*.

        Returns:
            A tuple of (artifact_path, DigestResult).

        Raises:
            ValueError: When *since_ref* cannot be resolved to a git commit.
        """
        from oh_no_my_claudecode.digest.compiler import compile_digest, digest_to_markdown

        repo_root, config, storage = self._load_context()
        result = compile_digest(repo_root, storage, since_ref)
        output_name = (
            f"{utc_now().strftime('%Y%m%d-%H%M%S')}"
            f"-digest-since-{since_ref[:16].replace('/', '-')}.md"
        )
        out_dir = compiled_dir(config, repo_root)
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / output_name
        output_path.write_text(digest_to_markdown(result), encoding="utf-8")
        return output_path, result

    def generate_wiki(
        self,
        *,
        output_dir: Path | None = None,
        format: WikiFormat | str = WikiFormat.MARKDOWN,
    ) -> tuple[Path, list[Path]]:
        """Generate a multi-page markdown wiki from stored memory and write it to disk.

        Parameters
        ----------
        output_dir:
            Directory to write wiki pages into.  Defaults to
            ``<repo_root>/.onmc/wiki/``.  Pass an explicit path (e.g.
            ``docs/wiki``) to produce a committable copy.

        Returns
        -------
        tuple[Path, list[Path]]
            ``(repo_root, written_paths)`` where *written_paths* lists every
            page file that was written (may be empty when the store has no data
            and even the minimal index is written as a single entry).
        """
        repo_root, config, storage = self._load_context()
        wiki_format = WikiFormat(format)
        default_dir = "obsidian" if wiki_format is WikiFormat.OBSIDIAN else "wiki"
        out_dir = output_dir if output_dir is not None else (repo_root / ".onmc" / default_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        pages = (
            build_obsidian_vault(storage, repo_root)
            if wiki_format is WikiFormat.OBSIDIAN
            else build_wiki(storage, repo_root)
        )
        written: list[Path] = []
        for rel_path, content in sorted(pages.items()):
            dest = out_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            written.append(dest)
        return repo_root, written

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
            legacy_global_hooks=legacy_global_hooks_present(settings_path=user_settings_path(home)),
            latest_snapshot_id=latest_snapshot.id if latest_snapshot else None,
            last_pre_compact_at=meta.get("last_pre_compact_at"),
            last_session_start_at=meta.get("last_session_start_at"),
        )

    def plug(self, target: str) -> PlugResult:
        """Wire onmc into *target* coding agent for the current repo.

        Supported targets: claude-code, codex, cursor, omc, omx, all.
        Returns a :class:`PlugResult` describing what was written.
        """
        from oh_no_my_claudecode.integrations.plug import plug_target

        repo_root = discover_repo_root(self.cwd)
        return plug_target(target, repo_root=repo_root)

    def gh_aw_init(
        self,
        repo_root: Path | None = None,
        *,
        dry_run: bool = False,
        force: bool = False,
    ) -> GhAwInitResult:
        """Generate memory-aware GitHub Actions workflows into *repo_root*.

        Scaffolds four ``.github/workflows/onmc-*.yml`` files:
        onmc-issue-context, onmc-pr-preflight, onmc-pr-learn,
        onmc-weekly-audit.

        Args:
            repo_root: target repo path; defaults to the current repo root.
            dry_run:   report what would be written without writing anything.
            force:     overwrite existing managed files.

        Returns a :class:`GhAwInitResult`.
        """
        from oh_no_my_claudecode.integrations.gh_aw import run_gh_aw_init

        target = repo_root if repo_root is not None else discover_repo_root(self.cwd)
        return run_gh_aw_init(target, dry_run=dry_run, force=force)

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

    def boot_digest(self, *, home: Path | None = None) -> tuple[str, int]:
        """Compile a boot digest for session startup/resume/clear injection.

        Returns ``(digest_md, token_count)``. When the store has no meaningful
        memory, returns ``("", 0)`` — callers must emit nothing on stdout in
        that case so the session is never blocked.

        The digest is also written to ``.onmc/boot-digest.md`` as a debug
        artifact.

        *home* is injectable for tests (default: ``Path.home()``).
        """
        repo_root, config, storage = self._load_context()
        memories = storage.list_memories()
        tasks = storage.list_tasks()
        user_memories = self._load_user_memories(home=home)
        digest_md, token_count = compile_boot_digest(
            memories=memories,
            tasks=tasks,
            repo_name=repo_root.name,
            user_memories=user_memories,
        )
        if digest_md:
            write_boot_digest_artifact(
                state_dir=state_dir(config, repo_root),
                boot_digest_md=digest_md,
            )
        storage.set_meta("last_session_start_at", isoformat_utc(utc_now()))
        return digest_md, token_count

    def prompt_recall(self, prompt: str) -> str:
        """Return a relevance-ranked memory markdown block for *prompt*.

        Loads the onmc context, runs FTS candidate retrieval, reranks by token
        overlap + confidence + feedback score (with staleness penalty), and
        returns a tight markdown block bounded to ~300 tokens.

        Returns an empty string when onmc is not initialised, the store is
        empty, or no memories are relevant to the prompt.  Never raises.
        """
        try:
            repo_root, config, storage = self._load_context()
            recall_md, _ = compile_prompt_recall(storage, prompt)
            if recall_md:
                sd = state_dir(config, repo_root)
                sd.mkdir(parents=True, exist_ok=True)
                (sd / "prompt-recall.md").write_text(recall_md, encoding="utf-8")
            return recall_md
        except Exception:  # noqa: BLE001
            return ""

    def loop(
        self,
        goal: str,
        *,
        agent: str = "claude",
        max_iterations: int = 10,
        budget_tokens: int | None = None,
        verify_command: str = "pytest",
        dry_run: bool = False,
        max_cost_usd: float | None = None,
        max_wall_seconds: int | None = None,
        agent_runner: AgentRunner | None = None,
        verify_runner: VerifyRunner | None = None,
        isolate: bool = False,
        resume: bool = False,
    ) -> tuple[LoopResult, Path | None]:
        """Run a memory-grounded autonomous loop against *goal*.

        Each iteration recalls recorded dead-ends from memory (via compile_guard)
        so the agent cannot repeat known failures.  WIN outcomes are recorded as
        DECISION memories; LOSS outcomes are recorded as FAILED_APPROACH memories
        so future iterations skip them automatically via the guard.

        When *dry_run* is True, no agent or verify subprocess is invoked — only
        the prompt that WOULD be sent is computed and returned in
        ``result.iterations[0].action_summary``.  Safe to call without any
        configured agent.

        Parameters
        ----------
        goal:
            The task description passed to the agent on every iteration.
        agent:
            Which CLI agent to use.  One of ``"claude"`` (default) or
            ``"codex"``.  Ignored when *dry_run* is True.
        max_iterations:
            Hard cap on loop iterations.
        budget_tokens:
            Optional token budget; the loop stops before the next iteration
            when total tokens consumed so far would exceed this value.
        verify_command:
            Shell command run after each agent iteration; exit-code 0 = win.
        dry_run:
            Build the prompt and recall dead-ends without invoking the agent
            or verify.  Safe to run without any configured agent binary.
        max_cost_usd:
            Optional USD cost ceiling; the loop stops before the next iteration
            when cumulative cost exceeds this value.
        max_wall_seconds:
            Optional wall-clock timeout in seconds; the loop stops before the
            next iteration when elapsed time exceeds this value.
        agent_runner:
            Optional injectable :class:`~oh_no_my_claudecode.loop.models.AgentRunner`.
            When provided, used directly instead of building a real CLI runner.
            Intended for testing and for ``autopilot`` orchestration.  When
            ``None`` (default), a real runner is built from *agent*.
        verify_runner:
            Optional injectable :class:`~oh_no_my_claudecode.loop.models.VerifyRunner`.
            When provided, used directly instead of the default subprocess runner.
            Intended for testing.  When ``None`` (default), the default subprocess
            verify runner is used.
        isolate:
            When ``True``, run the loop inside a fresh ``git worktree add`` so
            all file changes are isolated.  On success (converged + verified)
            the worktree path is preserved; on failure the worktree is removed
            and no changes leak into the working tree.  Degrades gracefully
            (warns + continues in-place) when ``git worktree add`` fails.
        resume:
            When ``True``, load any existing checkpoint for this goal +
            verify_command pair and continue from the last saved iteration.
            When ``False`` (default), always start a fresh run.

        Returns
        -------
        tuple[LoopResult, Path | None]
            ``(result, receipt_path)`` where *receipt_path* is the path to the
            written tamper-evident run receipt (under
            ``.agent-memory/receipts/``), or ``None`` for dry-runs.
        """
        import time as _time

        from oh_no_my_claudecode.loop.adapters import (
            agent_binary_available,
            make_agent_runner,
        )
        from oh_no_my_claudecode.loop.checkpoint import FileCheckpointStore
        from oh_no_my_claudecode.loop.engine import (
            _build_brief,  # noqa: PLC2701
            _default_verify_runner,
            run_loop,
        )
        from oh_no_my_claudecode.loop.models import (
            AgentRunResult,
            IterationContract,
            LoopConfig,
            LoopResult,
            LoopSpec,
        )
        from oh_no_my_claudecode.loop.receipt import build_receipt, write_receipt

        repo_root, _, storage = self._load_context()
        spec = LoopSpec(goal=goal)
        config = LoopConfig(
            max_iterations=max_iterations,
            budget_tokens=budget_tokens,
            verify_command=verify_command,
            max_cost_usd=max_cost_usd,
            max_wall_seconds=max_wall_seconds,
            isolate=isolate,
            # Protect user-facing runs from token storms out of the box. The raw
            # engine leaves these at 0 (off) for backward-compatibility, but the
            # CLI/service layer enables sane circuit breakers by default.
            duplicate_action_limit=3,
            repeated_error_limit=3,
        )

        if dry_run:
            brief = _build_brief(storage, goal, None, 0)
            planned_prompt = f"## Goal\n\n{goal}\n\n" + brief
            dry_contract = IterationContract(
                iteration=0,
                prediction="[dry-run: no agent invoked]",
                action_summary=planned_prompt,
                files_touched=[],
                verify_passed=False,
                verify_output="[dry-run: no verify invoked]",
                outcome="loss",
                tokens=None,
            )
            dry_result = LoopResult(
                iterations=[dry_contract],
                converged=False,
                stop_reason="dry-run",
                recorded_memory_ids=[],
                total_tokens=0,
            )
            return dry_result, None

        # Resolve the verify runner (injected takes priority).
        resolved_verify_runner = (
            verify_runner if verify_runner is not None else _default_verify_runner
        )

        # Resolve the agent runner (injected takes priority).
        resolved_agent_runner: object
        if agent_runner is not None:
            resolved_agent_runner = agent_runner
        else:
            # Validate the agent selector and surface a clean error when the
            # binary is missing rather than letting subprocess raise obscure errors.
            if agent not in {"claude", "codex", "opencode"}:
                raise ValueError(
                    f"Unknown agent {agent!r}. Choose 'claude', 'codex', or 'opencode'."
                )

            if not agent_binary_available(agent):  # type: ignore[arg-type]

                def _missing_agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
                    del prompt, escalation_level
                    return AgentRunResult(
                        output=f"[{agent} binary not found on PATH — install it first]",
                        prediction="",
                        files_touched=[],
                        tokens=None,
                    )

                resolved_agent_runner = _missing_agent
            else:
                resolved_agent_runner = make_agent_runner(agent, repo_root)  # type: ignore[arg-type]  # noqa: PGH003

        # Always wire up a FileCheckpointStore so every run is resumable.
        checkpoint_store = FileCheckpointStore(repo_root)

        onmc_ver = _installed_onmc_version() or "unknown"
        wall_start = _time.monotonic()
        started_at = isoformat_utc(utc_now())

        result = run_loop(
            storage,
            repo_root,
            spec,
            config,
            agent_runner=resolved_agent_runner,
            verify_runner=resolved_verify_runner,
            checkpoint_store=checkpoint_store,
            resume=resume,
        )

        wall_seconds = _time.monotonic() - wall_start
        ended_at = isoformat_utc(utc_now())

        receipt = build_receipt(
            result,
            spec,
            config,
            repo_root=str(repo_root),
            agent=agent,
            model=None,
            wall_seconds=wall_seconds,
            onmc_version=onmc_ver,
            started_at=started_at,
            ended_at=ended_at,
        )
        receipt_path: Path | None = None
        with contextlib.suppress(Exception):
            receipt_path = write_receipt(repo_root, receipt)

        return result, receipt_path

    def autopilot(
        self,
        goal: str,
        *,
        agent: str = "claude",
        dry_run: bool = False,
        max_iterations: int = 10,
        budget_tokens: int | None = None,
        max_cost_usd: float | None = None,
        max_wall_seconds: int | None = None,
        verify_command: str = "pytest",
        agent_runner: AgentRunner | None = None,
        verify_runner: VerifyRunner | None = None,
        plan_model: str | None = None,
        execute_model: str | None = None,
        plan_runner: AgentRunner | None = None,
        isolate: bool = False,
    ) -> AutopilotResult:
        """Run the full KNOW→(PLAN)→ACT→PROVE→LEARN autopilot cycle against *goal*.

        Orchestrates all existing onmc commands in a single narrated run:
        KNOW (brief + guard + profile), optional PLAN (expensive model writes a
        precise implementation plan), ACT (loop with optional cheap execute_model),
        PROVE (verify), LEARN (capture + skill_promote + consolidate), ending with
        a brain-growth delta.

        Parameters
        ----------
        goal:
            The task/goal to work on.
        agent:
            Which CLI agent to use (``"claude"`` or ``"codex"``).
        dry_run:
            When True, only run KNOW phase and return without invoking any agent
            or verify subprocess.  No memory writes, no cost.
        max_iterations, budget_tokens, max_cost_usd, max_wall_seconds, verify_command:
            Forwarded to :meth:`loop`.
        agent_runner, verify_runner:
            Optional injectable runners for testing.  When ``None`` (default),
            real CLI runners are used.
        plan_model:
            Optional expensive model name for the PLAN step.  When set, a planning
            pass runs before ACT; the plan text is injected into the ACT goal and
            recorded as a memory.  When ``None`` (default), no plan step runs.
        execute_model:
            Optional cheap model name for the ACT step.  When ``None``, the loop
            uses its own default.  Ignored when *agent_runner* is injected.
        plan_runner:
            Optional injectable runner for the PLAN step (testing).  When ``None``
            and *plan_model* is set, a real runner is built from *agent* +
            *plan_model*.
        isolate:
            When True, run ACT inside a fresh git worktree via ``loop``.

        Returns
        -------
        AutopilotResult
            Full structured result including brain delta and LEARN outcomes.
        """
        from oh_no_my_claudecode.autopilot.orchestrator import run_autopilot

        return run_autopilot(
            self,
            goal,
            agent=agent,
            dry_run=dry_run,
            max_iterations=max_iterations,
            budget_tokens=budget_tokens,
            max_cost_usd=max_cost_usd,
            max_wall_seconds=max_wall_seconds,
            verify_command=verify_command,
            agent_runner=agent_runner,
            verify_runner=verify_runner,
            plan_model=plan_model,
            execute_model=execute_model,
            plan_runner=plan_runner,
            isolate=isolate,
        )

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

    def capture_session(
        self,
        *,
        session_id: str | None = None,
        transcript_path: Path | None = None,
    ) -> int:
        """Heuristically capture durable memory from a session transcript.

        Reads the transcript at *transcript_path* (if supplied) or discovers the
        most-recent transcript for the repo that matches *session_id* (if
        given).  Extracts high-signal patterns (fixes, decisions, invariants,
        notes) without any LLM call, deduplicates against the existing store via
        ``stable_id``, and writes new entries tagged with
        ``source_type=SourceType.SESSION``.

        Returns the number of new memories written.  Never raises — any error
        produces 0 writes.
        """
        from oh_no_my_claudecode.mine.autocapture import capture_from_transcript
        from oh_no_my_claudecode.mine.transcript import discover_transcripts

        try:
            repo_root, _, storage = self._load_context()
        except Exception:  # noqa: BLE001
            return 0

        try:
            if transcript_path is not None:
                resolved_path: Path = transcript_path
                resolved_id = session_id or transcript_path.stem
            else:
                candidates = discover_transcripts(repo_root, session_id=session_id)
                if not candidates:
                    return 0
                resolved_path = candidates[-1]
                resolved_id = session_id or resolved_path.stem

            entries = capture_from_transcript(
                resolved_path,
                session_id=resolved_id,
                repo_root=repo_root,
            )
        except Exception:  # noqa: BLE001
            return 0

        if not entries:
            return 0

        try:
            inserted, _ = storage.upsert_memories(entries)
        except Exception:  # noqa: BLE001
            return 0
        return inserted

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
            f"{len(memories)} memory records ({llm_extracted} LLM-extracted, {heuristic} heuristic)"
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
            if config.llm.provider == LLMProviderType.OLLAMA:
                # Local, keyless provider — check server reachability instead.
                reachable, detail = validate_provider_api_key(config.llm.provider, "")
                if reachable:
                    report["provider"].append(detail)
                else:
                    report["warnings"].append(
                        f"Ollama provider configured but {detail}. "
                        "Start a local Ollama server to enable LLM features."
                    )
            elif not key_var:
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
                        report["errors"].append(f"{provider_name} key is invalid. Check {key_var}.")
                    else:
                        report["warnings"].append(f"Could not validate {key_var}: {detail}.")
        # --- PATH / binary health (check 1 + 2) ---
        path_checks = _check_onmc_path_health()
        onmc_resolvable = any(sev == "ok" for sev, _ in path_checks)
        for severity, message in path_checks:
            if severity == "ok":
                report["claude"].append(message)
            else:
                report["warnings"].append(message)

        hook_status = self.hooks_status()
        report["claude"].append(
            "Compaction hooks "
            f"{'installed' if hook_status.installed else 'not installed'} "
            "(.claude/settings.json)"
        )
        if hook_status.installed and not onmc_resolvable:
            report["warnings"].append(
                "Hooks are installed in .claude/settings.json but the `onmc` binary is "
                "not resolvable on PATH — hooks will silently fail. "
                "Fix PATH or reinstall via `pip install oh-no-my-claudecode`."
            )

        # --- MCP sanity (check 3) ---
        mcp_registered_ok = hook_status.mcp_registered
        report["claude"].append(
            f"MCP server {'registered' if mcp_registered_ok else 'not registered'} (.mcp.json)"
        )
        if mcp_registered_ok:
            # Verify the MCP entry's command resolves to a working binary.
            mcp_path = mcp_config_path(repo_root)
            mcp_command = _read_mcp_command(mcp_path)
            if mcp_command:
                mcp_binary = shutil.which(mcp_command)
                if mcp_binary is None:
                    report["warnings"].append(
                        f"MCP server is registered but its command `{mcp_command}` is not "
                        "resolvable — the MCP server will fail to start."
                    )
                else:
                    report["claude"].append(f"MCP command resolvable ({mcp_binary})")

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
        post_commit = resolve_hooks_dir(repo_root) / "post-commit"
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

    def list_repo_files(self) -> list[RepoFileRecord]:
        """Return files indexed during the latest ingest."""
        _, _, storage = self._load_context()
        return storage.list_repo_files()

    def list_file_stats(self) -> list[FileStat]:
        """Return git-derived file activity statistics."""
        _, _, storage = self._load_context()
        return storage.list_file_stats()

    # ------------------------------------------------------------------
    # Structural code graph (deterministic, offline)
    # ------------------------------------------------------------------

    def codegraph_build(self) -> tuple[Path, CodeGraph]:
        """Build the structural code graph and cache it to ``.onmc/codegraph.json``.

        Walks every ``*.py`` file under the repo root via :mod:`ast` (no LLM,
        no network), assembles symbols + import edges + blast-radius +
        test-mapping, and writes a deterministic JSON cache.  Returns the
        ``(cache_path, graph)`` pair.
        """
        from oh_no_my_claudecode.codegraph.builder import build_codegraph

        repo_root, config, _ = self._load_context()
        graph = build_codegraph(repo_root)
        cache_path = self._codegraph_cache_path(config, repo_root)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(graph.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return cache_path, graph

    def codegraph_neighbors(self, target: str) -> Neighbors:
        """Return the blast radius (importers + dependents + tests) for *target*.

        Loads the cached graph, building it on demand if no cache exists.
        *target* may be a repo-relative file path or a bare symbol name.
        """
        from oh_no_my_claudecode.codegraph.builder import neighbors

        graph = self._load_or_build_codegraph()
        return neighbors(graph, target)

    def codegraph_context(self, goal: str, *, budget: int = 8) -> ContextSelection:
        """Return a bounded set of files relevant to *goal*.

        Loads the cached graph (building on demand), tokenises the goal, and
        scores files by path + symbol matches, capping the result at *budget*.
        """
        from oh_no_my_claudecode.codegraph.builder import context_files

        graph = self._load_or_build_codegraph()
        return context_files(graph, goal, budget=budget)

    def pack(self, goal: str, *, budget_chars: int = 6000) -> ContextPack:
        """Build a compact context pack for spawned agents."""
        from oh_no_my_claudecode.pack import compile_context_pack

        repo_root, config, storage = self._load_context()
        return compile_context_pack(
            repo_root,
            config,
            storage,
            goal,
            budget_chars=budget_chars,
        )

    def _load_or_build_codegraph(self) -> CodeGraph:
        """Return the cached :class:`CodeGraph`, rebuilding if absent or invalid."""
        from oh_no_my_claudecode.codegraph.builder import build_codegraph
        from oh_no_my_claudecode.codegraph.models import CodeGraph

        repo_root, config, _ = self._load_context()
        cache_path = self._codegraph_cache_path(config, repo_root)
        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                return CodeGraph.from_dict(payload)
        return build_codegraph(repo_root)

    @staticmethod
    def _codegraph_cache_path(config: ProjectConfig, repo_root: Path) -> Path:
        """Path to the cached code graph JSON (``.onmc/codegraph.json``)."""
        return state_dir(config, repo_root) / "codegraph.json"

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
        sync_hook_path = resolve_hooks_dir(repo_root) / "post-commit"
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

    def pull(
        self,
        source: str | Path,
        *,
        ref: str | None = None,
        repo_label: str | None = None,
    ) -> tuple[Path, PullResult]:
        """Import memories from another repo's ``.agent-memory/`` export.

        Accepts either a local path or a remote git URL.  When *source* is a
        git URL (``https://``, ``http://``, ``git@``, ``ssh://``, or ending
        with ``.git``) the repo is shallow-cloned to a temporary directory,
        its ``.agent-memory/`` is imported, and the clone is removed.

        Federated memories are stamped with a ``federated:<repo-label>`` tag so
        they are clearly attributed to their origin and are never confused with
        local memories.  Re-pulling is idempotent: memories already present in
        the local store are skipped.

        Parameters
        ----------
        source:
            Local path (str or Path) to another repo root or its
            ``.agent-memory/`` directory, **or** a remote git URL.
        ref:
            Branch, tag, or commit-ish to check out when cloning a remote URL.
            Ignored for local paths.  Defaults to the remote's default branch.
        repo_label:
            Override the short label used for the ``federated:`` namespace tag.
            For local paths defaults to the source directory name; for remote
            URLs defaults to the last path segment of the URL (minus ``.git``).

        Returns
        -------
        tuple[Path, PullResult]
            ``(local_repo_root, result)`` where *result* carries imported/skipped counts.
        """
        from oh_no_my_claudecode.federation.pull import PullResult as _PullResult
        from oh_no_my_claudecode.federation.pull import pull_memories
        from oh_no_my_claudecode.federation.remote import clone_and_pull, is_git_url

        repo_root, _, storage = self._load_context()

        source_str = str(source)
        result: _PullResult
        if is_git_url(source_str):
            result = clone_and_pull(
                storage,
                source_str,
                ref=ref,
                repo_label=repo_label,
            )
        else:
            source_path = source if isinstance(source, Path) else Path(source_str)
            result = pull_memories(storage, source_path, repo_label=repo_label)

        return repo_root, result

    def pull_all(
        self,
        *,
        dry_run: bool = False,
    ) -> tuple[Path, list[tuple[str, PullResult | Exception]]]:
        """Pull memories from every source in ``federation.sources`` config.

        Iterates the configured sources in order.  For each source, dispatches
        to :func:`~oh_no_my_claudecode.federation.remote.clone_and_pull` (git
        URL) or :func:`~oh_no_my_claudecode.federation.pull.pull_memories`
        (local path), mirroring :meth:`pull`.

        One source failing never aborts the rest — errors are captured
        per-source and returned alongside successful :class:`PullResult` objects.

        Parameters
        ----------
        dry_run:
            When *True*, print what would be pulled without writing any
            memories.

        Returns
        -------
        tuple[Path, list[tuple[str, PullResult | Exception]]]
            ``(local_repo_root, results)`` where *results* is an ordered list of
            ``(source_identifier, PullResult | Exception)`` — one entry per
            configured source.
        """
        from oh_no_my_claudecode.federation.pull import PullResult as _PullResult
        from oh_no_my_claudecode.federation.pull import pull_memories
        from oh_no_my_claudecode.federation.remote import clone_and_pull, is_git_url

        repo_root, config, storage = self._load_context()
        results: list[tuple[str, _PullResult | Exception]] = []

        for federation_source in config.federation.sources:
            src = federation_source.path_or_url
            label = federation_source.label
            ref = federation_source.ref
            if dry_run:
                results.append(
                    (src, _PullResult(source=src, repo_label=label or "", imported=0, skipped=0))
                )
                continue
            try:
                if is_git_url(src):
                    result = clone_and_pull(storage, src, ref=ref, repo_label=label)
                else:
                    result = pull_memories(storage, Path(src), repo_label=label)
                results.append((src, result))
            except Exception as exc:  # noqa: BLE001
                results.append((src, exc))

        return repo_root, results

    def spec_validate(self, path: Path | None = None) -> tuple[Path, SpecValidationReport]:
        """Validate that a .agent-memory/ directory conforms to the open spec."""
        from oh_no_my_claudecode.spec.validator import validate_agent_memory_dir

        repo_root = discover_repo_root(self.cwd)
        target = path or repo_root / ".agent-memory"
        report = validate_agent_memory_dir(target)
        return repo_root, report

    def spec_print(self) -> str:
        """Return a summary of the Agent Memory Spec version and schema."""
        from oh_no_my_claudecode.spec.validator import (
            _MEMORY_KIND_VALUES,
            _SOURCE_TYPE_VALUES,
            _TASK_STATUS_VALUES,
            SPEC_VERSION,
        )

        lines = [
            f"Agent Memory Format Specification  version={SPEC_VERSION}",
            "",
            "MemoryKind values:    " + ", ".join(sorted(_MEMORY_KIND_VALUES)),
            "SourceType values:    " + ", ".join(sorted(_SOURCE_TYPE_VALUES)),
            "TaskStatus values:    " + ", ".join(sorted(_TASK_STATUS_VALUES)),
            "",
            "Full spec: AGENT-MEMORY-SPEC.md",
            "Reference implementation: onmc (oh-no-my-claudecode)",
        ]
        return "\n".join(lines)

    def install_sync_hook(self) -> tuple[Path, Path]:
        """Install a post-commit hook that exports ONMC memory to .agent-memory."""
        repo_root = discover_repo_root(self.cwd)
        hook_path = resolve_hooks_dir(repo_root) / "post-commit"
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
        hook_path = resolve_hooks_dir(repo_root) / "post-commit"
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

    # Feedback delta constants.
    # ``up`` nudges the memory toward corroborated; ``down`` demotes it.
    # Deltas are intentionally modest so a few votes move the score, not a single one.
    _FEEDBACK_UP_SCORE: float = 0.25
    _FEEDBACK_DOWN_SCORE: float = 0.3
    _FEEDBACK_UP_CONFIDENCE: float = 0.05
    _FEEDBACK_DOWN_CONFIDENCE: float = 0.05
    # floor: never drop confidence to zero — keep the memory discoverable
    _FEEDBACK_CONFIDENCE_FLOOR: float = 0.15

    def feedback(
        self,
        memory_id: str,
        direction: str,
        *,
        note: str | None = None,
    ) -> MemoryEntry:
        """Apply a human trust signal to a memory.

        ``direction`` must be ``"up"`` (memory proved useful) or ``"down"``
        (memory was wrong or misleading).

        ``up``  increases ``feedback_score`` by ``_FEEDBACK_UP_SCORE`` (clamped
                to 1.0) and nudges ``confidence`` up by ``_FEEDBACK_UP_CONFIDENCE``
                (clamped to 1.0).

        ``down`` decreases ``feedback_score`` by ``_FEEDBACK_DOWN_SCORE``
                (clamped to -1.0) and nudges ``confidence`` down by
                ``_FEEDBACK_DOWN_CONFIDENCE`` (clamped at ``_FEEDBACK_CONFIDENCE_FLOOR``
                so the memory remains visible but ranked lower).

        ``updated_at`` is always touched so the decay clock restarts from now,
        treating fresh feedback as corroboration even for "down" votes.

        If *note* is given it is appended to ``details`` on a new line (only
        when non-empty).

        Raises:
            ValueError: When ``direction`` is not ``"up"`` or ``"down"``.
            LookupError: When ``memory_id`` does not exist.
        """
        if direction not in ("up", "down"):
            msg = f"direction must be 'up' or 'down', got {direction!r}"
            raise ValueError(msg)
        _, _, storage = self._load_context()
        memory = self.get_memory(memory_id)
        if memory is None:
            msg = f"Memory not found: {memory_id}"
            raise LookupError(msg)
        if direction == "up":
            new_feedback = min(memory.feedback_score + self._FEEDBACK_UP_SCORE, 1.0)
            new_confidence = min(memory.confidence + self._FEEDBACK_UP_CONFIDENCE, 1.0)
        else:
            new_feedback = max(memory.feedback_score - self._FEEDBACK_DOWN_SCORE, -1.0)
            new_confidence = max(
                memory.confidence - self._FEEDBACK_DOWN_CONFIDENCE,
                self._FEEDBACK_CONFIDENCE_FLOOR,
            )
        updates: dict[str, object] = {
            "feedback_score": new_feedback,
            "confidence": new_confidence,
            "updated_at": utc_now(),
        }
        if note and note.strip():
            updates["details"] = (
                (memory.details.rstrip() + "\n\n" + note.strip())
                if memory.details and memory.details.strip()
                else note.strip()
            )
        updated = memory.model_copy(update=updates)
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

    def memory_health(self) -> MemoryHealth:
        """Compute a :class:`MemoryHealth` snapshot for this repo."""
        from oh_no_my_claudecode.stats.health import compute_memory_health

        repo_root, config, storage = self._load_context()
        log_path = self._llm_log_path(repo_root, config)
        return compute_memory_health(storage, repo_root, log_path)

    def coverage(
        self,
        *,
        suggest: bool = False,
        apply: bool = False,
    ) -> tuple[Path, CoverageReport, list[CoverageSuggestion]]:
        """Compute a knowledge-gap dashboard for this repo.

        Returns ``(repo_root, CoverageReport, suggestions)`` where *suggestions*
        is non-empty only when *suggest* or *apply* is True.

        Parameters
        ----------
        suggest:
            When True, derive a :class:`~oh_no_my_claudecode.coverage.compiler.CoverageSuggestion`
            for each top uncovered hotspot.
        apply:
            When True, create stub memory entries (low confidence, tagged
            ``coverage-stub``) for each suggestion that does not already exist
            in the store.  Implies *suggest*.

        Entirely offline — no LLM calls, no network access.  Requires an
        initialised store with at least one ingest run (file stats must exist).
        """
        from oh_no_my_claudecode.coverage.compiler import CoverageReport as _CoverageReport
        from oh_no_my_claudecode.coverage.compiler import (
            CoverageSuggestion as _CoverageSuggestion,
        )
        from oh_no_my_claudecode.coverage.compiler import compile_coverage, suggest_coverage

        repo_root, _, storage = self._load_context()
        report: _CoverageReport = compile_coverage(storage, repo_root)

        suggestions: list[_CoverageSuggestion] = []
        if suggest or apply:
            suggestions = suggest_coverage(report, repo_root)

        if apply and suggestions:
            now = utc_now()
            entries: list[MemoryEntry] = []
            for sug in suggestions:
                mem_id = stable_id(
                    "coverage-stub",
                    sug.file,
                    sug.suggested_title,
                    prefix=sug.suggested_kind.value,
                )
                summary = (
                    f"[coverage-stub] {sug.suggested_title}. {sug.rationale}"
                )
                entries.append(
                    MemoryEntry(
                        id=mem_id,
                        kind=sug.suggested_kind,
                        title=sug.suggested_title,
                        summary=summary,
                        details=summary,
                        source_type=SourceType.MANUAL,
                        source_ref=sug.file,
                        tags=unique_preserve(["coverage-stub", sug.subsystem]),
                        confidence=0.2,
                        created_at=now,
                        updated_at=now,
                    )
                )
            storage.upsert_memories(entries)

        return repo_root, report, suggestions

    def benchmark(
        self,
        *,
        runs: int = 20,
    ) -> tuple[Path, BenchmarkReport]:
        """Run the reproducible benchmark suite against the current repo brain.

        Entirely offline — no LLM calls, no network access.  Returns a
        :class:`~oh_no_my_claudecode.benchmark.suite.BenchmarkReport` with
        metrics labelled MEASURED (live timing / counts) or SIM (deterministic
        simulation).

        Parameters
        ----------
        runs:
            Number of timing repetitions for each timed benchmark.  Higher
            values produce more stable p95 latencies (default: 20).

        Returns
        -------
        tuple[Path, BenchmarkReport]
            ``(repo_root, report)``
        """
        from oh_no_my_claudecode.benchmark.suite import run_benchmark_suite

        repo_root, _, storage = self._load_context()
        now_str = isoformat_utc(utc_now())
        report = run_benchmark_suite(storage, repo_root, runs=runs, now=now_str)
        return repo_root, report

    def savings(self) -> tuple[Path, SavingsResult]:
        """Compute a Memory Wrapped :class:`~oh_no_my_claudecode.savings.compiler.SavingsResult`.

        Entirely offline — no LLM calls, no network access.  Results are
        deterministic: given the same memory store they always produce the same
        numbers.  Token-ROI figures are labelled as a simulation; see
        ``bench/harness.py`` for the methodology.

        Returns
        -------
        tuple[Path, SavingsResult]
            ``(repo_root, result)``
        """
        from oh_no_my_claudecode.savings.compiler import SavingsResult as _SavingsResult
        from oh_no_my_claudecode.savings.compiler import compile_savings

        repo_root, _, storage = self._load_context()
        now_str = isoformat_utc(utc_now())
        result: _SavingsResult = compile_savings(storage, repo_root, now=now_str)
        return repo_root, result

    def evolution(self) -> tuple[Path, EvolutionReport]:
        """Compile an evolution report from the run-receipt chain.

        Reads all ``run-*.json`` receipts written by ``onmc loop`` /
        ``onmc autopilot`` from ``.agent-memory/receipts/`` and computes
        compounding-proof trend metrics (cost, iterations, verified rate).

        Entirely offline — no LLM calls, no network access.  All numbers
        come directly from real receipt data; proxies are labelled honestly.

        Returns
        -------
        tuple[Path, EvolutionReport]
            ``(repo_root, report)``
        """
        from oh_no_my_claudecode.evolution.compiler import (
            EvolutionReport as _EvolutionReport,
        )
        from oh_no_my_claudecode.evolution.compiler import compile_evolution

        repo_root = discover_repo_root(self.cwd)
        receipts_dir = repo_root / ".agent-memory" / "receipts"
        report: _EvolutionReport = compile_evolution(receipts_dir)
        return repo_root, report

    def ledger_summary(self, *, scope: str = "project") -> tuple[Path, LedgerSummary]:
        """Compile an agent-work accounting summary from run receipts.

        Reads ``RunReceipt`` JSON files written by ``onmc loop`` / ``onmc
        swarm`` from ``.agent-memory/receipts/`` and aggregates cost, wall-time,
        success-rate, and per-model / per-agent breakdowns.

        Entirely offline — no LLM calls, no network access.  Honest: receipts
        with no ``cost_usd`` are excluded from the cost total (never fabricated)
        and surfaced via the summary's ``cost_unknown_count`` / ``note``.

        Parameters
        ----------
        scope:
            ``"today"`` filters to receipts dated today (UTC); any other value
            ("project") includes all receipts.

        Returns
        -------
        tuple[Path, LedgerSummary]
            ``(repo_root, summary)``
        """
        from oh_no_my_claudecode.ledger.accounting import (
            LedgerSummary as _LedgerSummary,
        )
        from oh_no_my_claudecode.ledger.accounting import (
            load_receipts,
            summarize_receipts,
        )

        repo_root = discover_repo_root(self.cwd)
        receipts = load_receipts(repo_root, scope=scope)
        summary: _LedgerSummary = summarize_receipts(receipts, scope=scope)
        return repo_root, summary

    # ------------------------------------------------------------------
    # Trace Observatory
    # ------------------------------------------------------------------

    def trace_start(self, *, label: str = "") -> tuple[Path, str | None]:
        """Start a new trace session.

        Creates ``.onmc/traces/<session_id>.jsonl`` and sets the ``current``
        pointer.  Entirely offline — no LLM calls.

        Parameters
        ----------
        label:
            Optional human-readable label (e.g. ``"Codex task: add timeout"``).

        Returns
        -------
        tuple[Path, str | None]
            ``(repo_root, session_id)`` — ``session_id`` is ``None`` on I/O
            failure.
        """
        from oh_no_my_claudecode.trace.recorder import start_session

        repo_root, _, _ = self._load_context()
        session_id = start_session(repo_root, label=label)
        return repo_root, session_id

    def trace_stop(self) -> tuple[Path, bool]:
        """Close the current trace session.

        Returns
        -------
        tuple[Path, bool]
            ``(repo_root, success)``
        """
        from oh_no_my_claudecode.trace.recorder import stop_session

        repo_root, _, _ = self._load_context()
        ok = stop_session(repo_root)
        return repo_root, ok

    def trace_report(
        self,
        session_id: str | None = None,
    ) -> tuple[Path, str, TraceReport]:
        """Compile and return a :class:`~oh_no_my_claudecode.trace.models.TraceReport`.

        Parameters
        ----------
        session_id:
            Session to report on.  Defaults to the current active session.

        Returns
        -------
        tuple[Path, str, TraceReport]
            ``(repo_root, session_id, report)``

        Raises
        ------
        FileNotFoundError
            If no session is found for *session_id*.
        """
        from oh_no_my_claudecode.trace.recorder import (
            current_session_id,
            load_session_events,
        )
        from oh_no_my_claudecode.trace.report import compile_trace_report

        repo_root, _, _ = self._load_context()

        sid = session_id
        if sid is None:
            sid = current_session_id(repo_root)
        if sid is None:
            msg = "No active trace session.  Run 'onmc trace start' first."
            raise FileNotFoundError(msg)

        session, events = load_session_events(repo_root, sid)
        if session is None:
            msg = f"Trace session '{sid}' not found."
            raise FileNotFoundError(msg)

        report = compile_trace_report(events, session=session)
        return repo_root, sid, report

    def replay(
        self,
        session_id_or_path: str,
        *,
        compare: bool = False,
        with_memory: bool = True,
        recall_limit: int = 8,
    ) -> tuple[Path, ReplayReport | ReplayComparison]:
        """Re-derive onmc memory hits over a recorded trace session.

        Loads a session from ``.onmc/traces/<session_id>.jsonl`` (by session_id)
        or from a direct JSONL file path.  For each query-bearing event in the
        session, runs :func:`~oh_no_my_claudecode.recall.compiler.compile_recall`
        and :func:`~oh_no_my_claudecode.guard.compiler.compile_guard` against the
        current brain and returns a regression report.

        No LLM is called.  Deterministic and offline.

        Parameters
        ----------
        session_id_or_path:
            A session ID (``tr_…``) or an absolute / relative file path to a
            ``.jsonl`` session file.
        compare:
            When ``True``, run both ``with_memory=True`` and ``with_memory=False``
            and return a :class:`~oh_no_my_claudecode.replay.models.ReplayComparison`.
        with_memory:
            When ``False`` and *compare* is ``False``, run the cold (no-memory)
            baseline only.  Ignored when *compare* is ``True``.
        recall_limit:
            Max entries per :func:`compile_recall` call.

        Returns
        -------
        tuple[Path, ReplayReport | ReplayComparison]
            ``(repo_root, report_or_comparison)``

        Raises
        ------
        FileNotFoundError
            When the session file cannot be found.
        """
        from oh_no_my_claudecode.replay.lab import compare_replay, replay_session
        from oh_no_my_claudecode.trace.recorder import load_session_events

        repo_root, _, storage = self._load_context()

        # Resolve the session file.
        candidate_path = Path(session_id_or_path)
        if candidate_path.exists():
            # Treat it as a direct JSONL path.
            resolved_path = candidate_path
            resolved_sid = candidate_path.stem
        else:
            # Treat it as a session_id.
            traces_dir = repo_root / ".onmc" / "traces"
            resolved_path = traces_dir / f"{session_id_or_path}.jsonl"
            resolved_sid = session_id_or_path

        if not resolved_path.exists():
            msg = (
                f"Trace session not found: {session_id_or_path!r}. "
                "Run 'onmc trace start' to record a session."
            )
            raise FileNotFoundError(msg)

        # Load events using the standard loader.
        session, events = load_session_events(
            resolved_path.parent.parent.parent,  # repo_root for load_session_events
            resolved_sid,
        )
        # If load_session_events fails (e.g. path-based input outside traces dir),
        # fall back to reading the JSONL file directly.
        if session is None and not events:
            import json

            raw_lines = resolved_path.read_text(encoding="utf-8").splitlines()
            from oh_no_my_claudecode.trace.models import TraceEvent, TraceSession

            for raw_line in raw_lines:
                line = raw_line.strip()
                if not line:
                    continue
                record = json.loads(line)
                rec_type = record.get("_type", "")
                if rec_type == "session":
                    session = TraceSession.from_record(record)
                elif rec_type != "session_end":
                    events.append(TraceEvent.from_record(record))

        sid = session.session_id if session is not None else resolved_sid

        if compare:
            result: ReplayReport | ReplayComparison = compare_replay(
                storage, events, session_id=sid, recall_limit=recall_limit
            )
        else:
            result = replay_session(
                storage,
                events,
                session_id=sid,
                with_memory=with_memory,
                recall_limit=recall_limit,
            )
        return repo_root, result

    def statusline(self) -> str:
        """Return a compact one-line health string for Claude Code statusLine.

        Includes a memory-health segment: memory count, skill count, and the
        simulated context-token savings percentage from the bench harness.

        Never raises — degrades to a minimal string when not initialised.
        """
        try:
            h = self.memory_health()
            tok_k = h.recent_cost.total_tokens // 1000
            raw_tok = h.recent_cost.total_tokens
            tok_label = f"{tok_k}k tok/day" if tok_k >= 1 else f"{raw_tok} tok/day"

            # Memory-health segment: counts + simulated savings %.
            # Skills count comes from storage directly (cheap read).
            try:
                _, _, storage = self._load_context()
                skills_count = len(storage.list_skills())
                from oh_no_my_claudecode.bench.harness import (
                    BUILTIN_SCENARIO,
                    BenchScenario,
                    MemoryRecord,
                    run_benchmark,
                )
                repo_memories = [
                    MemoryRecord(kind=m.kind.value, summary=m.summary, relevant_to=[])
                    for m in storage.list_memories()
                ]
                _scenario = BenchScenario(
                    name="statusline",
                    description="",
                    tasks=list(BUILTIN_SCENARIO.tasks),
                    memories=repo_memories or list(BUILTIN_SCENARIO.memories),
                    baseline_context_tokens=BUILTIN_SCENARIO.baseline_context_tokens,
                )
                _bench = run_benchmark(_scenario)
                ctx_pct = _bench.context_tokens_pct_reduction
                mem_segment = (
                    f" · {skills_count} skills · ~{ctx_pct:.0f}% ctx saved (sim)"
                )
            except Exception:  # noqa: BLE001
                mem_segment = ""

            return (
                f"🧠 {h.total_memories} mem"
                f" · {h.freshness_pct:.0f}% fresh"
                f" · {h.stale_count} stale"
                f" · {tok_label}"
                f"{mem_segment}"
            )
        except (FileNotFoundError, LookupError):
            return "🧠 onmc not initialized"
        except Exception:  # noqa: BLE001
            return "🧠 onmc error"

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
        markdown = (
            "\n".join(
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
            ).strip()
            + "\n"
        )
        output_path.write_text(markdown, encoding="utf-8")
        return output_path

    # ── Playbook methods ───────────────────────────────────────────────────────

    def generate_playbooks(
        self,
        *,
        no_llm: bool = False,
        write_artifacts: bool = True,
    ) -> tuple[Path, list[Playbook], list[str]]:
        """Synthesize playbooks from stored memory, persist them, and write artifacts.

        Returns ``(repo_root, playbooks, artifact_paths)``.
        """
        repo_root, config, storage = self._load_context()
        memories = storage.list_memories()
        provider = self._optional_provider(config=config, no_llm=no_llm)
        playbooks = compile_playbooks(
            memories,
            provider=provider,
            no_llm=no_llm,
            log_path=self._llm_log_path(repo_root, config),
        )

        # Persist to storage (upsert so regeneration is idempotent).
        storage.upsert_playbooks(playbooks)

        artifact_paths: list[str] = []
        if write_artifacts and playbooks:
            artifact_paths = self._write_playbook_artifacts(
                repo_root=repo_root,
                config=config,
                playbooks=playbooks,
            )

        return repo_root, playbooks, artifact_paths

    def list_playbooks(self) -> list[Playbook]:
        """Return all persisted playbooks ordered by confidence."""
        _, _, storage = self._load_context()
        return storage.list_playbooks()

    def get_playbook(self, playbook_id: str) -> Playbook | None:
        """Return a single playbook by id."""
        _, _, storage = self._load_context()
        return storage.get_playbook(playbook_id)

    @staticmethod
    def _write_playbook_artifacts(
        *,
        repo_root: Path,
        config: ProjectConfig,
        playbooks: list[Playbook],
    ) -> list[str]:
        """Write playbook artifacts to .onmc/compiled/ and .agent-memory/playbooks/."""
        import json as _json

        written: list[str] = []

        # .onmc/compiled/ — human-readable markdown for review.
        compiled = compiled_dir(config, repo_root)
        compiled.mkdir(parents=True, exist_ok=True)
        timestamp = utc_now().strftime("%Y%m%d-%H%M%S")
        md_path = compiled / f"{timestamp}-playbooks.md"
        lines = ["# Generated Playbooks", ""]
        for pb in playbooks:
            lines.extend(
                [
                    f"## {pb.title}",
                    "",
                    f"**ID:** `{pb.id}`  ",
                    f"**Confidence:** {pb.confidence:.2f}  ",
                    f"**When to use:** {pb.trigger}",
                    "",
                    "### Steps",
                    "",
                    *[f"{i}. {step}" for i, step in enumerate(pb.steps, 1)],
                    "",
                    "### Grounded In",
                    "",
                    *[
                        f"- [{item.kind}] `{item.memory_id[:16]}`  {item.title}"
                        for item in pb.grounded_in
                    ],
                    "",
                ]
            )
        md_path.write_text("\n".join(lines), encoding="utf-8")
        written.append(md_path.as_posix())

        # .agent-memory/playbooks/ — JSON for git portability.
        playbooks_dir = repo_root / ".agent-memory" / "playbooks"
        playbooks_dir.mkdir(parents=True, exist_ok=True)
        for pb in playbooks:
            target = playbooks_dir / f"{pb.id}.json"
            target.write_text(
                _json.dumps(pb.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            written.append(target.as_posix())

        return written

    # ── Skill management ──────────────────────────────────────────────────────

    # Feedback delta constants for skills (mirrors memory feedback constants).
    _SKILL_FEEDBACK_UP_CONFIDENCE: float = 0.05
    _SKILL_FEEDBACK_DOWN_CONFIDENCE: float = 0.05
    _SKILL_CONFIDENCE_FLOOR: float = 0.10

    def skill_promote(
        self,
        playbook_id: str | None = None,
        *,
        auto: bool = False,
        name: str | None = None,
    ) -> list[object]:
        """Promote a playbook or recurring patterns to skill(s).

        When *playbook_id* is given, promotes that single playbook to a Skill
        (raises LookupError when not found, ValueError when already promoted).

        When *auto=True*, detects recurring fail→fix patterns + high-signal tag
        clusters across all stored memories and returns new Skills (skipping
        memories already captured by existing skills).

        Returns a list of newly created Skill objects.
        """
        from oh_no_my_claudecode.skill.promoter import (
            auto_promote_recurring,
            promote_playbook_to_skill,
        )

        _, _, storage = self._load_context()

        if auto:
            import contextlib

            skills = auto_promote_recurring(storage)
            for sk in skills:
                with contextlib.suppress(ValueError):
                    storage.add_skill(sk)
            return list(skills)

        if playbook_id is None:
            msg = "Provide a playbook_id or pass auto=True."
            raise ValueError(msg)

        playbook = storage.get_playbook(playbook_id)
        if playbook is None:
            msg = f"Playbook not found: {playbook_id}"
            raise LookupError(msg)

        skill = promote_playbook_to_skill(playbook, name=name)
        storage.add_skill(skill)
        return [skill]

    def skill_list(self) -> list[object]:
        """Return all persisted skills ordered by confidence."""
        _, _, storage = self._load_context()
        return storage.list_skills()  # type: ignore[return-value]

    def skill_show(self, skill_id: str) -> object:
        """Return a single skill by id (or unique prefix); raises LookupError."""
        _, _, storage = self._load_context()
        all_skills = storage.list_skills()
        matches = [sk for sk in all_skills if sk.id.startswith(skill_id)]
        if not matches:
            msg = f"Skill not found: {skill_id}"
            raise LookupError(msg)
        if len(matches) > 1:
            ids = ", ".join(sk.id for sk in matches)
            msg = f"Ambiguous skill prefix '{skill_id}' matches: {ids}"
            raise LookupError(msg)
        return matches[0]

    def skill_feedback(self, skill_id: str, direction: str) -> object:
        """Apply a trust signal to a skill's confidence and success metrics.

        ``direction`` must be ``"up"`` or ``"down"``.

        ``up``   bumps success_count + use_count and nudges confidence up.
        ``down`` bumps use_count only and nudges confidence down
                 (clamped at _SKILL_CONFIDENCE_FLOOR so the skill stays visible).

        Returns the updated Skill.
        """
        if direction not in ("up", "down"):
            msg = f"direction must be 'up' or 'down', got {direction!r}"
            raise ValueError(msg)
        from oh_no_my_claudecode.models.skill import Skill as _Skill

        _, _, storage = self._load_context()
        skill_obj = self.skill_show(skill_id)
        if not isinstance(skill_obj, _Skill):
            msg = f"Skill not found: {skill_id}"
            raise LookupError(msg)
        skill = skill_obj
        success = direction == "up"
        updated = storage.record_skill_use(skill.id, success=success)
        # Also adjust confidence.
        if direction == "up":
            new_conf = min(1.0, updated.confidence + self._SKILL_FEEDBACK_UP_CONFIDENCE)
        else:
            new_conf = max(
                self._SKILL_CONFIDENCE_FLOOR,
                updated.confidence - self._SKILL_FEEDBACK_DOWN_CONFIDENCE,
            )
        final = updated.model_copy(update={"confidence": new_conf})
        storage.update_skill(final)
        return final

    def skill_prune(self) -> list[object]:
        """Disable auto_inject on skills with low success rate and long disuse.

        A skill is pruned when ALL of the following hold:
        - use_count >= 3  (enough signal to judge)
        - success_rate < 0.3  (failing more than it helps)
        - OR last_used_at is older than 60 days

        Pruning sets auto_inject=False and nudges confidence down to the floor.
        Returns the list of Skills that were pruned.
        """
        from oh_no_my_claudecode.utils.time import utc_now as _utc_now

        _, _, storage = self._load_context()
        skills = storage.list_skills()
        now = _utc_now()
        pruned: list[object] = []

        for sk in skills:
            should_prune = False
            if sk.use_count >= 3 and sk.success_rate < 0.3:
                should_prune = True
            if sk.last_used_at is not None:
                from datetime import UTC

                last = sk.last_used_at
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                now_aware = now if now.tzinfo else now.replace(tzinfo=UTC)
                days_since = (now_aware - last).total_seconds() / 86_400
                if days_since > 60:
                    should_prune = True
            if should_prune and sk.auto_inject:
                updated = sk.model_copy(
                    update={
                        "auto_inject": False,
                        "confidence": max(self._SKILL_CONFIDENCE_FLOOR, sk.confidence - 0.1),
                    }
                )
                storage.update_skill(updated)
                pruned.append(updated)

        return pruned

    def skill_export(
        self,
        *,
        out_dir: Path | None = None,
        scope: str = "project",
    ) -> list[Path]:
        """Export all persisted skills as Agent Skills SKILL.md files.

        Writes one ``<out_dir>/<slug>/SKILL.md`` per skill.  The output is
        compatible with the agentskills.io open standard, understood by 16+
        tools: Claude Code, Cursor, Codex, Gemini, Copilot, OpenCode, Goose,
        Letta, Hermes, and more.

        Parameters
        ----------
        out_dir:
            Destination directory.  Defaults to ``<repo_root>/.claude/skills/``
            (project scope) or ``~/.claude/skills/`` (personal scope).
        scope:
            ``"project"`` (default) writes to the current repo's
            ``.claude/skills/``; ``"personal"`` writes to ``~/.claude/skills/``.
            Ignored when *out_dir* is supplied explicitly.

        Returns
        -------
        list[Path]
            Paths of SKILL.md files actually written (empty when the store has
            no skills or when all files were already up to date).
        """
        from oh_no_my_claudecode.skill.export import export_skills as _export_skills

        repo_root, _, storage = self._load_context()
        skills = storage.list_skills()
        if not skills:
            return []

        if out_dir is not None:
            resolved_dir = out_dir
        elif scope == "personal":
            resolved_dir = Path.home() / ".claude" / "skills"
        else:
            resolved_dir = repo_root / ".claude" / "skills"

        return _export_skills(skills, resolved_dir)

    # ── Import from external tool formats ─────────────────────────────────────

    def import_from(
        self,
        source: str,
        path: Path | None = None,
        *,
        dry_run: bool = False,
        as_kind: str = "skill",
    ) -> ImportResult:
        """Import skills or memories from an external tool format.

        Parameters
        ----------
        source:
            ``"omc"`` (oh-my-claudecode skills), ``"hermes"`` (Nous hermes-agent
            context files), or a filesystem path to a ``.md`` file / directory.
        path:
            Optional explicit path override (for ``omc`` / ``hermes`` sources).
        dry_run:
            Parse and report without writing anything to the store.
        as_kind:
            ``"skill"`` or ``"memory"`` — controls how generic markdown paths are
            imported.  Ignored for ``omc`` (always ``"skill"``) and ``hermes``
            (always ``"memory"``).

        Returns
        -------
        ImportResult
            Summary: source, as_kind, imported, skipped, dry_run, items.
        """
        from oh_no_my_claudecode.importers import ImportResult as _ImportResult
        from oh_no_my_claudecode.importers import run_import

        _, _, storage = self._load_context()
        result: _ImportResult = run_import(
            storage,
            source,
            path,
            dry_run=dry_run,
            as_kind=as_kind,
            cwd=self.cwd,
        )
        return result

    # ── User-scope (cross-repo) memory ────────────────────────────────────────

    def add_user_memory(
        self,
        *,
        title: str,
        summary: str,
        home: Path | None = None,
    ) -> MemoryEntry:
        """Add a durable user-scope preference to ``~/.onmc/user.db``.

        User memories are not repo-scoped — they travel with the developer
        across all repositories and appear in every boot digest.  They use
        the ``MANUAL`` source type so they are protected from automated
        replacement.
        """
        storage = self._user_storage(home=home)
        now = utc_now()
        entry = MemoryEntry(
            id=stable_id("user", title, summary, "user:manual", prefix="user"),
            kind=MemoryKind.DECISION,
            title=title,
            summary=summary,
            details=summary,
            source_type=SourceType.MANUAL,
            source_ref="user:manual",
            tags=["user-pref"],
            confidence=0.9,
            created_at=now,
            updated_at=now,
        )
        storage.upsert_memories([entry])
        return storage.get_memory(entry.id) or entry

    def list_user_memories(self, *, home: Path | None = None) -> list[MemoryEntry]:
        """Return all user-scope preferences from ``~/.onmc/user.db``."""
        storage = self._user_storage(home=home)
        return storage.list_memories()

    def get_user_memory(self, memory_id: str, *, home: Path | None = None) -> MemoryEntry | None:
        """Return a single user-scope memory by id."""
        storage = self._user_storage(home=home)
        return storage.get_memory(memory_id)

    def remove_user_memory(self, memory_id: str, *, home: Path | None = None) -> bool:
        """Delete a user-scope memory by id.  Returns ``True`` if a row was deleted."""
        storage = self._user_storage(home=home)
        with storage._connection() as conn:  # noqa: SLF001
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cursor.rowcount > 0

    @staticmethod
    def _user_storage(*, home: Path | None = None) -> SQLiteStorage:
        """Return an initialised SQLiteStorage pointing at ``~/.onmc/user.db``."""
        db_path = user_database_path(home)
        storage = SQLiteStorage(db_path)
        storage.initialize()
        return storage

    def _load_user_memories(self, *, home: Path | None = None) -> list[MemoryEntry]:
        """Load user-scope memories; return an empty list on any error."""
        try:
            return self._user_storage(home=home).list_memories()
        except Exception:
            return []

    def user_profile(
        self,
        *,
        home: Path | None = None,
        max_items: int = 5,
    ) -> UserProfile:
        """Derive a behavioral profile from accumulated user-scope memories.

        Reads ``~/.onmc/user.db``, weights each memory by confidence × feedback ×
        recency-decay, and buckets entries into preferences, patterns,
        frequent_mistakes, and tooling.  Entirely offline — no LLM calls.

        Returns an empty ``UserProfile`` when the user store is empty or missing.
        """
        from oh_no_my_claudecode.profile.compiler import compile_user_profile

        memories = self._load_user_memories(home=home)
        return compile_user_profile(memories, max_items=max_items)

    def guard(self, task: str, *, limit: int = 8) -> tuple[Path, GuardResult]:
        """Surface recorded dead-ends relevant to *task*.

        Returns ``(repo_root, GuardResult)`` where ``GuardResult.entries``
        contains ranked ``GuardEntry`` items from ``FAILED_APPROACH`` memories
        and ``did_not_work`` artifacts.  An empty result is valid and means no
        relevant dead-ends have been recorded for this task.
        """
        from oh_no_my_claudecode.guard.compiler import compile_guard

        repo_root, _, storage = self._load_context()
        result = compile_guard(storage, task, limit=limit)
        return repo_root, result

    def recall(self, query: str, *, limit: int = 8) -> tuple[Path, RecallResult]:
        """Match *query* (error text / stacktrace) against past incidents in memory.

        Returns ``(repo_root, RecallResult)`` where ``RecallResult.entries``
        contains ranked ``RecallEntry`` items from memories biased toward
        ``FAILED_APPROACH`` and ``GOTCHA`` kinds.  An empty result is valid and
        means no relevant incidents have been recorded — the ``no_data_hint``
        field explains how to populate the brain.
        """
        from oh_no_my_claudecode.recall.compiler import compile_recall

        repo_root, _, storage = self._load_context()
        result = compile_recall(storage, query, limit=limit)
        return repo_root, result

    def reuse_find(self, query: str, *, limit: int = 8) -> tuple[Path, list[ReuseHit]]:
        """Surface existing code that already does what *query* describes.

        Indexes the repo via stdlib ``ast`` and ranks top-level functions and
        classes by token overlap against *query* (name, docstring, arg names).
        Entirely offline and deterministic — no LLM calls, no network — so an
        agent can check "does this already exist?" before reimplementing it.

        Returns ``(repo_root, hits)`` where *hits* is a ranked list of
        ``ReuseHit`` (may be empty when nothing relevant is found).
        """
        from oh_no_my_claudecode.reuse.radar import find_reuse

        repo_root = discover_repo_root(self.cwd)
        hits = find_reuse(repo_root, query, limit=limit)
        return repo_root, hits

    def ask(
        self,
        question: str,
        *,
        limit: int = 8,
        synthesize: bool = True,
    ) -> tuple[Path, AskResult]:
        """Answer *question* by querying the memory brain.

        Always returns ranked, cited memory entries (offline-safe).  When a
        provider is configured and *synthesize* is True, also returns a concise
        LLM-synthesized answer.  Provider failures never raise — the result
        always contains ranked entries.

        Args:
            question: Natural-language question to answer from memory.
            limit: Maximum number of ranked entries to return.
            synthesize: When True (default) and a provider is configured, run
                the LLM synthesis pass.  Pass False to force offline-only mode
                regardless of provider configuration.

        Returns:
            ``(repo_root, AskResult)`` where ``AskResult.entries`` is always
            populated (may be empty when the store has no relevant memories).
        """
        from oh_no_my_claudecode.ask.compiler import compile_ask

        repo_root, config, storage = self._load_context()
        provider = self._optional_provider(config=config, no_llm=not synthesize)
        result = compile_ask(storage, repo_root, question, limit=limit, provider=provider)
        return repo_root, result

    def consolidate(self, *, dry_run: bool = False) -> tuple[Path, ConsolidationResult]:
        """Run the memory consolidation pass (dedup, merge, promote, demote, graph).

        When *dry_run* is True the function computes the full plan but writes
        nothing — no memory updates and no edge upserts — so the result can be
        inspected without side effects.

        Returns ``(repo_root, ConsolidationResult)`` with action counts.
        """
        repo_root, _, storage = self._load_context()
        memories = storage.list_memories()
        existing_edges = storage.list_memory_edges()
        existing_edge_ids = {edge.id for edge in existing_edges}
        changed_memories, new_edges, result = consolidate_memories(
            memories,
            repo_root,
            existing_edge_ids=existing_edge_ids,
        )
        if not dry_run:
            for memory in changed_memories:
                storage.update_memory(memory)
            for edge in new_edges:
                storage.upsert_memory_edge(edge)
        return repo_root, result

    def audit(self, *, repo_root: Path | None = None) -> AuditReport:
        """Run the agent-configuration security scanner against the repo.

        This is entirely offline — no LLM calls, no network access.  Results
        are deterministic: given the same repo configuration files they always
        produce the same findings.

        Parameters
        ----------
        repo_root:
            Explicit repo root to scan.  When ``None``, discovered from
            ``self.cwd``.  This lets callers scan a path that has not been
            initialised with ``onmc init``.

        Returns
        -------
        AuditReport
            Scored, graded report ready for rendering or JSON serialisation.
        """
        from oh_no_my_claudecode.audit.scanner import AuditReport as _AuditReport
        from oh_no_my_claudecode.audit.scanner import run_audit

        if repo_root is None:
            try:
                repo_root = discover_repo_root(self.cwd)
            except FileNotFoundError:
                repo_root = self.cwd
        result: _AuditReport = run_audit(repo_root)
        return result

    def verify_diff(
        self,
        *,
        base: str = "main",
        expect_symbols: tuple[str, ...] = (),
        expect_files: tuple[str, ...] = (),
        repo_root: Path | None = None,
    ) -> VerifyReport:
        """Adversarially verify the working diff against *base*.

        Shells ``git diff <base>...HEAD`` for the repo and runs the pure,
        deterministic :func:`~oh_no_my_claudecode.verifydiff.checker.verify_diff`
        over the result.  No LLM calls.  Passes only when the change is real
        (non-empty), introduces every expected symbol/file, and is lawful (no
        banned/secret patterns in added lines).

        Parameters
        ----------
        base:
            Git ref to diff against (default ``main``).
        expect_symbols:
            Symbols that must each appear in at least one added line.
        expect_files:
            Repo-relative paths that must each receive added lines.
        repo_root:
            Explicit repo root.  When ``None``, discovered from ``self.cwd``.

        Returns
        -------
        VerifyReport
            ``ok`` is ``True`` only when every check passed.
        """
        from oh_no_my_claudecode.verifydiff.checker import collect_diff, verify_diff

        if repo_root is None:
            try:
                repo_root = discover_repo_root(self.cwd)
            except FileNotFoundError:
                repo_root = self.cwd
        diff_text = collect_diff(repo_root, base)
        return verify_diff(
            diff_text=diff_text,
            expect_symbols=expect_symbols,
            expect_files=expect_files,
        )

    # ------------------------------------------------------------------
    # Preflight (local CI gate)
    # ------------------------------------------------------------------

    def preflight(
        self,
        *,
        steps: Sequence[str] | None = None,
        repo_root: Path | None = None,
        executor: PreflightExecutor | None = None,
        provision: bool = False,
    ) -> PreflightReport:
        """Run the exact CI quality gate locally and return the report.

        Mirrors ``.github/workflows/ci.yml`` step-for-step (ruff, mypy,
        cli-reference ``--check``, pytest) so an agent can validate a change
        the same way CI will before pushing.

        Parameters
        ----------
        steps:
            Subset of step ids to run (``ruff``/``mypy``/``cliref``/``pytest``).
            ``None`` runs all of them in CI order.
        repo_root:
            Directory the commands run in.  Discovered from ``self.cwd`` when
            ``None`` (falling back to ``self.cwd`` outside a repo).
        executor:
            Injectable ``(cmd) -> (returncode, output)`` callable.  Defaults to
            a subprocess runner; tests inject a fake for deterministic runs.
        provision:
            When ``True`` each tool runs via ``uv run --with <tool>`` so a
            fresh worktree resolves the toolchain on demand (and the
            cli-reference step pins ``typer<1.0`` to match CI).  Passed through
            to :func:`run_preflight`.

        Returns
        -------
        PreflightReport
            One step result per executed step, plus an aggregate ``ok``.
        """
        from oh_no_my_claudecode.preflight import run_preflight

        if repo_root is None:
            try:
                repo_root = discover_repo_root(self.cwd)
            except (FileNotFoundError, RepoDiscoveryError):
                repo_root = self.cwd
        return run_preflight(
            repo_root, steps=steps, executor=executor, provision=provision
        )

    def fleet_status(self, *, swarm_id: str | None = None) -> FleetStatus:
        """Summarise local swarm/claim/receipt state."""
        from oh_no_my_claudecode.fleet import fleet_status

        try:
            repo_root = discover_repo_root(self.cwd)
        except (FileNotFoundError, RepoDiscoveryError):
            repo_root = self.cwd
        return fleet_status(repo_root, swarm_id=swarm_id)

    def fleet_doctor(self) -> FleetDoctorReport:
        """Diagnose stuck fleet state from local ledgers."""
        from oh_no_my_claudecode.fleet import fleet_doctor

        try:
            repo_root = discover_repo_root(self.cwd)
        except (FileNotFoundError, RepoDiscoveryError):
            repo_root = self.cwd
        return fleet_doctor(repo_root)

    # ------------------------------------------------------------------
    # MCP Trust Gateway
    # ------------------------------------------------------------------

    def mcp_policy_init(self, *, force: bool = False, repo_root: Path | None = None) -> Path:
        """Write a starter ``.onmc/mcp-policy.yaml`` for the MCP trust gateway.

        Parameters
        ----------
        force:
            Overwrite an existing policy file.
        repo_root:
            Explicit repo root.  When ``None``, discovered from ``self.cwd``.

        Returns
        -------
        Path
            Absolute path to the (written or existing) policy file.
        """
        from oh_no_my_claudecode.mcp_trust.policy import init_policy

        if repo_root is None:
            try:
                repo_root = discover_repo_root(self.cwd)
            except FileNotFoundError:
                repo_root = self.cwd
        return init_policy(repo_root, force=force)

    def mcp_check(
        self,
        calls_jsonl: str,
        *,
        repo_root: Path | None = None,
        write_audit_log: bool = True,
    ) -> list[tuple[McpToolCall, McpDecision]]:
        """Classify MCP tool calls recorded in a JSONL source string.

        Parameters
        ----------
        calls_jsonl:
            Raw JSONL string (one JSON object per line).  Each line must have
            ``server`` and ``tool`` keys; an optional ``args`` dict is scanned
            for secrets and injection phrases.
        repo_root:
            Explicit repo root for locating the policy file and the audit log.
            Defaults to the service's ``cwd``.
        write_audit_log:
            When ``True`` (default), append each decision to
            ``.onmc/mcp-audit.log``.

        Returns
        -------
        list[tuple[ToolCall, Decision]]
            One entry per parsed call.
        """
        from oh_no_my_claudecode.mcp_trust.gateway import (
            append_audit_log,
            classify_call,
            parse_calls_jsonl,
        )
        from oh_no_my_claudecode.mcp_trust.policy import load_policy

        if repo_root is None:
            try:
                repo_root = discover_repo_root(self.cwd)
            except FileNotFoundError:
                repo_root = self.cwd

        policy = load_policy(repo_root)
        calls = parse_calls_jsonl(calls_jsonl)
        results: list[tuple[McpToolCall, McpDecision]] = []
        for call in calls:
            decision = classify_call(policy, call)
            if write_audit_log:
                append_audit_log(repo_root, call, decision)
            results.append((call, decision))
        return results

    # ------------------------------------------------------------------
    # Conventions — capture + inherit repo coding conventions
    # ------------------------------------------------------------------

    def conventions_capture(
        self,
        *,
        force: bool = False,
        repo_root: Path | None = None,
    ) -> tuple[Conventions, Path]:
        """Detect repo conventions and write ``.onmc/conventions.md``.

        Parameters
        ----------
        force:
            Overwrite an existing ``conventions.md``.  Without ``force`` the file
            is left untouched when it already exists (idempotent no-op write).
        repo_root:
            Explicit repo root.  When ``None``, discovered from ``self.cwd`` and
            falling back to ``self.cwd`` when no git repo is found.

        Returns
        -------
        tuple[Conventions, Path]
            The detected conventions and the absolute path to the (written or
            existing) ``conventions.md`` file.
        """
        if repo_root is None:
            try:
                repo_root = discover_repo_root(self.cwd)
            except (FileNotFoundError, RepoDiscoveryError):
                repo_root = self.cwd

        conv = detect_conventions(repo_root)
        target = conventions_path(repo_root)
        if target.exists() and not force:
            return conv, target

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_conventions_markdown(conv), encoding="utf-8")
        return conv, target

    def conventions_show(
        self,
        *,
        repo_root: Path | None = None,
    ) -> Conventions:
        """Detect and return the repo's conventions without writing anything.

        Parameters
        ----------
        repo_root:
            Explicit repo root.  When ``None``, discovered from ``self.cwd`` and
            falling back to ``self.cwd`` when no git repo is found.
        """
        if repo_root is None:
            try:
                repo_root = discover_repo_root(self.cwd)
            except (FileNotFoundError, RepoDiscoveryError):
                repo_root = self.cwd
        return detect_conventions(repo_root)

    # ------------------------------------------------------------------
    # Release drafter (deterministic, offline)
    # ------------------------------------------------------------------

    def release_draft(
        self,
        *,
        write: bool = False,
        repo_root: Path | None = None,
        use_git_cliff: bool = True,
    ) -> tuple[Path, ReleaseDraft]:
        """Draft the next release from conventional-commit history.

        Reads the current version from ``pyproject.toml`` and the commit
        subjects since the last ``vX.Y.Z`` tag, classifies them into a semver
        bump, and renders a CHANGELOG entry.  Deterministic given the repo's
        git history; no network or LLM access.

        Parameters
        ----------
        write:
            When ``True``, edit ``pyproject.toml`` (bump version) and prepend
            the rendered entry to ``CHANGELOG.md``.  When ``False`` (default),
            nothing is written — the draft is returned for preview.
        repo_root:
            Explicit repo root.  When ``None``, discovered from ``self.cwd``.
        use_git_cliff:
            When ``True`` (default) and the external ``git-cliff`` binary is on
            ``PATH``, git-cliff renders the CHANGELOG entry.  When the binary is
            absent — or this is ``False`` — the built-in conventional-commit
            renderer is used instead (identical to prior behaviour).  Version
            bump and commit grouping are unaffected either way.

        Returns
        -------
        tuple[Path, ReleaseDraft]
            ``(repo_root, draft)``.
        """
        from oh_no_my_claudecode.release import (
            collect_commits,
            current_version,
            default_cliff_runner,
            draft_release,
            write_release,
        )

        if repo_root is None:
            repo_root = discover_repo_root(self.cwd)

        cliff_runner = default_cliff_runner() if use_git_cliff else None

        version = current_version(repo_root)
        commits = collect_commits(repo_root)
        draft = draft_release(
            current_version=version,
            commits=commits,
            date=utc_now().strftime("%Y-%m-%d"),
            cliff_runner=cliff_runner,
            repo_root=repo_root,
        )
        if write:
            write_release(repo_root, draft)
        return repo_root, draft

    # ------------------------------------------------------------------
    # Eval harness
    # ------------------------------------------------------------------

    def eval_create(
        self,
        *,
        from_memory_id: str | None = None,
        case_id: str | None = None,
        query: str | None = None,
        expected_files: list[str] | None = None,
        expected_deadend_substrings: list[str] | None = None,
        note: str = "",
    ) -> tuple[Path, EvalCase]:
        """Create and persist an eval case.

        Two creation modes:

        **Derive from memory** (``from_memory_id`` given):
            Calls :func:`~oh_no_my_claudecode.evals.store.create_eval_case_from_task`
            to derive query and expectations from an existing memory entry.
            Raises ``ValueError`` when the memory is not found.

        **Manual** (``query`` given, ``from_memory_id`` omitted):
            Creates a case from explicit parameters.  ``case_id`` defaults to
            a hash of the query when omitted.

        Returns
        -------
        tuple[Path, EvalCase]
            ``(repo_root, case)``
        """
        from oh_no_my_claudecode.evals.models import EvalCase
        from oh_no_my_claudecode.evals.store import (
            create_eval_case_from_task,
            save_eval_case,
        )
        from oh_no_my_claudecode.utils.text import stable_id

        repo_root, _, storage = self._load_context()

        if from_memory_id is not None:
            case = create_eval_case_from_task(storage, from_memory_id)
            if case is None:
                msg = f"No memory found with id: {from_memory_id}"
                raise ValueError(msg)
        else:
            if not query:
                msg = "Either --from-memory or --query must be provided."
                raise ValueError(msg)
            derived_id = case_id or ("eval-" + stable_id("eval", query, "", "", prefix="ev")[:20])
            case = EvalCase(
                id=derived_id,
                query=query,
                expected_files=expected_files or [],
                expected_deadend_substrings=expected_deadend_substrings or [],
                note=note,
            )

        save_eval_case(repo_root, case)
        return repo_root, case

    def eval_run(
        self,
        *,
        with_memory: bool = True,
        recall_limit: int = 8,
    ) -> tuple[Path, EvalReport]:
        """Run the eval suite and return an :class:`~oh_no_my_claudecode.evals.models.EvalReport`.

        Loads all cases from ``.onmc/evals/``.  Deterministic and offline.

        Parameters
        ----------
        with_memory:
            When True (default), evaluate against live storage.
            When False, simulate the cold (no-memory) baseline.
        recall_limit:
            Max entries to request from compile_recall per case.

        Returns
        -------
        tuple[Path, EvalReport]
            ``(repo_root, report)``
        """
        from oh_no_my_claudecode.evals.harness import run_evals
        from oh_no_my_claudecode.evals.store import load_all_eval_cases

        repo_root, _, storage = self._load_context()
        cases = load_all_eval_cases(repo_root)
        report = run_evals(storage, cases, with_memory=with_memory, recall_limit=recall_limit)
        return repo_root, report

    def eval_compare(
        self,
        *,
        recall_limit: int = 8,
    ) -> tuple[Path, EvalComparison]:
        """Run both conditions and return an :class:`EvalComparison`.

        Runs ``eval_run`` twice (with and without memory) and returns the
        side-by-side comparison.  Deterministic and offline.

        Returns
        -------
        tuple[Path, EvalComparison]
            ``(repo_root, comparison)``
        """
        from oh_no_my_claudecode.evals.harness import compare_evals
        from oh_no_my_claudecode.evals.store import load_all_eval_cases

        repo_root, _, storage = self._load_context()
        cases = load_all_eval_cases(repo_root)
        comparison = compare_evals(storage, cases, recall_limit=recall_limit)
        return repo_root, comparison

    def _load_context(self) -> tuple[Path, ProjectConfig, SQLiteStorage]:
        try:
            repo_root = discover_repo_root(self.cwd)
        except RepoDiscoveryError:
            msg = (
                "✗ Not inside a git repository. "
                "cd into your project (or [bold]git init[/bold]) "
                "and run [bold]onmc setup[/bold]."
            )
            raise FileNotFoundError(msg) from None
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

    # -----------------------------------------------------------------------
    # Notify / context firewall
    # -----------------------------------------------------------------------

    def notify_status(self) -> dict[str, object]:
        """Return the active notify configuration for the current repo.

        The dict includes ``enabled``, ``sink``, ``log_path`` (absolute),
        ``discord_webhook`` (masked), ``slack_webhook`` (masked), and a
        ``log_exists`` bool so callers can show whether the log has entries.
        """
        try:
            repo_root = discover_repo_root(self.cwd)
        except Exception:  # noqa: BLE001
            repo_root = self.cwd

        from oh_no_my_claudecode.notify.router import (  # noqa: PLC2701
            NotifyRouter,
            _resolve_notify_config,
        )

        cfg = _resolve_notify_config(repo_root)
        router = NotifyRouter(repo_root, config=cfg)
        log_path = router.file_sink.log_path

        def _mask(url: object) -> str | None:
            s = str(url) if url else ""
            if not s:
                return None
            return s[:12] + "…" if len(s) > 12 else s

        return {
            "enabled": cfg.get("enabled", True),
            "sink": cfg.get("sink", "file"),
            "log_path": str(log_path),
            "log_exists": log_path.exists(),
            "discord_webhook": _mask(cfg.get("discord_webhook")),
            "slack_webhook": _mask(cfg.get("slack_webhook")),
        }

    def notify_test(self, message: str = "test notification from onmc") -> str:
        """Emit a test ``NotifyEvent`` and return a human-readable summary.

        Returns a sentence describing where the event was routed.
        """
        try:
            repo_root = discover_repo_root(self.cwd)
        except Exception:  # noqa: BLE001
            repo_root = self.cwd

        from oh_no_my_claudecode.notify.events import EventKind, EventSeverity, NotifyEvent
        from oh_no_my_claudecode.notify.router import (  # noqa: PLC2701
            NotifyRouter,
            _resolve_notify_config,
        )

        cfg = _resolve_notify_config(repo_root)
        router = NotifyRouter(repo_root, config=cfg)

        event = NotifyEvent(
            kind=EventKind.GENERIC,
            title=message,
            severity=EventSeverity.ROUTINE,
            detail="Emitted by `onmc notify test` to verify the context firewall sink.",
        )
        router.emit(event)

        sink_type = str(cfg.get("sink", "file"))
        if not bool(cfg.get("enabled", True)) or sink_type == "none":
            return "notify disabled — event dropped."
        if sink_type == "file":
            return f"event written to {router.file_sink.log_path}"
        return f"event written to {router.file_sink.log_path} and dispatched to {sink_type} webhook"

    def notify_tail(self, n: int = 20) -> list[dict[str, object]]:
        """Return the last *n* events from the JSONL notify log.

        Returns an empty list when the log does not exist or is unreadable.
        """
        import json

        try:
            repo_root = discover_repo_root(self.cwd)
        except Exception:  # noqa: BLE001
            repo_root = self.cwd

        from oh_no_my_claudecode.notify.sinks import FileSink

        log_path = FileSink(repo_root).log_path
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
            tail_lines = lines[-n:] if n < len(lines) else lines
            events: list[dict[str, object]] = []
            for line in tail_lines:
                line = line.strip()
                if not line:
                    continue
                with contextlib.suppress(Exception):
                    events.append(json.loads(line))
            return events
        except Exception:  # noqa: BLE001
            return []


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
            assumptions=["The proposed change respects the repo invariants surfaced in the brief."],
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


def _append_report_memory_and_tasks(lines: list[str], summary: AgentReadinessSummary) -> None:
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


def _append_report_agent_integration(lines: list[str], summary: AgentReadinessSummary) -> None:
    lines.extend(
        [
            "## Agent Integration",
            "",
            f"- CLAUDE.md: {'present' if summary.claude_md_exists else 'missing'}",
            (f"- Claude hooks: {'installed' if summary.hooks.installed else 'not installed'}"),
            (f"- MCP server: {'registered' if summary.hooks.mcp_registered else 'not registered'}"),
            f"- Portable export: {'present' if summary.manifest_exists else 'missing'}",
            (f"- Sync hook: {'installed' if summary.sync_hook_installed else 'not installed'}"),
            f"- LLM provider: {summary.provider_label}",
            "",
        ]
    )


def _append_report_health_sections(lines: list[str], summary: AgentReadinessSummary) -> None:
    lines.extend(["## Health Signals", ""])
    for section in summary.health_sections:
        items = summary.health.get(section, [])
        if not items:
            continue
        lines.extend([f"### {section.title()}", ""])
        lines.extend(f"- {item}" for item in items)
        lines.append("")


def _append_report_recommendations(lines: list[str], summary: AgentReadinessSummary) -> None:
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


def _append_report_share_snippet(lines: list[str], summary: AgentReadinessSummary) -> None:
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


_ONMC_PATH_PROBE_TIMEOUT = 5  # seconds


def _installed_onmc_version() -> str | None:
    """Return the importlib.metadata version for oh-no-my-claudecode, or None."""
    try:
        return pkg_version("oh-no-my-claudecode")
    except PackageNotFoundError:
        return None


def _probe_path_onmc() -> tuple[str | None, str | None]:
    """Return (path_binary, version_string) for the `onmc` binary on PATH.

    Returns (None, None) if the binary is not found or fails to report a version.
    The probe uses a short hard timeout so it never hangs doctor.
    """
    binary = shutil.which("onmc")
    if binary is None:
        return None, None
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=_ONMC_PATH_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return binary, None
    output = (result.stdout + result.stderr).strip()
    # Extract trailing semver token, e.g. "onmc 0.10.0" or just "0.10.0"
    match = re.search(r"(\d+\.\d+\.\d+(?:\.\w+)*)", output)
    if match:
        return binary, match.group(1)
    # Binary ran but produced no parseable version — treat as broken
    return binary, None


def _check_onmc_path_health() -> list[tuple[str, str]]:
    """Return a list of (severity, message) tuples describing PATH onmc health.

    Severity is one of "ok", "warn", or "error".  Doctor aggregates these into
    the appropriate report buckets without needing to understand what they mean.
    """
    installed_ver = _installed_onmc_version()
    binary, path_ver = _probe_path_onmc()

    results: list[tuple[str, str]] = []

    if binary is None:
        results.append(
            (
                "warn",
                "onmc not found on PATH — hooks will fail. "
                "Add the virtualenv bin/ to PATH or reinstall (`pip install oh-no-my-claudecode`).",
            )
        )
        return results

    if path_ver is None:
        results.append(
            (
                "warn",
                f"onmc found at {binary} but failed to report a version "
                f"(binary may be broken). "
                "Reinstall via `pip install --upgrade oh-no-my-claudecode`.",
            )
        )
        return results

    if installed_ver and path_ver != installed_ver:
        results.append(
            (
                "warn",
                f"PATH onmc version ({path_ver} at {binary}) differs from installed "
                f"package version ({installed_ver}) — stale shadow binary detected. "
                "Run `pip install --upgrade oh-no-my-claudecode` or fix your PATH.",
            )
        )
    else:
        results.append(("ok", f"onmc {path_ver} on PATH ({binary})"))

    return results


def _read_mcp_command(mcp_path: Path) -> str | None:
    """Return the ``command`` field of the onmc MCP server entry in .mcp.json, or None."""
    if not mcp_path.exists():
        return None
    try:
        payload = json.loads(mcp_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict):
        return None
    onmc_entry = servers.get("onmc")
    if not isinstance(onmc_entry, dict):
        return None
    cmd = onmc_entry.get("command")
    return cmd if isinstance(cmd, str) else None


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
