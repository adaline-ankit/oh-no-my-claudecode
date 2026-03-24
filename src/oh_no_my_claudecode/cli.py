from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import (
    AttemptKind,
    AttemptStatus,
    MemoryKind,
    TaskLifecycleError,
    TaskStatus,
)
from oh_no_my_claudecode.rendering.console import (
    console,
    render_attempt_added,
    render_attempt_detail,
    render_attempt_list,
    render_attempt_updated,
    render_brief,
    render_ingest_result,
    render_init_summary,
    render_memory_detail,
    render_memory_list,
    render_status,
    render_task_detail,
    render_task_list,
    render_task_started,
    render_task_updated,
)

app = typer.Typer(
    help="Repo-native memory and context compiler for coding agents.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
memory_app = typer.Typer(help="Inspect stored memory.", no_args_is_help=True)
task_app = typer.Typer(help="Manage task lifecycle state.", no_args_is_help=True)
attempt_app = typer.Typer(help="Track task-scoped attempts.", no_args_is_help=True)
app.add_typer(memory_app, name="memory")
app.add_typer(task_app, name="task")
app.add_typer(attempt_app, name="attempt")


def main() -> None:
    app()


def _service() -> OnmcService:
    return OnmcService(Path.cwd())


@app.command("init")
def init_command() -> None:
    """Initialize ONMC state in the current git repository."""
    repo_root, config = _service().init_project()
    render_init_summary(repo_root.as_posix(), config)


@app.command("ingest")
def ingest_command() -> None:
    """Ingest repo knowledge into local structured memory."""
    try:
        _, result = _service().ingest()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_ingest_result(result)


@app.command("brief")
def brief_command(
    task: Annotated[str, typer.Option("--task", help="Task description to compile a brief for.")],
) -> None:
    """Compile a task-specific context brief."""
    try:
        _, artifact = _service().compile_brief(task)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_brief(artifact)
    console.print(f"[green]Wrote brief:[/green] {artifact.output_path}")


@app.command("status")
def status_command() -> None:
    """Show local ONMC status."""
    try:
        render_status(_service().status())
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc


@memory_app.command("list")
def memory_list_command(
    kind: Annotated[
        MemoryKind | None,
        typer.Option("--kind", help="Filter by memory kind."),
    ] = None,
) -> None:
    """List stored memory entries."""
    try:
        memories = _service().list_memories(kind=kind)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_memory_list(memories)


@memory_app.command("show")
def memory_show_command(memory_id: str) -> None:
    """Show a single memory entry with provenance."""
    try:
        memory = _service().get_memory(memory_id)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if memory is None:
        raise typer.Exit(code=_fatal(f"Memory not found: {memory_id}"))
    render_memory_detail(memory)


@task_app.command("start")
def task_start_command(
    title: Annotated[str, typer.Option("--title", help="Short task title.")],
    description: Annotated[str, typer.Option("--description", help="Task description.")],
    labels: Annotated[
        list[str] | None,
        typer.Option("--label", help="Repeat to attach one or more labels."),
    ] = None,
) -> None:
    """Create and activate a new task for the current repository."""
    try:
        task = _service().start_task(
            title=title,
            description=description,
            labels=labels or [],
        )
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_task_started(task)


@task_app.command("list")
def task_list_command() -> None:
    """List tasks for the current repository."""
    try:
        tasks = _service().list_tasks()
        attempt_counts = _service().attempt_counts_by_task()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_task_list(tasks, attempt_counts=attempt_counts)


@task_app.command("show")
def task_show_command(task_id: str) -> None:
    """Show a stored task with lifecycle details."""
    try:
        task = _service().get_task(task_id)
        attempts = _service().list_attempts_for_task(task_id)
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if task is None:
        raise typer.Exit(code=_fatal(f"Task not found: {task_id}"))
    render_task_detail(task, attempts=attempts)


@task_app.command("end")
def task_end_command(
    task_id: str,
    summary: Annotated[str, typer.Option("--summary", help="Final task summary.")],
    status: Annotated[
        TaskStatus,
        typer.Option("--status", help="Terminal task status."),
    ] = TaskStatus.SOLVED,
) -> None:
    """End a task with a terminal status and final summary."""
    try:
        task = _service().end_task(task_id, status=status, summary=summary)
    except (FileNotFoundError, LookupError, TaskLifecycleError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_task_updated(task, action="Task Ended")


@task_app.command("status")
def task_status_command(
    task_id: str,
    status: Annotated[
        TaskStatus,
        typer.Option("--status", help="New task status."),
    ],
) -> None:
    """Update task status."""
    try:
        task = _service().update_task_status(task_id, status)
    except (FileNotFoundError, LookupError, TaskLifecycleError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_task_updated(task, action="Task Updated")


@attempt_app.command("add")
def attempt_add_command(
    task_id: str,
    summary: Annotated[str, typer.Option("--summary", help="Short attempt summary.")],
    kind: Annotated[
        AttemptKind,
        typer.Option("--kind", help="Attempt kind."),
    ],
    status: Annotated[
        AttemptStatus,
        typer.Option("--status", help="Attempt status."),
    ],
    reasoning_summary: Annotated[
        str | None,
        typer.Option("--reasoning-summary", help="Why this attempt seemed worth trying."),
    ] = None,
    evidence_for: Annotated[
        str | None,
        typer.Option("--evidence-for", help="Signals supporting the attempt."),
    ] = None,
    evidence_against: Annotated[
        str | None,
        typer.Option("--evidence-against", help="Signals against the attempt."),
    ] = None,
    files_touched: Annotated[
        list[str] | None,
        typer.Option("--file", help="Repeat to record touched file paths."),
    ] = None,
) -> None:
    """Add an attempt record for a task."""
    try:
        attempt = _service().add_attempt(
            task_id,
            summary=summary,
            kind=kind,
            status=status,
            reasoning_summary=reasoning_summary,
            evidence_for=evidence_for,
            evidence_against=evidence_against,
            files_touched=files_touched or [],
        )
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_attempt_added(attempt)


@attempt_app.command("list")
def attempt_list_command(task_id: str) -> None:
    """List attempts attached to a task."""
    try:
        attempts = _service().list_attempts_for_task(task_id)
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_attempt_list(task_id, attempts)


@attempt_app.command("show")
def attempt_show_command(attempt_id: str) -> None:
    """Show one attempt record."""
    try:
        attempt = _service().get_attempt(attempt_id)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if attempt is None:
        raise typer.Exit(code=_fatal(f"Attempt not found: {attempt_id}"))
    render_attempt_detail(attempt)


@attempt_app.command("update")
def attempt_update_command(
    attempt_id: str,
    status: Annotated[
        AttemptStatus,
        typer.Option("--status", help="Updated attempt status."),
    ],
    summary: Annotated[
        str | None,
        typer.Option("--summary", help="Replace the attempt summary."),
    ] = None,
    reasoning_summary: Annotated[
        str | None,
        typer.Option("--reasoning-summary", help="Update reasoning notes."),
    ] = None,
    evidence_for: Annotated[
        str | None,
        typer.Option("--evidence-for", help="Update supporting evidence."),
    ] = None,
    evidence_against: Annotated[
        str | None,
        typer.Option("--evidence-against", help="Update counter-evidence."),
    ] = None,
    files_touched: Annotated[
        list[str] | None,
        typer.Option("--file", help="Replace touched file paths."),
    ] = None,
) -> None:
    """Update an existing attempt."""
    try:
        attempt = _service().update_attempt(
            attempt_id,
            status=status,
            summary=summary,
            reasoning_summary=reasoning_summary,
            evidence_for=evidence_for,
            evidence_against=evidence_against,
            files_touched=files_touched,
        )
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_attempt_updated(attempt)


def _fatal(message: str) -> int:
    console.print(f"[red]{message}[/red]")
    return 1
