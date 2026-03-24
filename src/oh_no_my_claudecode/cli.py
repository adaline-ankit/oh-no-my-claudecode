from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.llm.base import LLMConfigurationError, LLMProviderError
from oh_no_my_claudecode.models import (
    AttemptKind,
    AttemptStatus,
    LLMProviderType,
    MemoryArtifactType,
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
    render_llm_configured,
    render_llm_status,
    render_memory_artifact_added,
    render_memory_detail,
    render_memory_list,
    render_review_output,
    render_solve_output,
    render_status,
    render_task_detail,
    render_task_list,
    render_task_started,
    render_task_updated,
    render_teach_output,
)

app = typer.Typer(
    help="Repo-native memory and context compiler for coding agents.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
memory_app = typer.Typer(help="Inspect stored memory.", no_args_is_help=True)
task_app = typer.Typer(help="Manage task lifecycle state.", no_args_is_help=True)
attempt_app = typer.Typer(help="Track task-scoped attempts.", no_args_is_help=True)
llm_app = typer.Typer(help="Configure optional LLM providers.", no_args_is_help=True)
app.add_typer(memory_app, name="memory")
app.add_typer(task_app, name="task")
app.add_typer(attempt_app, name="attempt")
app.add_typer(llm_app, name="llm")


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


@app.command("solve")
def solve_command(
    task: Annotated[str, typer.Option("--task", help="Engineering task to solve.")],
    task_id: Annotated[
        str | None,
        typer.Option("--task-id", help="Optional existing task to link this output to."),
    ] = None,
) -> None:
    """Compile repo-aware context and ask the configured LLM for the next best approach."""
    try:
        _, record, output = _service().solve(task=task, task_id=task_id)
    except (
        FileNotFoundError,
        LookupError,
        ValueError,
        LLMConfigurationError,
        LLMProviderError,
    ) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_solve_output(output, record)
    console.print(f"[green]Wrote output:[/green] {record.markdown_path}")


@app.command("review")
def review_command(
    task: Annotated[str, typer.Option("--task", help="Task or proposed change to review.")],
    input_file: Annotated[
        Path | None,
        typer.Option("--input-file", help="Optional file containing plan, diff, or notes."),
    ] = None,
) -> None:
    """Compile repo-aware review context and critique the proposed approach."""
    try:
        external_input = input_file.read_text(encoding="utf-8") if input_file else None
        _, record, output = _service().review(task=task, external_input=external_input)
    except (
        FileNotFoundError,
        OSError,
        ValueError,
        LLMConfigurationError,
        LLMProviderError,
    ) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_review_output(output, record)
    console.print(f"[green]Wrote output:[/green] {record.markdown_path}")


@app.command("teach")
def teach_command(
    task: Annotated[str, typer.Option("--task", help="Task to explain and teach from.")],
    task_id: Annotated[
        str | None,
        typer.Option("--task-id", help="Optional existing task to link this output to."),
    ] = None,
) -> None:
    """Compile repo-aware teaching context and generate a learning artifact."""
    try:
        _, record, output = _service().teach(task=task, task_id=task_id)
    except (
        FileNotFoundError,
        LookupError,
        ValueError,
        LLMConfigurationError,
        LLMProviderError,
    ) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_teach_output(output, record)
    console.print(f"[green]Wrote output:[/green] {record.markdown_path}")


@llm_app.command("status")
def llm_status_command() -> None:
    """Show optional LLM provider configuration status."""
    try:
        _, status = _service().llm_status()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_llm_status(status)


@llm_app.command("configure")
def llm_configure_command(
    provider: Annotated[
        LLMProviderType,
        typer.Option("--provider", help="LLM provider to configure."),
    ],
    model: Annotated[str, typer.Option("--model", help="Default model name.")],
    api_key_env_var: Annotated[
        str | None,
        typer.Option(
            "--api-key-env-var",
            help="Environment variable to read the provider API key from.",
        ),
    ] = None,
    temperature: Annotated[
        float,
        typer.Option("--temperature", min=0.0, max=2.0, help="Default temperature."),
    ] = 0.0,
    max_tokens: Annotated[
        int,
        typer.Option("--max-tokens", min=1, help="Default maximum output tokens."),
    ] = 1024,
) -> None:
    """Persist optional LLM provider settings to the local ONMC config."""
    try:
        _, settings = _service().configure_llm(
            provider=provider,
            model=model,
            api_key_env_var=api_key_env_var,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_llm_configured(settings)


@memory_app.command("list")
def memory_list_command(
    kind: Annotated[
        MemoryKind | None,
        typer.Option("--kind", help="Filter by memory kind."),
    ] = None,
    artifact_type: Annotated[
        MemoryArtifactType | None,
        typer.Option("--type", help="Filter task-derived memory artifacts by type."),
    ] = None,
) -> None:
    """List stored memory entries."""
    if kind is not None and artifact_type is not None:
        raise typer.Exit(code=_fatal("Use either --kind or --type, not both."))
    try:
        memories = _service().list_memories(kind=kind)
        artifacts = _service().list_memory_artifacts(artifact_type=artifact_type)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if kind is not None:
        artifacts = []
    if artifact_type is not None:
        memories = []
    render_memory_list(memories, artifacts=artifacts)


@memory_app.command("add")
def memory_add_command(
    task_id: str,
    artifact_type: Annotated[
        MemoryArtifactType,
        typer.Option("--type", help="Task-derived memory artifact type."),
    ],
    title: Annotated[str, typer.Option("--title", help="Short artifact title.")],
    summary: Annotated[
        str,
        typer.Option("--summary", help="What worked, failed, or conflicted."),
    ],
    why_it_matters: Annotated[
        str,
        typer.Option(
            "--why-it-matters",
            help="Why a future agent or engineer should keep this in mind.",
        ),
    ] = "Preserve this task outcome so future work starts from a known result.",
    apply_when: Annotated[
        str | None,
        typer.Option("--apply-when", help="When this guidance should be used."),
    ] = None,
    avoid_when: Annotated[
        str | None,
        typer.Option("--avoid-when", help="When this guidance should not be applied."),
    ] = None,
    evidence: Annotated[
        str,
        typer.Option("--evidence", help="Evidence from the task or attempts."),
    ] = "Recorded from task-scoped work.",
    related_files: Annotated[
        list[str] | None,
        typer.Option("--file", help="Repeat to record related file paths."),
    ] = None,
    related_modules: Annotated[
        list[str] | None,
        typer.Option("--module", help="Repeat to record related module names."),
    ] = None,
    confidence: Annotated[
        float,
        typer.Option("--confidence", min=0.0, max=1.0, help="Confidence from 0.0 to 1.0."),
    ] = 0.7,
) -> None:
    """Add a task-derived memory artifact."""
    try:
        artifact = _service().add_memory_artifact(
            task_id,
            artifact_type=artifact_type,
            title=title,
            summary=summary,
            why_it_matters=why_it_matters,
            apply_when=apply_when,
            avoid_when=avoid_when,
            evidence=evidence,
            related_files=related_files or [],
            related_modules=related_modules or [],
            confidence=confidence,
        )
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_memory_artifact_added(artifact)


@memory_app.command("show")
def memory_show_command(memory_id: str) -> None:
    """Show a single memory entry with provenance."""
    try:
        artifact = _service().get_memory_artifact(memory_id)
        memory = _service().get_memory(memory_id) if artifact is None else None
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if artifact is not None:
        render_memory_detail(artifact)
        return
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
        memory_artifact_counts = _service().memory_artifact_counts_by_task()
        task_output_counts = _service().task_output_counts_by_task()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_task_list(
        tasks,
        attempt_counts=attempt_counts,
        memory_artifact_counts=memory_artifact_counts,
        task_output_counts=task_output_counts,
    )


@task_app.command("show")
def task_show_command(task_id: str) -> None:
    """Show a stored task with lifecycle details."""
    try:
        task = _service().get_task(task_id)
        attempts = _service().list_attempts_for_task(task_id)
        artifacts = _service().list_memory_artifacts_for_task(task_id)
        outputs = _service().list_task_outputs_for_task(task_id)
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if task is None:
        raise typer.Exit(code=_fatal(f"Task not found: {task_id}"))
    render_task_detail(task, attempts=attempts, artifacts=artifacts, outputs=outputs)


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
