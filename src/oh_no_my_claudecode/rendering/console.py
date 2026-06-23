from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from oh_no_my_claudecode.audit.scanner import AuditReport
    from oh_no_my_claudecode.federation.pull import PullResult
    from oh_no_my_claudecode.loop.models import LoopResult
    from oh_no_my_claudecode.profile.compiler import UserProfile
    from oh_no_my_claudecode.trace.models import TraceReport

from oh_no_my_claudecode.ask.compiler import AskResult
from oh_no_my_claudecode.blame.compiler import BlameResult
from oh_no_my_claudecode.coverage.compiler import CoverageReport, CoverageSuggestion
from oh_no_my_claudecode.importers.base import ImportResult
from oh_no_my_claudecode.integrations.gh_aw import GhAwInitResult
from oh_no_my_claudecode.models import (
    AttemptRecord,
    AttemptStatus,
    BriefArtifact,
    HookStatus,
    IngestResult,
    LLMSettings,
    LLMStatus,
    MemoryArtifactRecord,
    MemoryArtifactType,
    MemoryEntry,
    Playbook,
    ProjectConfig,
    ReviewModeOutput,
    Skill,
    SolveModeOutput,
    TaskOutputRecord,
    TaskRecord,
    TaskStatus,
    TeachModeOutput,
)
from oh_no_my_claudecode.onboard.compiler import OnboardingTour
from oh_no_my_claudecode.savings.compiler import SavingsResult
from oh_no_my_claudecode.stats.health import MemoryHealth
from oh_no_my_claudecode.sync.schema import SyncResult
from oh_no_my_claudecode.timetravel.memory_diff import MemoryDiffResult
from oh_no_my_claudecode.utils.text import shorten
from oh_no_my_claudecode.why.compiler import WhyReport

console = Console()


def render_gh_aw_init_result(result: GhAwInitResult) -> None:
    """Render the outcome of ``onmc gh-aw init`` to the console."""
    if result.dry_run:
        console.print("[bold]Dry-run mode — no files written.[/bold]")

    for path in result.written:
        verb = "[dim]would write:[/dim]" if result.dry_run else "[green]wrote:[/green]"
        console.print(f"{verb} {path}")

    for path in result.skipped:
        console.print(f"[dim]skipped (already managed — use --force to overwrite):[/dim] {path}")

    if not result.written and not result.skipped:
        console.print("[green]onmc gh-aw init: done (nothing to do).[/green]")
    elif result.written and not result.dry_run:
        console.print(
            f"\n[bold]Generated {len(result.written)} workflow(s). "
            "Commit the .github/workflows/ files to activate them.[/bold]"
        )


def render_init_summary(repo_root: str, config: ProjectConfig) -> None:
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Repo root: [bold]{repo_root}[/bold]",
                    f"State dir: {config.storage.state_dir}",
                    f"Database: {config.storage.database_path}",
                    "",
                    "Next steps:",
                    "  1. onmc ingest",
                    '  2. onmc brief --task "..."',
                ]
            ),
            title="ONMC Initialized",
        )
    )


def render_ingest_result(result: IngestResult) -> None:
    table = Table(title="Ingest Summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Memories extracted", str(result.memory_count))
    table.add_row("New memories", str(result.new_memory_count))
    table.add_row("Updated memories", str(result.updated_memory_count))
    if result.llm_new_memory_count or result.llm_deduped_count:
        table.add_row("LLM-added memories", str(result.llm_new_memory_count))
        table.add_row("LLM deduplicated", str(result.llm_deduped_count))
    table.add_row("Repo files indexed", str(result.repo_file_count))
    table.add_row("File stats stored", str(result.file_stat_count))
    table.add_row("Docs parsed", str(result.doc_count))
    table.add_row("Commits analyzed", str(result.commit_count))
    console.print(table)
    for note in result.notes:
        console.print(f"[yellow]- {note}[/yellow]")


def render_brief(artifact: BriefArtifact) -> None:
    console.print(
        Panel.fit(
            f"[bold]{artifact.task}[/bold]\n{artifact.output_path or ''}",
            title="Task Brief",
        )
    )

    overview = Table(title="Repo Overview")
    overview.add_column("Item")
    for item in artifact.repo_overview:
        overview.add_row(item)
    console.print(overview)

    memories = Table(title="Relevant Memory")
    memories.add_column("Kind")
    memories.add_column("Title")
    memories.add_column("Summary")
    for memory in artifact.relevant_memories:
        memories.add_row(memory.kind.value, memory.title, memory.summary)
    if artifact.relevant_memories:
        console.print(memories)
    else:
        console.print("[yellow]No stored memory scored strongly for this task.[/yellow]")

    files = Table(title="Inspect First")
    files.add_column("Path")
    for path in artifact.files_to_inspect:
        files.add_row(path)
    console.print(files)

    console.print(Markdown("## Risk Notes"))
    for note in artifact.risk_notes:
        console.print(f"- {note}")

    console.print(Markdown("## Validation Checklist"))
    for item in artifact.validation_checklist:
        console.print(f"- {item}")

    console.print(Markdown("## Reading List"))
    for item in artifact.reading_list:
        console.print(f"1. `{item}`")


def render_memory_list(
    memories: list[MemoryEntry],
    *,
    artifacts: list[MemoryArtifactRecord] | None = None,
    wide: bool = True,
) -> None:
    artifact_rows = artifacts or []
    if not memories and not artifact_rows:
        console.print("[yellow]No stored memory found for this repository.[/yellow]")
        return
    if artifact_rows:
        artifact_table = Table(title="Task-Derived Memory Artifacts")
        artifact_table.add_column("Memory ID", no_wrap=True)
        artifact_table.add_column("Type", no_wrap=True)
        artifact_table.add_column("Task", no_wrap=True)
        artifact_table.add_column("Title", overflow="fold")
        artifact_table.add_column("Confidence", justify="right", no_wrap=True)
        for artifact in artifact_rows:
            artifact_table.add_row(
                artifact.memory_id,
                _memory_artifact_type_label(artifact.type),
                artifact.task_id,
                shorten(artifact.title, max_length=42),
                f"{artifact.confidence:.2f}",
            )
        console.print(artifact_table)

    if not memories:
        return

    table = Table(title="Stored Memory")
    table.add_column("", no_wrap=True, width=2)
    table.add_column("ID", style="dim", width=24)
    table.add_column("Kind", width=14)
    table.add_column("Title", min_width=20 if not wide else 40, no_wrap=False)
    table.add_column("Summary", min_width=24 if not wide else 48, no_wrap=False)
    table.add_column("Source", width=20, style="dim")
    table.add_column("Conf", width=6, justify="right", no_wrap=True)
    for memory in memories:
        table.add_row(
            _memory_feedback_indicator(memory.feedback_score),
            memory.id,
            memory.kind.value,
            memory.title if wide else shorten(memory.title, max_length=20),
            memory.summary if wide else shorten(memory.summary, max_length=36),
            f"{memory.source_type.value}:{memory.source_ref}",
            f"{memory.confidence:.2f}",
        )
    console.print(table)


def render_memory_detail(memory: MemoryEntry | MemoryArtifactRecord) -> None:
    if isinstance(memory, MemoryArtifactRecord):
        render_memory_artifact_detail(memory)
        return
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"[bold]{memory.title}[/bold]",
                    f"ID: {memory.id}",
                    f"Kind: {memory.kind.value}",
                    f"Source: {memory.source_type.value}:{memory.source_ref}",
                    f"Confidence: {memory.confidence:.2f}",
                    f"Feedback: {memory.feedback_score:.2f}",
                    "",
                    memory.summary,
                    "",
                    memory.details,
                ]
            ),
            title="Memory Detail",
        )
    )


def render_memory_artifact_added(artifact: MemoryArtifactRecord) -> None:
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Memory ID: [bold]{artifact.memory_id}[/bold]",
                    f"Task ID: {artifact.task_id}",
                    f"Type: {_memory_artifact_type_label(artifact.type)}",
                    f"Confidence: {artifact.confidence:.2f}",
                    "",
                    artifact.title,
                ]
            ),
            title="Memory Artifact Added",
        )
    )


def render_memory_artifact_detail(
    artifact: MemoryArtifactRecord,
    *,
    title: str = "Memory Artifact Detail",
) -> None:
    lines = [
        f"[bold]{artifact.title}[/bold]",
        f"Memory ID: {artifact.memory_id}",
        f"Type: {_memory_artifact_type_label(artifact.type)}",
        f"Task ID: {artifact.task_id}",
        "Provenance: task-derived",
        f"Confidence: {artifact.confidence:.2f}",
        f"Created: {artifact.created_at.isoformat()}",
    ]

    if artifact.type == MemoryArtifactType.DID_NOT_WORK:
        lines.extend(
            [
                "",
                "What was tried:",
                artifact.summary,
                "",
                "Why it failed:",
                artifact.evidence,
                "",
                "Why future agents should avoid repeating it:",
                artifact.why_it_matters,
            ]
        )
    elif artifact.type == MemoryArtifactType.DESIGN_CONFLICT:
        lines.extend(
            [
                "",
                "Incompatible solution:",
                artifact.summary,
                "",
                "Constraint or principle it violated:",
                artifact.evidence,
                "",
                "Why it matters:",
                artifact.why_it_matters,
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Summary:",
                artifact.summary,
                "",
                "Why it matters:",
                artifact.why_it_matters,
                "",
                "Evidence:",
                artifact.evidence,
            ]
        )

    if artifact.apply_when:
        lines.extend(["", "Apply when:", artifact.apply_when])
    if artifact.avoid_when:
        lines.extend(["", "Avoid when:", artifact.avoid_when])
    if artifact.related_files:
        lines.extend(["", f"Related files: {', '.join(artifact.related_files)}"])
    if artifact.related_modules:
        lines.extend(["", f"Related modules: {', '.join(artifact.related_modules)}"])

    console.print(Panel.fit("\n".join(lines), title=title))


