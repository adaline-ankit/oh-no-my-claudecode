from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from oh_no_my_claudecode.models import BriefArtifact, IngestResult, MemoryEntry, ProjectConfig

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
