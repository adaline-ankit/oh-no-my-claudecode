from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from oh_no_my_claudecode.models import (
    AttemptRecord,
    AttemptStatus,
    BriefArtifact,
    IngestResult,
    MemoryEntry,
    ProjectConfig,
    TaskRecord,
    TaskStatus,
)
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


def render_memory_list(memories: list[MemoryEntry]) -> None:
    table = Table(title="Stored Memory")
    table.add_column("ID")
    table.add_column("Kind")
    table.add_column("Title")
    table.add_column("Source")
    table.add_column("Confidence", justify="right")
    for memory in memories:
        table.add_row(
            memory.id,
            memory.kind.value,
            memory.title,
            f"{memory.source_type.value}:{memory.source_ref}",
            f"{memory.confidence:.2f}",
        )
    console.print(table)


def render_memory_detail(memory: MemoryEntry) -> None:
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"[bold]{memory.title}[/bold]",
                    f"ID: {memory.id}",
                    f"Kind: {memory.kind.value}",
                    f"Source: {memory.source_type.value}:{memory.source_ref}",
                    f"Confidence: {memory.confidence:.2f}",
                    "",
                    memory.summary,
                    "",
                    memory.details,
                ]
            ),
            title="Memory Detail",
        )
    )


def render_status(status: dict[str, str]) -> None:
    table = Table(title="ONMC Status")
    table.add_column("Field")
    table.add_column("Value")
    for key, value in status.items():
        table.add_row(key, value)
    console.print(table)


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
) -> None:
    if not tasks:
        console.print("[yellow]No tasks found for this repository.[/yellow]")
        return
    table = Table(title="Tasks")
    table.add_column("Task ID", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Title", overflow="fold")
    table.add_column("Attempts", no_wrap=True, justify="right")
    table.add_column("Branch", no_wrap=True)
    table.add_column("Labels", overflow="fold")
    table.add_column("Created", no_wrap=True)
    counts = attempt_counts or {}
    for task in tasks:
        table.add_row(
            task.task_id,
            _task_status_label(task.status),
            shorten(task.title, max_length=32),
            str(counts.get(task.task_id, 0)),
            task.branch,
            shorten(", ".join(task.labels) if task.labels else "-", max_length=18),
            task.created_at.strftime("%m-%d %H:%M"),
        )
    console.print(table)


def render_task_detail(
    task: TaskRecord,
    *,
    title: str = "Task Detail",
    attempts: list[AttemptRecord] | None = None,
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