def render_status(status: dict[str, str]) -> None:
    table = Table(title="ONMC Status")
    table.add_column("Field")
    table.add_column("Value")
    for key, value in status.items():
        table.add_row(key, value)
    console.print(table)


def render_doctor_report(ok: bool, report: dict[str, list[str]]) -> None:
    title = "ONMC Health Check"
    lines: list[str] = []
    for section, items in report.items():
        if section in {"warnings", "errors"}:
            continue
        lines.append(section.title())
        for item in items:
            lines.append(f"  ✓ {item}")
        lines.append("")
    if report.get("errors"):
        lines.append("Errors")
        for item in report["errors"]:
            lines.append(f"  ✗ {item}")
        lines.append("")
    if report.get("warnings"):
        lines.append("Warnings")
        for item in report["warnings"]:
            lines.append(f"  ⚠ {item}")
    console.print(Panel.fit("\n".join(lines), title=title, border_style="green" if ok else "red"))


def _memory_feedback_indicator(score: float) -> str:
    if score > 0:
        return "✓"
    if score < 0:
        return "✗"
    return ""


def render_mine_result(result: dict[str, object], *, dry_run: bool) -> None:
    message = result.get("message")
    if isinstance(message, str) and message:
        console.print(f"[yellow]{message}[/yellow]")
        return
    attempts = result.get("attempts", [])
    memories = result.get("memories", [])
    artifacts = result.get("artifacts", [])
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Mode: {'dry-run' if dry_run else 'persisted'}",
                    f"Attempts: {len(attempts) if isinstance(attempts, list) else 0}",
                    f"Memories: {len(memories) if isinstance(memories, list) else 0}",
                    f"Artifacts: {len(artifacts) if isinstance(artifacts, list) else 0}",
                ]
            ),
            title="Transcript Mining",
        )
    )


def render_sync_result(result: SyncResult, *, action: str) -> None:
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Directory: {result.output_dir}",
                    f"Memories: {result.memory_count}",
                    f"Tasks: {result.task_count}",
                    f"Attempts: {result.attempt_count}",
                    f"Artifacts: {result.artifact_count}",
                    f"Latest brief: {result.latest_brief_path or '-'}",
                ]
            ),
            title=action,
        )
    )


def render_hook_status(status: HookStatus) -> None:
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Installed: {'yes' if status.installed else 'no'}",
                    f"Settings: {status.settings_path}",
                    f"Backup: {status.backup_path}",
                    f"MCP (.mcp.json): {'registered' if status.mcp_registered else 'no'}",
                    f"Legacy global hooks: {'present' if status.legacy_global_hooks else 'none'}",
                    f"Latest snapshot: {status.latest_snapshot_id or '-'}",
                    f"Last pre-compact: {status.last_pre_compact_at or '-'}",
                    f"Last session-start: {status.last_session_start_at or '-'}",
                ]
            ),
            title="Hooks Status",
        )
    )


def render_llm_status(status: LLMStatus) -> None:
    table = Table(title="LLM Status")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("configured", "yes" if status.configured else "no")
    table.add_row("provider", status.provider.value if status.provider else "unconfigured")
    table.add_row("model", status.model or "-")
    table.add_row("api_key_env_var", status.api_key_env_var or "-")
    table.add_row("credentials_present", "yes" if status.credentials_present else "no")
    console.print(table)


def render_llm_configured(settings: LLMSettings) -> None:
    console.print(
        Panel.fit(
            "\n".join(
                [
                    (
                        "Provider: "
                        f"[bold]{settings.provider.value if settings.provider else '-'}[/bold]"
                    ),
                    f"Model: {settings.model or '-'}",
                    f"API key env var: {settings.api_key_env_var or '-'}",
                    f"Temperature: {settings.temperature:.2f}",
                    f"Max tokens: {settings.max_tokens}",
                ]
            ),
            title="LLM Configuration Saved",
        )
    )


def render_solve_output(output: SolveModeOutput, record: TaskOutputRecord) -> None:
    console.print(
        Panel.fit(
            "\n".join(
                [
                    output.approach_summary,
                    "",
                    f"Output ID: {record.output_id}",
                    f"Task ID: {record.task_id or '-'}",
                    f"Model: {record.provider}/{record.model}",
                ]
            ),
            title="Solve",
        )
    )
    _render_output_list("Inspect First", output.files_to_inspect)
    _render_output_list("Risks", output.risks, ordered=False)
    _render_output_list("Validations", output.validations, ordered=False)
    console.print(f"[cyan]Confidence:[/cyan] {output.confidence}")


def render_review_output(output: ReviewModeOutput, record: TaskOutputRecord) -> None:
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Output ID: {record.output_id}",
                    f"Task ID: {record.task_id or '-'}",
                    f"Model: {record.provider}/{record.model}",
                ]
            ),
            title="Review",
        )
    )
    _render_output_list("Concerns", output.concerns, ordered=False)
    _render_output_list("Assumptions", output.assumptions, ordered=False)
    _render_output_list("Likely Regressions", output.likely_regressions, ordered=False)
    _render_output_list("Required Tests", output.required_tests, ordered=False)


def render_teach_output(output: TeachModeOutput, record: TaskOutputRecord) -> None:
    console.print(
        Panel.fit(
            "\n".join(
                [
                    output.problem_this_solves,
                    "",
                    f"Output ID: {record.output_id}",
                    f"Task ID: {record.task_id or '-'}",
                    f"Model: {record.provider}/{record.model}",
                ]
            ),
            title="Teach",
        )
    )
    console.print("[cyan]The Problem This Solves:[/cyan]")
    console.print(output.problem_this_solves)
    console.print("[cyan]Approach Chosen And Why:[/cyan]")
    console.print(output.approach_chosen_and_why)
    _render_output_list("What Was Tried First", output.what_was_tried_first, ordered=False)
    console.print("[cyan]Current Implementation:[/cyan]")
    console.print(output.current_implementation)
    _render_output_list("Reasoning Map", output.reasoning_map, ordered=False)
    _render_output_list("What Would Break", output.what_would_break, ordered=False)
    _render_output_list("Open Questions", output.open_questions, ordered=False)
    _render_output_list("Validation", output.validation, ordered=False)
    if output.system_lesson:
        console.print("[cyan]System Lesson:[/cyan]")
        console.print(output.system_lesson)
    _render_output_list("False Lead Analysis", output.false_lead_analysis, ordered=False)
    if output.mental_model_upgrade:
        console.print("[cyan]Mental Model Upgrade:[/cyan]")
        console.print(output.mental_model_upgrade)


def render_task_started(task: TaskRecord) -> None:
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Task ID: [bold]{task.task_id}[/bold]",
                    f"Status: {_task_status_label(task.status)}",
                    f"Repo: {task.repo_root}",
                    f"Branch: {task.branch}",
                    f"Labels: {', '.join(task.labels) if task.labels else '-'}",
                    "",
                    task.title,
                ]
            ),
            title="Task Started",
        )
    )


