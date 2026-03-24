from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import MemoryKind, TaskLifecycleError, TaskStatus
from oh_no_my_claudecode.rendering.console import (
    console,
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
app.add_typer(memory_app, name="memory")
app.add_typer(task_app, name="task")


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
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_task_list(tasks)


@task_app.command("show")
def task_show_command(task_id: str) -> None:
    """Show a stored task with lifecycle details."""
    try:
        task = _service().get_task(task_id)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if task is None:
        raise typer.Exit(code=_fatal(f"Task not found: {task_id}"))
    render_task_detail(task)


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


def _fatal(message: str) -> int:
    console.print(f"[red]{message}[/red]")
    return 1
