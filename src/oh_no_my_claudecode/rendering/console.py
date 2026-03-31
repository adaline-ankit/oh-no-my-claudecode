from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

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
    ProjectConfig,
    ReviewModeOutput,
    SolveModeOutput,
    TaskOutputRecord,
    TaskRecord,
    TaskStatus,
    TeachModeOutput,
)
from oh_no_my_claudecode.sync.schema import SyncResult
from oh_no_my_claudecode.utils.text import shorten

console = Console()


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
                    f"Latest snapshot: {status.latest_snapshot_id or '-'}",
                    f"Last pre-compact: {status.last_pre_compact_at or '-'}",
                    f"Last post-compact: {status.last_post_compact_at or '-'}",
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