def render_task_list(
    tasks: list[TaskRecord],
    *,
    attempt_counts: dict[str, int] | None = None,
    memory_artifact_counts: dict[str, int] | None = None,
    task_output_counts: dict[str, int] | None = None,
) -> None:
    if not tasks:
        console.print("[yellow]No tasks found for this repository.[/yellow]")
        return
    counts = attempt_counts or {}
    artifact_counts = memory_artifact_counts or {}
    output_counts = task_output_counts or {}
    if not console.is_terminal:
        console.print("Tasks")
        for task in tasks:
            console.print(
                "\t".join(
                    [
                        task.task_id,
                        task.status.value,
                        shorten(task.title, max_length=40),
                        (
                            f"{counts.get(task.task_id, 0)}/"
                            f"{artifact_counts.get(task.task_id, 0)}/"
                            f"{output_counts.get(task.task_id, 0)}"
                        ),
                        task.branch,
                    ]
                )
            )
        return
    table = Table(title="Tasks")
    table.add_column("Task ID", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Title", overflow="fold")
    table.add_column("A/M/O", no_wrap=True, justify="right")
    table.add_column("Branch", no_wrap=True)
    for task in tasks:
        table.add_row(
            task.task_id,
            _task_status_label(task.status),
            shorten(task.title, max_length=40),
            (
                f"{counts.get(task.task_id, 0)}/"
                f"{artifact_counts.get(task.task_id, 0)}/"
                f"{output_counts.get(task.task_id, 0)}"
            ),
            task.branch,
        )
    console.print(table)


def render_task_detail(
    task: TaskRecord,
    *,
    title: str = "Task Detail",
    attempts: list[AttemptRecord] | None = None,
    artifacts: list[MemoryArtifactRecord] | None = None,
    outputs: list[TaskOutputRecord] | None = None,
) -> None:
    lines = [
        f"[bold]{task.title}[/bold]",
        f"Task ID: {task.task_id}",
        f"Status: {_task_status_label(task.status)}",
        f"Repo: {task.repo_root}",
        f"Branch: {task.branch}",
        f"Labels: {', '.join(task.labels) if task.labels else '-'}",
        f"Created: {task.created_at.isoformat()}",
        f"Started: {task.started_at.isoformat() if task.started_at else '-'}",
        f"Ended: {task.ended_at.isoformat() if task.ended_at else '-'}",
        f"Confidence: {task.confidence if task.confidence is not None else '-'}",
        f"Final outcome: {task.final_outcome or '-'}",
        "",
        "Description:",
        task.description,
    ]
    if task.final_summary:
        lines.extend(["", "Final summary:", task.final_summary])
    if attempts:
        lines.extend(["", "Attempts:"])
        for attempt in attempts[:5]:
            lines.append(
                f"- {attempt.attempt_id} | {_attempt_status_label(attempt.status)} | "
                f"{attempt.kind.value} | {shorten(attempt.summary, max_length=64)}"
            )
    if artifacts:
        lines.extend(["", "Memory artifacts:"])
        for artifact in artifacts[:5]:
            lines.append(
                f"- {artifact.memory_id} | {_memory_artifact_type_label(artifact.type)} | "
                f"{shorten(artifact.title, max_length=40)}"
            )
    if outputs:
        lines.extend(["", "LLM outputs:"])
        for output in outputs[:5]:
            lines.append(
                f"- {output.output_id} | {output.type.value} | "
                f"{shorten(output.summary, max_length=56)}"
            )
    console.print(Panel.fit("\n".join(lines), title=title))


def render_task_updated(task: TaskRecord, *, action: str) -> None:
    render_task_detail(task, title=action)


def render_attempt_added(attempt: AttemptRecord) -> None:
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Attempt ID: [bold]{attempt.attempt_id}[/bold]",
                    f"Task ID: {attempt.task_id}",
                    f"Status: {_attempt_status_label(attempt.status)}",
                    f"Kind: {attempt.kind.value}",
                    "",
                    attempt.summary,
                ]
            ),
            title="Attempt Added",
        )
    )


