from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import (
    HookStatus,
    IngestResult,
    MemoryArtifactRecord,
    MemoryArtifactType,
    MemoryEntry,
    MemoryKind,
    TaskRecord,
    TaskStatus,
)
from oh_no_my_claudecode.sync.schema import SyncResult
from oh_no_my_claudecode.utils.text import tokenize

MemoryRecord = MemoryEntry | MemoryArtifactRecord
MemoryRecordList = list[MemoryRecord]
StringList = list[str]


@dataclass(slots=True)
class BriefResult:
    """Hold a compiled brief plus useful rendering metadata."""

    artifact_path: str | None
    markdown: str
    token_count: int
    truncated: bool = False


def init(path: str | Path = ".") -> OnmcRepo:
    """Initialize ONMC for a repo path and return a typed repo handle."""
    service = OnmcService(Path(path))
    service.init_project()
    return OnmcRepo(service)


class OnmcRepo:
    """Expose ONMC repo operations as an importable API."""

    def __init__(self, service: OnmcService) -> None:
        self._service = service
        self._memory_api = MemoryAPI(self)
        self._task_api = TaskAPI(self)
        self._hooks_api = HooksAPI(self)
        self._sync_api = SyncAPI(self)

    def ingest(self) -> IngestResult:
        """Ingest repo knowledge into ONMC memory."""
        return self._service.ingest()[1]

    def brief(self, task: str, max_tokens: int = 2000) -> BriefResult:
        """Compile a task brief and return markdown plus token metadata."""
        artifact = self._service.compile_brief(task)[1]
        markdown = artifact.to_markdown()
        token_count = len(tokenize(markdown))
        if token_count <= max_tokens:
            return BriefResult(
                artifact_path=artifact.output_path,
                markdown=markdown,
                token_count=token_count,
                truncated=False,
            )

        limited = _limit_markdown(markdown, max_tokens)
        return BriefResult(
            artifact_path=artifact.output_path,
            markdown=limited,
            token_count=token_count,
            truncated=True,
        )

    @property
    def memory(self) -> MemoryAPI:
        """Return memory operations for this repo."""
        return self._memory_api

    @property
    def task(self) -> TaskAPI:
        """Return task operations for this repo."""
        return self._task_api

    @property
    def hooks(self) -> HooksAPI:
        """Return Claude Code hook operations for this repo."""
        return self._hooks_api

    @property
    def sync(self) -> SyncAPI:
        """Return git-portable memory sync operations for this repo."""
        return self._sync_api


class MemoryAPI:
    """Expose ONMC memory operations."""

    def __init__(self, repo: OnmcRepo) -> None:
        self._repo = repo

    def add(
        self,
        *,
        type: str,
        title: str,
        summary: str,
        task_id: str | None = None,
    ) -> MemoryRecord:
        """Create a manual memory entry or a task-derived memory artifact."""
        if type in {kind.value for kind in MemoryKind}:
            return self._repo._service.add_manual_memory(
                kind=MemoryKind(type),
                title=title,
                summary=summary,
                task_id=task_id,
            )
        if type in {artifact_type.value for artifact_type in MemoryArtifactType}:
            if task_id is None:
                msg = "task_id is required when adding task-derived memory artifacts."
                raise ValueError(msg)
            return self._repo._service.add_memory_artifact(
                task_id,
                artifact_type=MemoryArtifactType(type),
                title=title,
                summary=summary,
                why_it_matters=summary,
                apply_when=None,
                avoid_when=None,
                evidence="Added via ONMC API.",
                related_files=[],
                related_modules=[],
                confidence=0.75,
            )
        msg = f"Unsupported memory type: {type}"
        raise ValueError(msg)

    def list(
        self,
        *,
        kind: str | None = None,
        type: str | None = None,
    ) -> list[MemoryRecord]:
        """List repo memories or task-derived memory artifacts."""
        if kind and type:
            msg = "Specify only one of kind or type."
            raise ValueError(msg)
        if kind:
            return [*self._repo._service.list_memories(kind=MemoryKind(kind))]
        if type:
            return [
                *self._repo._service.list_memory_artifacts(
                    artifact_type=MemoryArtifactType(type)
                )
            ]
        memories = self._repo._service.list_memories()
        artifacts = self._repo._service.list_memory_artifacts()
        return sorted(
            [*memories, *artifacts],
            key=_record_updated_at,
            reverse=True,
        )

    def show(self, id: str) -> MemoryRecord | None:
        """Return a repo memory or task-derived memory artifact by id."""
        return self._repo._service.get_memory(id) or self._repo._service.get_memory_artifact(id)

    def search(self, files: StringList) -> MemoryRecordList:
        """Search repo and task memories by related file paths."""
        repo_memories = self._repo._service.search_memories(files)
        artifacts = self._repo._service.list_memory_artifacts()
        artifact_scores: list[tuple[float, MemoryArtifactRecord]] = []
        file_tokens = set(tokenize(" ".join(files)))
        for artifact in artifacts:
            haystack = " ".join(
                [
                    artifact.title,
                    artifact.summary,
                    artifact.why_it_matters,
                    *artifact.related_files,
                    *artifact.related_modules,
                ]
            )
            score = float(len(file_tokens & set(tokenize(haystack))) * 4) + artifact.confidence
            if _artifact_matches_files(artifact, files):
                score += 4.0
            artifact_scores.append((score, artifact))

        artifact_scores.sort(key=lambda item: (-item[0], item[1].title))
        selected_artifacts = [artifact for score, artifact in artifact_scores if score > 0][:5]
        return [*repo_memories, *selected_artifacts]