def render_attempt_list(task_id: str, attempts: list[AttemptRecord]) -> None:
    if not attempts:
        console.print(f"[yellow]No attempts found for task {task_id}.[/yellow]")
        return
    table = Table(title=f"Attempts For {task_id}")
    table.add_column("Attempt ID", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Kind", no_wrap=True)
    table.add_column("Summary", overflow="fold")
    table.add_column("Created", no_wrap=True)
    for attempt in attempts:
        table.add_row(
            attempt.attempt_id,
            _attempt_status_label(attempt.status),
            attempt.kind.value,
            shorten(attempt.summary, max_length=48),
            attempt.created_at.strftime("%m-%d %H:%M"),
        )
    console.print(table)


def render_attempt_detail(attempt: AttemptRecord, *, title: str = "Attempt Detail") -> None:
    lines = [
        f"[bold]{attempt.summary}[/bold]",
        f"Attempt ID: {attempt.attempt_id}",
        f"Task ID: {attempt.task_id}",
        f"Status: {_attempt_status_label(attempt.status)}",
        f"Kind: {attempt.kind.value}",
        f"Created: {attempt.created_at.isoformat()}",
        f"Closed: {attempt.closed_at.isoformat() if attempt.closed_at else '-'}",
        f"Files touched: {', '.join(attempt.files_touched) if attempt.files_touched else '-'}",
    ]
    if attempt.reasoning_summary:
        lines.extend(["", "Reasoning summary:", attempt.reasoning_summary])
    if attempt.evidence_for:
        lines.extend(["", "Evidence for:", attempt.evidence_for])
    if attempt.evidence_against:
        lines.extend(["", "Evidence against:", attempt.evidence_against])
    console.print(Panel.fit("\n".join(lines), title=title))


def render_attempt_updated(attempt: AttemptRecord) -> None:
    render_attempt_detail(attempt, title="Attempt Updated")


def _task_status_label(status: TaskStatus) -> str:
    styles = {
        TaskStatus.OPEN: "[white]open[/white]",
        TaskStatus.ACTIVE: "[green]active[/green]",
        TaskStatus.BLOCKED: "[yellow]blocked[/yellow]",
        TaskStatus.SOLVED: "[blue]solved[/blue]",
        TaskStatus.ABANDONED: "[red]abandoned[/red]",
    }
    return styles[status]


def _attempt_status_label(status: AttemptStatus) -> str:
    styles = {
        AttemptStatus.PROPOSED: "[white]proposed[/white]",
        AttemptStatus.TRIED: "[yellow]tried[/yellow]",
        AttemptStatus.REJECTED: "[red]rejected[/red]",
        AttemptStatus.SUCCEEDED: "[green]succeeded[/green]",
        AttemptStatus.PARTIAL: "[blue]partial[/blue]",
    }
    return styles[status]


def _render_output_list(title: str, items: list[str], *, ordered: bool = True) -> None:
    console.print(Markdown(f"## {title}"))
    if not items:
        console.print("[yellow]- none[/yellow]")
        return
    for item in items:
        prefix = "1." if ordered else "-"
        console.print(f"{prefix} {item}")


def _memory_artifact_type_label(artifact_type: MemoryArtifactType) -> str:
    styles = {
        MemoryArtifactType.FIX: "[green]fix[/green]",
        MemoryArtifactType.DID_NOT_WORK: "[red]did_not_work[/red]",
        MemoryArtifactType.DESIGN_CONFLICT: "[yellow]design_conflict[/yellow]",
        MemoryArtifactType.GOTCHA: "[magenta]gotcha[/magenta]",
        MemoryArtifactType.INVARIANT: "[blue]invariant[/blue]",
        MemoryArtifactType.VALIDATION: "[cyan]validation[/cyan]",
    }
    return styles[artifact_type]


def render_why_report(report: WhyReport) -> None:
    """Render a WhyReport to the terminal using rich panels and tables."""
    verdict_color = "red" if "hotspot" in report.risk_verdict else "green"
    panel_lines = [
        f"[bold]{report.path}[/bold]",
        f"Risk verdict: [{verdict_color}]{report.risk_verdict}[/{verdict_color}]",
    ]
    if report.at_label:
        panel_lines.append(f"[dim]As of: {report.at_label}[/dim]")
    console.print(Panel.fit("\n".join(panel_lines), title="onmc why"))

    if report.at_label:
        console.print(
            "[yellow]Note:[/yellow] git history is bounded to the given commit. "
            "Memory entries reflect the [italic]current[/italic] store."
        )

    if report.llm_narrative:
        console.print(Markdown("## Narrative"))
        console.print(report.llm_narrative)

    if not report.has_data:
        console.print(
            "[yellow]Nothing is known about this file yet.[/yellow]\n"
            "Run [bold]onmc ingest[/bold] to index git history and docs, "
            "then [bold]onmc mine[/bold] to extract memories from session transcripts."
        )
        return

    if report.decisions:
        console.print(Markdown("## Why it looks this way"))
        for memory in report.decisions:
            console.print(f"  [bold]{memory.title}[/bold] [{memory.kind.value}]")
            console.print(f"  {memory.summary}")

    if report.failed_approaches:
        console.print(Markdown("## What was tried and failed"))
        for memory in report.failed_approaches:
            console.print(f"  [bold]{memory.title}[/bold]")
            console.print(f"  {memory.summary}")

    danger_lines: list[str] = []
    for memory in report.hotspot_memories:
        danger_lines.append(f"{memory.title}: {memory.summary}")
    if report.file_stat and report.file_stat.change_count > 0:
        danger_lines.append(
            f"Churn: {report.file_stat.change_count} modifying commits; "
            f"{report.file_stat.recent_change_count} in the last 30 days."
        )
    if report.git_history and report.git_history.commit_count > 0:
        danger_lines.append(
            f"Git history: {report.git_history.commit_count} commits touch this file."
        )
    if danger_lines:
        console.print(Markdown("## Dangerous to change because"))
        for line in danger_lines:
            console.print(f"  - {line}")

    if report.context_memories or report.related_artifacts:
        console.print(Markdown("## Related context"))
        for memory in report.context_memories:
            console.print(f"  [{memory.kind.value}] [bold]{memory.title}[/bold]: {memory.summary}")
        for artifact in report.related_artifacts:
            console.print(
                f"  [artifact/{artifact.type.value}] [bold]{artifact.title}[/bold]: "
                f"{artifact.summary}"
            )

    if report.git_history_at is not None and report.at_label:
        console.print(Markdown(f"## Recent commits (as of `{report.at_label}`)"))
        if report.git_history_at.recent_subjects:
            for subject in report.git_history_at.recent_subjects:
                console.print(f"  - {subject}")
        else:
            console.print(f"  [dim](no commits for this file at {report.at_label})[/dim]")
    elif report.git_history and report.git_history.recent_subjects:
        console.print(Markdown("## Recent commits"))
        for subject in report.git_history.recent_subjects:
            console.print(f"  - {subject}")


def render_blame_result(result: BlameResult) -> None:
    """Render a BlameResult to the terminal using rich panels and tables."""
    found_label = "yes" if result.file_exists else "[yellow]no (not in working tree)[/yellow]"
    status_lines = [
        f"[bold]{result.path}[/bold]",
        f"File found: {found_label}",
        f"Symbols extracted: {result.symbol_count}",
    ]
    if result.parse_skipped:
        status_lines.append(f"[dim]Symbol scan skipped: {result.parse_skip_reason}[/dim]")
    console.print(Panel.fit("\n".join(status_lines), title="onmc blame"))
    console.print(
        "[dim]Heuristic: regex symbol extraction + substring attachment. "
        "Results are approximate.[/dim]"
    )

    if not result.has_data:
        console.print(
            "[yellow]No recorded knowledge for this file.[/yellow]\n"
            "Run [bold]onmc ingest[/bold] to index git history and docs, "
            "then [bold]onmc mine[/bold] to extract memories from session transcripts."
        )
        return

    if result.anchors:
        console.print(Markdown("## Symbol-level governance"))
        for anchor in result.anchors:
            line_label = f"  (line {anchor.line})" if anchor.line is not None else ""
            console.print(f"\n  [bold cyan]{anchor.anchor}[/bold cyan]{line_label}")
            for memory in anchor.memories:
                console.print(f"    [{memory.kind.value}] [bold]{memory.title}[/bold]")
                console.print(f"    {memory.summary}")

    if result.file_level_memories:
        console.print(Markdown("## File-level governance (applies to whole file)"))
        for memory in result.file_level_memories:
            console.print(f"  [{memory.kind.value}] [bold]{memory.title}[/bold]")
            console.print(f"  {memory.summary}")


# ── Playbook rendering ─────────────────────────────────────────────────────────


def render_playbook_list(playbooks: list[Playbook]) -> None:
    """Render a compact summary table of generated playbooks."""
    if not playbooks:
        console.print("[yellow]No playbooks found. Run `onmc playbook generate` first.[/yellow]")
        return
    table = Table(title=f"Playbooks ({len(playbooks)})")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Title", min_width=30)
    table.add_column("Steps", justify="right", no_wrap=True)
    table.add_column("Sources", justify="right", no_wrap=True)
    table.add_column("Conf", justify="right", no_wrap=True)
    for pb in playbooks:
        table.add_row(
            pb.id[:16],
            shorten(pb.title, max_length=40),
            str(len(pb.steps)),
            str(len(pb.grounded_in)),
            f"{pb.confidence:.2f}",
        )
    console.print(table)


def render_playbook_detail(playbook: Playbook) -> None:
    """Render a single playbook with steps and provenance."""
    header_lines = [
        f"[bold]{playbook.title}[/bold]",
        f"ID: {playbook.id}",
        f"Confidence: {playbook.confidence:.2f}",
        f"Tags: {', '.join(playbook.tags) if playbook.tags else '-'}",
        "",
        f"[italic]When to use:[/italic] {playbook.trigger}",
    ]
    console.print(Panel.fit("\n".join(header_lines), title="Playbook"))

    if playbook.steps:
        console.print(Markdown("## Steps"))
        for i, step in enumerate(playbook.steps, 1):
            console.print(f"  {i}. {step}")

    if playbook.grounded_in:
        console.print(Markdown("## Grounded In"))
        for item in playbook.grounded_in:
            console.print(f"  [{item.kind}] {item.memory_id[:16]}  {item.title}")


def render_playbook_generate_summary(
    playbooks: list[Playbook],
    artifacts_written: list[str],
) -> None:
    """Render a post-generate summary panel."""
    lines = [
        f"Generated: [bold]{len(playbooks)} playbooks[/bold]",
        "",
        *[f"  • {pb.title} ({len(pb.steps)} steps, conf={pb.confidence:.2f})" for pb in playbooks],
        "",
        f"Artifacts written: {len(artifacts_written)}",
        *[f"  {path}" for path in artifacts_written],
    ]
    console.print(Panel.fit("\n".join(lines), title="Playbook Generate Complete"))


# ---------------------------------------------------------------------------
# Skill rendering
# ---------------------------------------------------------------------------


def render_skill_list(skills: list[Skill]) -> None:
    """Render a compact summary table of persisted skills."""
    if not skills:
        console.print(
            "[yellow]No skills found. Run `onmc skill promote --auto` or "
            "`onmc skill promote <playbook-id>` first.[/yellow]"
        )
        return
    table = Table(title=f"Skills ({len(skills)})")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Name", min_width=28)
    table.add_column("Uses", justify="right", no_wrap=True)
    table.add_column("Success%", justify="right", no_wrap=True)
    table.add_column("Conf", justify="right", no_wrap=True)
    table.add_column("Inject", justify="center", no_wrap=True)
    for sk in skills:
        success_pct = f"{sk.success_rate * 100:.0f}%" if sk.use_count else "-"
        table.add_row(
            sk.id[:16],
            shorten(sk.name, max_length=40),
            str(sk.use_count),
            success_pct,
            f"{sk.confidence:.2f}",
            "[green]yes[/green]" if sk.auto_inject else "[dim]no[/dim]",
        )
    console.print(table)


def render_skill_detail(skill: Skill) -> None:
    """Render a single skill with body, trigger, and metadata."""
    header_lines = [
        f"[bold]{skill.name}[/bold]",
        f"ID: {skill.id}",
        f"Confidence: {skill.confidence:.2f}  "
        f"Uses: {skill.use_count}  Success: {skill.success_rate * 100:.0f}%",
        f"Auto-inject: {'yes' if skill.auto_inject else 'no'}",
        f"Tags: {', '.join(skill.tags) if skill.tags else '-'}",
        f"Files: {', '.join(skill.files) if skill.files else '-'}",
        "",
        f"[italic]When to use:[/italic] {skill.trigger}",
    ]
    console.print(Panel.fit("\n".join(header_lines), title="Skill"))
    if skill.body:
        console.print(Markdown("## Body"))
        console.print(skill.body)
    if skill.source_memory_ids:
        console.print(Markdown("## Source Memories"))
        for mid in skill.source_memory_ids:
            console.print(f"  {mid}")


def render_skill_promoted(skills: list[Skill]) -> None:
    """Render a post-promote summary panel."""
    if not skills:
        console.print("[yellow]No new skills promoted.[/yellow]")
        return
    lines = [
        f"Promoted: [bold]{len(skills)} skill(s)[/bold]",
        "",
        *[
            f"  • {sk.name} (conf={sk.confidence:.2f}, inject={'yes' if sk.auto_inject else 'no'})"
            for sk in skills
        ],
    ]
    console.print(Panel.fit("\n".join(lines), title="Skill Promote Complete"))


def render_skill_pruned(skills: list[Skill]) -> None:
    """Render a post-prune summary panel."""
    if not skills:
        console.print("[green]No skills needed pruning.[/green]")
        return
    lines = [
        f"Pruned (auto_inject disabled): [bold]{len(skills)} skill(s)[/bold]",
        "",
        *[f"  • {sk.name} ({sk.id[:16]})" for sk in skills],
    ]
    console.print(Panel.fit("\n".join(lines), title="Skill Prune Complete"))


# ---------------------------------------------------------------------------
# User-scope memory rendering
# ---------------------------------------------------------------------------


def render_user_memory_added(memory: MemoryEntry) -> None:
    """Render confirmation that a user-scope preference was stored."""
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"ID: [bold]{memory.id}[/bold]",
                    f"Title: {memory.title}",
                    "",
                    memory.summary,
                    "",
                    "Store: ~/.onmc/user.db  (travels across all repos)",
                ]
            ),
            title="User Preference Saved",
        )
    )


def render_user_memory_list(memories: list[MemoryEntry]) -> None:
    """Render a table of user-scope preference memories."""
    if not memories:
        console.print("[yellow]No user preferences found. Use `onmc user add` to add one.[/yellow]")
        return
    table = Table(title="Your Preferences (~/.onmc/user.db)")
    table.add_column("ID", style="dim", width=24)
    table.add_column("Title", min_width=28, no_wrap=False)
    table.add_column("Summary", min_width=40, no_wrap=False)
    for memory in memories:
        table.add_row(memory.id, memory.title, shorten(memory.summary, max_length=60))
    console.print(table)


def render_user_memory_detail(memory: MemoryEntry) -> None:
    """Render a single user-scope preference."""
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"[bold]{memory.title}[/bold]",
                    f"ID: {memory.id}",
                    f"Confidence: {memory.confidence:.2f}",
                    f"Created: {memory.created_at.isoformat()}",
                    "",
                    memory.summary,
                ]
            ),
            title="User Preference Detail",
        )
    )


def render_user_memory_removed(memory_id: str, *, found: bool) -> None:
    """Render confirmation (or not-found notice) after removing a user preference."""
    if found:
        console.print(f"[green]Removed user preference:[/green] {memory_id}")
    else:
        console.print(f"[yellow]User preference not found:[/yellow] {memory_id}")


def render_user_profile(profile: UserProfile) -> None:
    """Render a derived user behavioral profile in a rich panel.

    Sections: Preferences / Patterns / Mistakes to avoid / Tooling.
    Empty sections are omitted.  When the profile is entirely empty, prints a
    hint to add user preferences first.
    """
    if profile.is_empty:
        console.print(
            "[yellow]No user profile data found. "
            "Use `onmc user add` to record preferences.[/yellow]"
        )
        return

    noun = "memory" if profile.derived_from == 1 else "memories"
    lines: list[str] = [f"Derived from {profile.derived_from} user {noun}.", ""]

    if profile.preferences:
        lines.append("[bold cyan]Preferences[/bold cyan]")
        for title, summary in profile.preferences:
            short = shorten(summary, max_length=80)
            lines.append(f"  [green]+[/green] [bold]{title}[/bold]: {short}")
        lines.append("")

    if profile.frequent_mistakes:
        lines.append("[bold red]Mistakes to avoid[/bold red]")
        for title, summary in profile.frequent_mistakes:
            short = shorten(summary, max_length=80)
            lines.append(f"  [red]-[/red] [bold]{title}[/bold]: {short}")
        lines.append("")

    if profile.tooling:
        lines.append("[bold yellow]Tooling[/bold yellow]")
        for title, summary in profile.tooling:
            short = shorten(summary, max_length=80)
            lines.append(f"  [yellow]~[/yellow] [bold]{title}[/bold]: {short}")
        lines.append("")

    if profile.patterns:
        lines.append("[bold]Patterns[/bold]")
        for title, summary in profile.patterns:
            short = shorten(summary, max_length=80)
            lines.append(f"  [dim]·[/dim] [bold]{title}[/bold]: {short}")
        lines.append("")

    console.print(Panel.fit("\n".join(lines).rstrip(), title="Your User Profile"))


def render_hud(health: MemoryHealth) -> None:
    """Render a rich multi-line HUD panel with brain observability data."""
    # --- freshness bar ---
    bar_width = 20
    if health.total_memories > 0:
        filled = round(health.freshness_pct / 100 * bar_width)
    else:
        filled = bar_width
    bar = "█" * filled + "░" * (bar_width - filled)
    freshness_color = (
        "green"
        if health.freshness_pct >= 80
        else ("yellow" if health.freshness_pct >= 50 else "red")
    )

    # --- token summary ---
    rc = health.recent_cost
    tok_k = rc.total_tokens // 1000
    tok_label = f"{tok_k}k" if tok_k >= 1 else str(rc.total_tokens)
    latency_s = rc.total_latency_ms / 1000.0

    lines: list[str] = [
        f"Total memories:  [bold]{health.total_memories}[/bold]",
        "",
        "[underline]By kind[/underline]",
    ]
    for kind, count in sorted(health.counts_by_kind.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {kind:<20} {count}")

    lines += [
        "",
        "[underline]Freshness[/underline]",
        f"  [{freshness_color}]{bar}[/{freshness_color}]  {health.freshness_pct:.0f}%",
        f"  Fresh: {health.fresh_count}  Stale: {health.stale_count}"
        f"  Orphaned: {health.orphaned_count}  Unanchored: {health.unanchored_count}",
    ]

    if health.stale_titles:
        lines += ["", "[underline]Stale memories[/underline]"]
        for title in health.stale_titles:
            lines.append(f"  · {shorten(title, max_length=70)}")

    lines += [
        "",
        "[underline]Coverage proxy[/underline]",
        f"  {health.covered_files}/{health.top_churn_files} top-churn files"
        f" covered — {health.coverage_pct:.0f}%",
        "",
        f"[underline]LLM activity (last {rc.window_hours}h)[/underline]",
        f"  Calls: {rc.call_count}  Tokens: {tok_label}  Latency: {latency_s:.1f}s total",
    ]

    console.print(Panel("\n".join(lines), title="ONMC Memory HUD", border_style="blue"))


def render_memory_diff(result: MemoryDiffResult) -> None:
    """Render a :class:`MemoryDiffResult` to the terminal using rich tables."""
    label_a = f"{result.short_a} ({result.date_a})" if result.short_a else result.commit_a
    label_b = f"{result.short_b} ({result.date_b})" if result.short_b else result.commit_b

    console.print(
        Panel.fit(
            f"From: [bold]{label_a}[/bold]\nTo:   [bold]{label_b}[/bold]",
            title="onmc memory-diff",
        )
    )

    if result.fallback_mode:
        console.print(f"[yellow]Fallback mode:[/yellow] {result.fallback_reason}")
        if result.files_changed:
            console.print(Markdown("## Files changed between commits"))
            for path in result.files_changed:
                console.print(f"  `{path}`")
        else:
            console.print("[dim]No file changes detected.[/dim]")
        return

    summary = (
        f"[green]+{len(result.added)} added[/green]  "
        f"[red]-{len(result.removed)} removed[/red]  "
        f"[yellow]~{len(result.changed)} changed[/yellow]"
    )
    console.print(summary)

    if result.added:
        table = Table(title="Added knowledge", show_header=True)
        table.add_column("Kind", style="dim", width=14)
        table.add_column("Title", min_width=30)
        table.add_column("Summary", min_width=40)
        for entry in result.added:
            table.add_row(entry.kind, entry.title, shorten(entry.summary, max_length=60))
        console.print(table)

    if result.removed:
        table = Table(title="Removed / invalidated knowledge", show_header=True)
        table.add_column("Kind", style="dim", width=14)
        table.add_column("Title", min_width=30)
        table.add_column("Summary", min_width=40)
        for entry in result.removed:
            table.add_row(entry.kind, entry.title, shorten(entry.summary, max_length=60))
        console.print(table)

    if result.changed:
        table = Table(title="Changed knowledge", show_header=True)
        table.add_column("Kind", style="dim", width=14)
        table.add_column("Title", min_width=30)
        table.add_column("Before", min_width=32)
        table.add_column("After", min_width=32)
        for change in result.changed:
            table.add_row(
                change.kind,
                change.new_title,
                shorten(change.old_summary, max_length=40),
                shorten(change.new_summary, max_length=40),
            )
        console.print(table)

    if not result.added and not result.removed and not result.changed:
        console.print("[dim]No differences in committed memory snapshots.[/dim]")


def render_onboard_summary(tour: OnboardingTour, output_path: str) -> None:
    """Render a brief onboarding tour summary panel (for non-steps mode)."""
    repo_name = tour.repo_root.split("/")[-1] or tour.repo_root
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"[bold]{repo_name}[/bold]",
                    f"Memories: {tour.memory_count}  |  "
                    f"Files indexed: {tour.file_stat_count}  |  "
                    f"Playbooks: {tour.playbook_count}",
                    "",
                    f"Tour stops: {len(tour.stops)}",
                    f"Artifact: {output_path}",
                ]
            ),
            title="onmc onboard",
        )
    )


def render_coverage_summary(report: CoverageReport) -> None:
    """Render a knowledge-gap dashboard panel to the terminal.

    Prints an overall coverage summary, a per-subsystem table (worst-covered
    first), and the top uncovered hotspot files — the actionable landmines.
    """
    # ── Overall panel ──────────────────────────────────────────────────────
    pct = report.overall_coverage_pct
    color = "green" if pct >= 70 else ("yellow" if pct >= 40 else "red")
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"[bold]Coverage:[/bold]  [{color}]{pct:.1f}%[/{color}]"
                    f"  ({report.covered_files} / {report.total_files} files)",
                    f"[dim]Memories consulted: {report.memory_count}[/dim]",
                    f"[dim]Uncovered files:    {report.uncovered_files}[/dim]",
                ]
            ),
            title="Coverage Report",
        )
    )

    if not report.subsystem_rows:
        console.print("[yellow]No file stats found — run `onmc ingest` first.[/yellow]")
        return

    # ── Per-subsystem table ────────────────────────────────────────────────
    sub_table = Table(title="Coverage by Subsystem  (worst first)")
    sub_table.add_column("Subsystem", min_width=24, no_wrap=False)
    sub_table.add_column("Files", justify="right", width=6)
    sub_table.add_column("Covered", justify="right", width=8)
    sub_table.add_column("Coverage", justify="right", width=10)
    sub_table.add_column("Churn", justify="right", width=8)

    for row in report.subsystem_rows:
        row_pct = row.coverage_pct
        row_color = "green" if row_pct >= 70 else ("yellow" if row_pct >= 40 else "red")
        sub_table.add_row(
            row.subsystem,
            str(row.total_files),
            str(row.covered_files),
            f"[{row_color}]{row_pct:.0f}%[/{row_color}]",
            str(row.total_churn),
        )
    console.print(sub_table)

    # ── Top gaps ──────────────────────────────────────────────────────────
    if report.top_gaps:
        gap_table = Table(title="Top Uncovered Hotspots  (landmines)")
        gap_table.add_column("File", min_width=30, no_wrap=False)
        gap_table.add_column("Subsystem", width=20)
        gap_table.add_column("Churn", justify="right", width=6)
        gap_table.add_column("Recent", justify="right", width=8)
        for gap in report.top_gaps:
            gap_table.add_row(
                f"[red]{gap.path}[/red]",
                gap.subsystem,
                str(gap.churn),
                str(gap.recent_churn),
            )
        console.print(gap_table)
    else:
        console.print("[green]No uncovered hotspot files — well covered![/green]")