class TaskAPI:
    """Expose ONMC task operations."""

    def __init__(self, repo: OnmcRepo) -> None:
        self._repo = repo

    def start(self, *, title: str, description: str = "", label: str = "") -> TaskRecord:
        """Start a task and mark it active."""
        labels = [item.strip() for item in label.split(",") if item.strip()]
        return self._repo._service.start_task(title=title, description=description, labels=labels)

    def list(self) -> list[TaskRecord]:
        """List all stored tasks."""
        return self._repo._service.list_tasks()

    def show(self, task_id: str) -> TaskRecord | None:
        """Return a single task by id."""
        return self._repo._service.get_task(task_id)

    def end(self, task_id: str, status: str, summary: str = "") -> TaskRecord:
        """End a task with a terminal status and summary."""
        return self._repo._service.end_task(task_id, status=TaskStatus(status), summary=summary)


class HooksAPI:
    """Expose Claude Code hook operations."""

    def __init__(self, repo: OnmcRepo) -> None:
        self._repo = repo

    def install(self) -> None:
        """Install Claude Code compaction hooks."""
        self._repo._service.install_hooks()

    def uninstall(self) -> None:
        """Uninstall Claude Code compaction hooks."""
        self._repo._service.uninstall_hooks()

    def status(self) -> HookStatus:
        """Return the current Claude Code hook status."""
        return self._repo._service.hooks_status()


class SyncAPI:
    """Expose git-portable memory sync operations."""

    def __init__(self, repo: OnmcRepo) -> None:
        self._repo = repo

    def commit(self, output_dir: str = ".agent-memory") -> SyncResult:
        """Export ONMC state to a git-portable directory."""
        return self._repo._service.sync_commit(output_dir=Path(output_dir))[1]

    def restore(self, input_dir: str = ".agent-memory") -> SyncResult:
        """Restore ONMC state from a git-portable directory."""
        return self._repo._service.sync_restore(input_dir=Path(input_dir))[1]

    def install_hook(self) -> None:
        """Install the post-commit ONMC sync hook."""
        self._repo._service.install_sync_hook()


def _limit_markdown(markdown: str, max_tokens: int) -> str:
    lines_out: list[str] = []
    used = 0
    for line in markdown.splitlines():
        tokens = line.split()
        if not tokens:
            lines_out.append("")
            continue
        remaining = max_tokens - used
        if remaining <= 0:
            break
        if len(tokens) <= remaining:
            lines_out.append(line)
            used += len(tokens)
            continue
        lines_out.append(" ".join(tokens[:remaining]) + " ...")
        used += remaining
        break
    lines_out.extend(["", "[truncated to fit token budget]"])
    return "\n".join(lines_out).strip() + "\n"


def _record_updated_at(record: MemoryRecord) -> datetime:
    if isinstance(record, MemoryEntry):
        return record.updated_at
    return record.created_at


def _artifact_matches_files(artifact: MemoryArtifactRecord, files: list[str]) -> bool:
    return any(
        path in artifact.related_files or any(path in related for related in artifact.related_files)
        for path in files
    )