def render_coverage_suggestions(suggestions: list[CoverageSuggestion]) -> None:
    """Render the coverage suggestion list to the terminal.

    Prints a table of actionable documentation suggestions derived from
    uncovered hotspot files.  Each row shows the file, the suggested
    memory kind, and the one-sentence rationale.
    """
    if not suggestions:
        console.print("[green]No suggestions — all hotspots are covered.[/green]")
        return

    table = Table(title="Coverage Suggestions  (document these hotspots)")
    table.add_column("File", min_width=30, no_wrap=False)
    table.add_column("Kind", width=12)
    table.add_column("Suggested Title", min_width=36, no_wrap=False)
    table.add_column("Rationale", min_width=36, no_wrap=False)

    for sug in suggestions:
        table.add_row(
            f"[yellow]{sug.file}[/yellow]",
            f"[dim]{sug.suggested_kind.value}[/dim]",
            sug.suggested_title,
            f"[dim]{sug.rationale}[/dim]",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Notify / context firewall rendering
# ---------------------------------------------------------------------------


def render_notify_status(status: dict[str, object]) -> None:
    """Render the notify sink status panel."""
    enabled = bool(status.get("enabled", True))
    sink = str(status.get("sink", "file"))
    log_path = str(status.get("log_path", ""))
    log_exists = bool(status.get("log_exists", False))
    discord = status.get("discord_webhook")
    slack = status.get("slack_webhook")

    enabled_label = "[green]enabled[/green]" if enabled else "[red]disabled[/red]"
    sink_label = f"[bold]{sink}[/bold]"

    log_state = "[green](exists)[/green]" if log_exists else "[dim](not yet created)[/dim]"
    lines = [
        f"Status:  {enabled_label}",
        f"Sink:    {sink_label}",
        f"Log:     {log_path}  {log_state}",
    ]
    if discord:
        lines.append(f"Discord: {discord}")
    if slack:
        lines.append(f"Slack:   {slack}")

    console.print(
        Panel.fit(
            "\n".join(lines),
            title="onmc notify status",
        )
    )


def render_notify_tail(events: list[dict[str, object]]) -> None:
    """Render the last N events from the notify log."""
    import datetime

    if not events:
        console.print("[dim]No events in notify log.[/dim]")
        return

    table = Table(title=f"notify log — last {len(events)} event(s)", show_lines=False)
    table.add_column("Time", width=19)
    table.add_column("Sev", width=9)
    table.add_column("Kind", width=18)
    table.add_column("Title")

    for ev in events:
        ts = ev.get("ts")
        try:
            dt = datetime.datetime.fromtimestamp(float(ts), tz=datetime.UTC)  # type: ignore[arg-type]
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:  # noqa: BLE001
            time_str = str(ts)

        severity = str(ev.get("severity", ""))
        if severity == "failure":
            sev_cell = "[red]failure[/red]"
        elif severity == "approval":
            sev_cell = "[cyan]approval[/cyan]"
        else:
            sev_cell = "[dim]routine[/dim]"

        kind = str(ev.get("kind", ""))
        title = str(ev.get("title", ""))
        table.add_row(time_str, sev_cell, kind, title)

    console.print(table)


def render_ask_result(result: AskResult) -> None:
    """Render an ``AskResult`` — synthesized answer (if any) + cited memory entries."""
    from rich.rule import Rule

    if not result.entries and not result.answer:
        hint = result.no_data_hint or "No relevant memories found."
        console.print(f"[yellow]{hint}[/yellow]")
        return

    # Synthesized answer panel (only shown when synthesis succeeded).
    if result.answer:
        console.print(
            Panel.fit(
                result.answer,
                title="[bold cyan]Answer[/bold cyan]",
                border_style="cyan",
            )
        )
    elif result.entries:
        console.print(
            "[dim]No LLM synthesis — showing ranked memory entries.[/dim]"
        )

    if not result.entries:
        return

    noun = "memory" if len(result.entries) == 1 else "memories"
    console.print(Rule(f"[dim]{len(result.entries)} relevant {noun}[/dim]"))

    table = Table(show_header=True, show_lines=True)
    table.add_column("#", width=3, justify="right", no_wrap=True)
    table.add_column("ID", style="dim", width=24, no_wrap=True)
    table.add_column("Kind", width=14, no_wrap=True)
    table.add_column("Title", min_width=24)
    table.add_column("Summary", min_width=32)
    table.add_column("Provenance", width=22, style="dim")
    table.add_column("Rel", width=5, justify="right", no_wrap=True)

    for idx, entry in enumerate(result.entries, 1):
        table.add_row(
            str(idx),
            entry.memory_id,
            entry.kind,
            entry.title,
            entry.what_happened,
            entry.citation or "",
            f"{entry.relevance:.2f}",
        )

    console.print(table)


def render_savings_card(result: SavingsResult) -> None:
    """Render a screenshot-worthy 'Memory Wrapped' ROI card.

    Displays a Rich Panel with:
    - headline context-token savings % (simulation)
    - memory / skill / playbook counts
    - repeated-failure rate improvement (simulation)
    - top hotspot files covered
    - honest simulation disclaimer footer
    """
    # --- token-savings colour ---
    ctx_pct = result.context_tokens_pct_reduction
    if ctx_pct >= 50:
        ctx_color = "green"
    elif ctx_pct >= 20:
        ctx_color = "yellow"
    else:
        ctx_color = "dim"

    # --- headline ---
    headline = (
        f"  [{ctx_color}]~{ctx_pct:.0f}%[/{ctx_color}] fewer context tokens"
        "  [dim](deterministic sim)[/dim]"
    )

    # --- brain inventory ---
    inventory_line = (
        f"  🧠  [bold]{result.memories_count}[/bold] memories"
        f"   ·   [bold]{result.skills_count}[/bold] skills"
        f"   ·   [bold]{result.playbooks_count}[/bold] playbooks"
    )

    # --- ROI table ---
    roi_table = Table(show_header=True, show_lines=False, box=None, padding=(0, 2))
    roi_table.add_column("Metric", style="bold", min_width=32)
    roi_table.add_column("Without memory", justify="right", style="dim", width=16)
    roi_table.add_column("With memory", justify="right", width=14)

    # We only have the delta; derive plausible display values from the built-in
    # scenario's known WITHOUT rate (80%) and subtract the improvement.
    rfr_without = 0.80
    rfr_with = max(0.0, rfr_without - result.repeated_failure_rate_delta)
    roi_table.add_row(
        "Repeated-failure rate  [dim](sim)[/dim]",
        f"{rfr_without:.0%}",
        f"[green]{rfr_with:.0%}[/green]",
    )
    roi_table.add_row(
        "Wasted attempts saved  [dim](sim)[/dim]",
        "—",
        f"[green]-{result.wasted_attempts_saved}[/green]",
    )

    # --- coverage ---
    cov_pct = (
        round(result.covered_hotspots / result.total_hotspots * 100)
        if result.total_hotspots > 0
        else 0
    )
    cov_color = "green" if cov_pct >= 70 else ("yellow" if cov_pct >= 40 else "dim")
    cov_line = (
        f"  [{cov_color}]{result.covered_hotspots}/{result.total_hotspots}[/{cov_color}]"
        " hotspot files covered"
    )
    if result.top_covered_names:
        cov_line += "  [dim](" + ", ".join(result.top_covered_names) + ")[/dim]"

    # --- footer ---
    footer = (
        "[dim]Sim metrics: deterministic bench — identical across runs, no LLM calls. "
        "powered by onmc — git-portable memory for coding agents[/dim]"
    )
    if result.now:
        footer += f"  [dim]· {result.now}[/dim]"

    # --- assemble panel body ---
    panel_body = "\n".join(
        [
            "",
            headline,
            "",
            inventory_line,
            "",
        ]
    )

    console.print(
        Panel(
            panel_body,
            title="[bold magenta]🧠 onmc — Memory Wrapped[/bold magenta]",
            border_style="magenta",
        )
    )

    # ROI table and coverage below the panel
    console.print(roi_table)
    console.print(cov_line)
    console.print()
    console.print(footer)


def render_benchmark_report(report: object) -> None:
    """Render a :class:`~oh_no_my_claudecode.benchmark.suite.BenchmarkReport`.

    Displays two labelled sections (MEASURED / SIM) in a Rich table, with a
    reproducibility footer.  Each metric shows its value, unit, and an honest
    kind label so the reader always knows what is live vs simulated.
    """
    from oh_no_my_claudecode.benchmark.suite import BenchmarkReport

    if not isinstance(report, BenchmarkReport):
        console.print("[yellow]No benchmark report to display.[/yellow]")
        return

    # --- headline panel ---
    brain = report.brain_memory_count
    brain_color = "green" if brain >= 10 else ("yellow" if brain >= 1 else "dim")  # noqa: PLR2004
    headline = (
        f"  [{brain_color}]{brain}[/{brain_color}] memories in brain"
        "  [dim]· MEASURED = live, SIM = deterministic model[/dim]"
    )
    console.print(
        Panel(
            f"\n{headline}\n",
            title="[bold blue]onmc benchmark[/bold blue]",
            border_style="blue",
        )
    )

    # --- MEASURED section ---
    measured = report.metrics_by_kind("measured")
    if measured:
        m_table = Table(
            title="MEASURED  [dim](live computation — no LLM)[/dim]",
            show_lines=False,
            box=None,
            padding=(0, 2),
        )
        m_table.add_column("Metric", style="bold", min_width=36)
        m_table.add_column("Value", justify="right", width=12)
        m_table.add_column("Unit", width=14)
        for metric in measured:
            m_table.add_row(metric.name, f"{metric.value:g}", metric.unit)
        console.print(m_table)

    # --- SIM section ---
    sim = report.metrics_by_kind("sim")
    if sim:
        s_table = Table(
            title="SIM  [dim](deterministic model — identical across runs)[/dim]",
            show_lines=False,
            box=None,
            padding=(0, 2),
        )
        s_table.add_column("Metric", style="bold", min_width=36)
        s_table.add_column("Value", justify="right", width=12)
        s_table.add_column("Unit", width=14)
        for metric in sim:
            val_color = "green" if metric.value > 0 else "dim"
            s_table.add_row(
                metric.name,
                f"[{val_color}]{metric.value:g}[/{val_color}]",
                metric.unit,
            )
        console.print(s_table)

    # --- footer ---
    console.print()
    console.print(f"[dim]{report.generated_note}[/dim]")


def render_import_summary(result: ImportResult) -> None:
    """Render a compact import summary table."""
    mode_label = "[dim](dry-run — nothing written)[/dim]" if result.dry_run else ""

    table = Table(title=f"Import: {result.source}  {mode_label}")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Source", result.source)
    table.add_row("Kind", result.as_kind)
    if result.dry_run:
        table.add_row("Would import", str(len(result.items)))
    else:
        table.add_row("Imported", str(result.imported))
        table.add_row("Skipped (already present)", str(result.skipped))
    console.print(table)

    if result.items:
        console.print("[dim]Items:[/dim]")
        for name in result.items[:20]:
            prefix = "  [cyan]~[/cyan]" if result.dry_run else "  [green]✓[/green]"
            console.print(f"{prefix} {name}")
        remaining = len(result.items) - 20
        if remaining > 0:
            console.print(f"  [dim]… and {remaining} more[/dim]")


def render_pull_all_summary(
    results: list[tuple[str, PullResult | Exception]],
    *,
    dry_run: bool = False,
) -> None:
    """Render a combined summary for ``onmc pull --all``.

    One row per configured source.  Successful pulls show imported/skipped
    counts; failures show the error message.
    """
    mode_label = " [dim](dry-run)[/dim]" if dry_run else ""
    table = Table(title=f"Federation pull --all{mode_label}")
    table.add_column("Source", overflow="fold", min_width=20)
    table.add_column("Label", no_wrap=True)
    if dry_run:
        table.add_column("Would pull", justify="center")
    else:
        table.add_column("Imported", justify="right")
        table.add_column("Skipped", justify="right")
    table.add_column("Status", no_wrap=True)

    total_imported = 0
    total_skipped = 0
    error_count = 0

    for source_id, outcome in results:
        if isinstance(outcome, Exception):
            error_count += 1
            if dry_run:
                table.add_row(source_id, "", "", "[red]error[/red]")
            else:
                table.add_row(source_id, "", "", "", "[red]error[/red]")
            console.print(f"  [red]Error pulling {source_id!r}:[/red] {outcome}")
        else:
            total_imported += outcome.imported
            total_skipped += outcome.skipped
            label = outcome.repo_label or ""
            if dry_run:
                table.add_row(source_id, label, "[dim]—[/dim]", "[cyan]dry-run[/cyan]")
            else:
                table.add_row(
                    source_id,
                    label,
                    str(outcome.imported),
                    str(outcome.skipped),
                    "[green]ok[/green]",
                )

    console.print(table)
    if not dry_run:
        console.print(
            f"Total: [bold]{total_imported}[/bold] imported, "
            f"{total_skipped} skipped, "
            f"{error_count} error(s)"
        )


# ---------------------------------------------------------------------------
# Loop rendering
# ---------------------------------------------------------------------------


def render_loop_result(result: LoopResult) -> None:
    """Render a :class:`LoopResult` to the terminal.

    Displays a per-iteration table (outcome, prediction, action, files) and a
    summary panel (stop_reason, converged, token count, memory records written).
    """
    if result.iterations:
        table = Table(title="Loop Iterations")
        table.add_column("#", justify="right", no_wrap=True)
        table.add_column("Outcome", no_wrap=True)
        table.add_column("Prediction", overflow="fold")
        table.add_column("Action", overflow="fold")
        table.add_column("Files", overflow="fold")
        for c in result.iterations:
            color = "green" if c.outcome == "win" else "red"
            table.add_row(
                str(c.iteration),
                f"[{color}]{c.outcome}[/{color}]",
                shorten(c.prediction, max_length=60),
                shorten(c.action_summary, max_length=60),
                ", ".join(c.files_touched[:3]) or "-",
            )
        console.print(table)

    status_color = "green" if result.converged else "yellow"
    token_str = str(result.total_tokens) if result.total_tokens else "-"
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Stop reason: [{status_color}]{result.stop_reason}[/{status_color}]",
                    f"Converged:   {'yes' if result.converged else 'no'}",
                    f"Iterations:  {len(result.iterations)}",
                    f"Tokens used: {token_str}",
                    f"Memories written: {len(result.recorded_memory_ids)}",
                ]
            ),
            title="Loop Result",
        )
    )


def render_trace_card(report: TraceReport) -> None:
    """Render the viral Agent Trace Observatory card.

    Displays a Rich Panel with:
    - Big "saved X% (est)" headline (or token counts when no savings data)
    - Tokens used vs. estimated-without-onmc
    - Repeated reads blocked
    - Tool calls / failures
    - Memory hit-rate
    - Loops detected
    - Tasteful footer with honesty label
    """
    from oh_no_my_claudecode.trace.models import TraceReport as _TraceReport

    if not isinstance(report, _TraceReport):
        console.print("[yellow]No trace report to display.[/yellow]")
        return

    # --- headline ---
    saved_pct = report.tokens_saved_pct
    if report.total_tokens > 0 and saved_pct > 0:
        pct_color = "green" if saved_pct >= 50 else ("yellow" if saved_pct >= 20 else "dim")
        headline = (
            f"  [{pct_color}]saved {saved_pct:.0f}%[/{pct_color}]"
            f"  [dim](est — bench simulation)[/dim]"
        )
    elif report.total_tokens > 0:
        headline = f"  [dim]{report.total_tokens:,} tokens used[/dim]"
    else:
        headline = "  [dim]no token events recorded — record TraceEventKind.TOKENS for ROI[/dim]"

    # --- label line ---
    label_line = ""
    if report.label:
        label_line = f"  [bold]{report.label}[/bold]\n"

    # --- session id line ---
    sid_line = f"  session: [dim]{report.session_id}[/dim]"

    panel_body = "\n".join(filter(None, ["", label_line + headline, "", sid_line, ""]))

    title_label = "[bold cyan]onmc — Agent Trace Observatory[/bold cyan]"
    console.print(Panel(panel_body, title=title_label, border_style="cyan"))

    # --- stats table ---
    stats = Table(show_header=True, show_lines=False, box=None, padding=(0, 2))
    stats.add_column("Metric", style="bold", min_width=34)
    stats.add_column("Value", justify="right", width=18)

    if report.total_tokens > 0:
        stats.add_row(
            "Tokens used",
            f"{report.total_tokens:,}",
        )
    if report.est_tokens_without_onmc > 0:
        stats.add_row(
            "Est. without onmc  [dim](est)[/dim]",
            f"{report.est_tokens_without_onmc:,}",
        )
    if report.tool_calls > 0 or report.tool_failures > 0:
        failures_str = (
            f"  [red]({report.tool_failures} failed)[/red]" if report.tool_failures > 0 else ""
        )
        stats.add_row("Tool calls", f"{report.tool_calls}{failures_str}")

    repeated_reads = report.repeated_reads_blocked
    if repeated_reads > 0:
        stats.add_row("Repeated reads blocked", f"[green]{repeated_reads}[/green]")

    hit_rate = report.memory_hit_rate
    if report.memory_hits + report.memory_misses > 0:
        hit_color = "green" if hit_rate >= 0.7 else ("yellow" if hit_rate >= 0.4 else "dim")
        stats.add_row(
            "Memory hit-rate",
            f"[{hit_color}]{hit_rate:.0%}[/{hit_color}]"
            f"  [dim]({report.memory_hits} hits / {report.memory_misses} misses)[/dim]",
        )

    if report.loops_detected:
        stats.add_row(
            "Loops detected  [yellow](potential waste)[/yellow]",
            str(len(report.loops_detected)),
        )

    console.print(stats)

    # --- top wasteful ---
    if report.top_wasteful:
        console.print("\n  [dim]Top repeated items:[/dim]")
        for item in report.top_wasteful:
            console.print(f"    [yellow]×{item.count}[/yellow]  {item.target}")

    # --- repeated reads detail ---
    if report.repeated_file_reads:
        console.print("\n  [dim]Repeated file reads:[/dim]")
        for item in report.repeated_file_reads[:5]:
            console.print(f"    [yellow]×{item.count}[/yellow]  {item.target}")

    # --- footer ---
    footer_parts = [
        "token savings (est): bench-harness simulation — no LLM calls.",
        "powered by onmc — git-portable memory for coding agents",
    ]
    console.print()
    console.print(f"[dim]{' · '.join(footer_parts)}[/dim]")


# ---------------------------------------------------------------------------
# Audit report rendering
# ---------------------------------------------------------------------------


def render_audit_report(report: AuditReport) -> None:
    """Render a security scorecard for ``onmc audit``.

    Layout
    ------
    1. Grade banner (A–F) with colour + score.
    2. Counts-by-severity table.
    3. Per-finding table (file:line, rule-id, severity, title, fix).
    4. Files scanned count.

    The scorecard is designed to be screenshot-viral — a single panel
    that communicates the security posture at a glance.
    """
    from oh_no_my_claudecode.audit.scanner import AuditReport

    if not isinstance(report, AuditReport):  # pragma: no cover
        return

    grade_colors: dict[str, str] = {
        "A": "green",
        "B": "cyan",
        "C": "yellow",
        "D": "red",
        "F": "bold red",
    }
    sev_colors: dict[str, str] = {
        "critical": "bold red",
        "high": "red",
        "medium": "yellow",
        "low": "blue",
        "info": "dim",
    }

    grade_color = grade_colors.get(report.grade, "white")

    # ── Grade banner ───────────────────────────────────────────────────────
    critical = report.counts_by_severity.get("critical", 0)
    high = report.counts_by_severity.get("high", 0)
    medium = report.counts_by_severity.get("medium", 0)
    low = report.counts_by_severity.get("low", 0)
    info = report.counts_by_severity.get("info", 0)
    total = len(report.findings)

    banner_lines = [
        f"  Grade: [{grade_color}]{report.grade}[/{grade_color}]"
        f"   Score: [{grade_color}]{report.score}/100[/{grade_color}]",
        "",
        f"  [bold red]{critical} critical[/bold red]  "
        f"[red]{high} high[/red]  "
        f"[yellow]{medium} medium[/yellow]  "
        f"[blue]{low} low[/blue]  "
        f"[dim]{info} info[/dim]",
        "",
        f"  [dim]{total} finding(s) across {len(report.files_scanned)} file(s) scanned[/dim]",
    ]
    border = "green" if report.grade == "A" else ("yellow" if report.grade in ("B", "C") else "red")
    console.print(
        Panel(
            "\n".join(banner_lines),
            title="[bold]onmc audit — Agent Config Security Scorecard[/bold]",
            border_style=border,
        )
    )

    if not report.findings:
        console.print(
            "[green]No findings — configuration looks clean.[/green]\n"
            "[dim]Re-run after any change to CLAUDE.md, AGENTS.md, "
            ".claude/settings.json, or .mcp.json.[/dim]"
        )
        return

    # ── Per-finding table ──────────────────────────────────────────────────
    table = Table(
        title=f"Findings ({total})",
        show_lines=True,
        expand=True,
    )
    table.add_column("Rule", width=12, no_wrap=True)
    table.add_column("Sev", width=10, no_wrap=True)
    table.add_column("File", min_width=20, no_wrap=False)
    table.add_column("Title", min_width=28, no_wrap=False)
    table.add_column("Fix", min_width=34, no_wrap=False)

    sev_order = ["critical", "high", "medium", "low", "info"]
    sorted_findings = sorted(
        report.findings,
        key=lambda f: (sev_order.index(f.severity), f.file, f.line or 0),
    )

    for finding in sorted_findings:
        sev_color = sev_colors.get(finding.severity, "white")
        file_cell = finding.file
        if finding.line is not None:
            file_cell = f"{finding.file}:{finding.line}"
        table.add_row(
            f"[dim]{finding.rule_id}[/dim]",
            f"[{sev_color}]{finding.severity}[/{sev_color}]",
            file_cell,
            finding.title,
            shorten(finding.fix, max_length=120),
        )
    console.print(table)


def render_eval_result(
    report: object,
    *,
    comparison: object = None,
) -> None:
    """Render an :class:`~oh_no_my_claudecode.evals.models.EvalReport` or
    :class:`~oh_no_my_claudecode.evals.models.EvalComparison`.

    When *comparison* is provided (an ``EvalComparison``), renders a
    side-by-side delta table as well as both per-condition reports.
    When only *report* is given (an ``EvalReport``), renders just that report.
    """
    from oh_no_my_claudecode.evals.models import EvalComparison, EvalReport

    # --- comparison view ---
    if isinstance(comparison, EvalComparison):
        _render_eval_comparison(comparison)
        return

    if not isinstance(report, EvalReport):
        console.print("[yellow]No eval report to display.[/yellow]")
        return

    _render_eval_report(report)


def _render_eval_report(report: object) -> None:
    """Render a single :class:`~oh_no_my_claudecode.evals.models.EvalReport`."""
    from oh_no_my_claudecode.evals.models import EvalReport

    if not isinstance(report, EvalReport):
        return

    condition = "WITH memory" if report.with_memory else "WITHOUT memory"
    score_color = "green" if report.score >= 80 else ("yellow" if report.score >= 50 else "red")  # noqa: PLR2004

    headline = (
        f"  [{score_color}]{report.score:.1f}[/{score_color}] / 100  "
        f"[dim]· {report.passed_cases}/{report.total_cases} passed[/dim]"
    )
    console.print(
        Panel(
            f"\n{headline}\n",
            title=f"[bold blue]onmc eval — {condition}[/bold blue]",
            border_style=score_color,
        )
    )

    if not report.results:
        console.print("[yellow]No eval cases found. Run `onmc eval create` to add cases.[/yellow]")
        return

    table = Table(
        title=f"Eval Cases ({report.total_cases})",
        show_lines=False,
        box=None,
        padding=(0, 2),
    )
    table.add_column("Case ID", style="dim", min_width=18)
    table.add_column("files_hit", justify="center", width=10)
    table.add_column("deadend_hit", justify="center", width=12)
    table.add_column("recall_entries", justify="right", width=14)
    table.add_column("injected_chars", justify="right", width=14)
    table.add_column("passed", justify="center", width=8)

    for r in report.results:
        table.add_row(
            shorten(r.case_id, max_length=30),
            "[green]✓[/green]" if r.files_hit else "[red]✗[/red]",
            "[green]✓[/green]" if r.deadend_hit else "[red]✗[/red]",
            str(r.recall_entries),
            str(r.injected_chars),
            "[green]✓[/green]" if r.passed else "[red]✗[/red]",
        )
    console.print(table)
    console.print(
        f"\n[dim]Mean injected chars: {report.mean_injected_chars:.0f}[/dim]"
    )


def _render_eval_comparison(comparison: object) -> None:
    """Render an :class:`~oh_no_my_claudecode.evals.models.EvalComparison`."""
    from oh_no_my_claudecode.evals.models import EvalComparison

    if not isinstance(comparison, EvalComparison):
        return

    w = comparison.with_memory
    n = comparison.without_memory

    if comparison.score_delta > 0:
        delta_color = "green"
    elif comparison.score_delta == 0:
        delta_color = "yellow"
    else:
        delta_color = "red"
    headline = (
        f"  Score delta: [{delta_color}]+{comparison.score_delta:.1f}[/{delta_color}]"
        f"  [dim]({n.score:.1f} → {w.score:.1f})[/dim]"
    )
    console.print(
        Panel(
            f"\n{headline}\n",
            title="[bold blue]onmc eval compare — with vs without memory[/bold blue]",
            border_style=delta_color,
        )
    )

    table = Table(show_lines=False, box=None, padding=(0, 2))
    table.add_column("Metric", style="bold", min_width=28)
    table.add_column("Without memory", justify="right", width=16)
    table.add_column("With memory", justify="right", width=14)
    table.add_column("Delta", justify="right", width=10)

    table.add_row(
        "Score (0–100)",
        f"{n.score:.2f}",
        f"[green]{w.score:.2f}[/green]" if w.score > n.score else f"{w.score:.2f}",
        f"[green]+{comparison.score_delta:.2f}[/green]"
        if comparison.score_delta > 0
        else f"{comparison.score_delta:.2f}",
    )
    table.add_row(
        "Pass rate",
        f"{n.pass_rate:.1%}",
        f"{w.pass_rate:.1%}",
        f"+{comparison.pass_rate_delta:.1%}",
    )
    table.add_row(
        "Mean injected chars",
        f"{n.mean_injected_chars:.0f}",
        f"{w.mean_injected_chars:.0f}",
        f"-{comparison.chars_delta:.0f}",
    )
    table.add_row(
        "Cases passed",
        f"{n.passed_cases}/{n.total_cases}",
        f"{w.passed_cases}/{w.total_cases}",
        "—",
    )
    console.print(table)
    console.print()
    console.print("[dim]Methodology: deterministic, offline — no LLM calls.[/dim]")
    console.print("[dim]without-memory baseline: all retrieval results treated as empty.[/dim]")
