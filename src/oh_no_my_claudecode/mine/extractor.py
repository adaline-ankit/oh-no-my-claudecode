from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, RootModel

from oh_no_my_claudecode.llm import generate_structured_logged
from oh_no_my_claudecode.llm.base import BaseLLMProvider, LLMProviderError
from oh_no_my_claudecode.mine.transcript import discover_transcripts, parse_assistant_turns
from oh_no_my_claudecode.models import (
    AttemptKind,
    AttemptRecord,
    AttemptStatus,
    LLMGenerationRequest,
    MemoryArtifactRecord,
    MemoryArtifactType,
    MemoryEntry,
    MemoryKind,
    SourceType,
    TaskRecord,
)
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import stable_id, tokenize
from oh_no_my_claudecode.utils.time import utc_now


class TranscriptFinding(BaseModel):
    kind: str
    title: str
    summary: str
    files_touched: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    session_id: str


class TranscriptFindingList(RootModel[list[TranscriptFinding]]):
    pass


def extract_transcript_findings(
    *,
    provider: BaseLLMProvider,
    transcript_text: str,
    session_id: str,
    log_path: Path,
) -> list[TranscriptFinding]:
    """Extract structured findings from assistant-only transcript turns."""
    try:
        payload = generate_structured_logged(
            provider,
            LLMGenerationRequest(
                system_prompt="Return only valid JSON. Do not include markdown fences.",
                prompt=_transcript_prompt(transcript_text, session_id),
                temperature=0.0,
                max_tokens=1800,
            ),
            TranscriptFindingList,
            log_path=log_path,
            operation=f"mine.session.{session_id}",
        )
    except LLMProviderError:
        return []
    return [item for item in payload.root if item.confidence >= 0.8]


def mine_transcripts(
    *,
    repo_root: Path,
    storage: SQLiteStorage,
    provider: BaseLLMProvider | None,
    log_path: Path | None,
    dry_run: bool = False,
    session_id: str | None = None,
    since: str | None = None,
) -> dict[str, object]:
    """Mine Claude Code transcripts into attempts and memory records."""
    transcript_paths = discover_transcripts(repo_root, session_id=session_id, since=since)
    if not transcript_paths:
        return {
            "message": "No Claude Code sessions found for this repo yet.",
            "attempts": [],
            "memories": [],
            "artifacts": [],
        }
    attempts: list[AttemptRecord] = []
    memories: list[MemoryEntry] = []
    artifacts: list[MemoryArtifactRecord] = []
    for path in transcript_paths:
        transcript_text, transcript_files = parse_assistant_turns(path)
        if not transcript_text:
            continue
        findings = (
            extract_transcript_findings(
                provider=provider,
                transcript_text=transcript_text,
                session_id=path.stem,
                log_path=log_path,
            )
            if provider is not None and log_path is not None
            else []
        )
        linked_task = _link_task(storage.list_tasks(), transcript_files)
        for finding in findings:
            attempt, memory, artifact = _finding_to_records(finding, linked_task)
            if attempt is not None:
                attempts.append(attempt)
            if memory is not None:
                memories.append(memory)
            if artifact is not None:
                artifacts.append(artifact)
    if not dry_run:
        for memory in memories:
            storage.upsert_memories([memory])
        for attempt in attempts:
            storage.create_attempt(attempt)
        for artifact in artifacts:
            storage.create_memory_artifact(artifact)
    return {
        "message": None,
        "attempts": attempts,
        "memories": memories,
        "artifacts": artifacts,
    }


def _finding_to_records(
    finding: TranscriptFinding,
    task: TaskRecord | None,
) -> tuple[AttemptRecord | None, MemoryEntry | None, MemoryArtifactRecord | None]:
    now = utc_now()
    files = finding.files_touched
    if finding.kind == "attempt" and task is not None:
        attempt = AttemptRecord(
            attempt_id=stable_id(finding.session_id, finding.title, prefix="attempt"),
            task_id=task.task_id,
            summary=finding.summary,
            kind=AttemptKind.INVESTIGATION,
            status=AttemptStatus.PARTIAL,
            reasoning_summary="Mined from Claude Code session transcript.",
            evidence_for=None,
            evidence_against=None,
            files_touched=files,
            created_at=now,
            closed_at=None,
        )
        return attempt, None, None
    if finding.kind == "decision":
        memory = MemoryEntry(
            id=stable_id(finding.session_id, finding.title, prefix=MemoryKind.DECISION.value),
            kind=MemoryKind.DECISION,
            title=finding.title,
            summary=finding.summary,
            details=finding.summary,
            source_type=SourceType.TRANSCRIPT,
            source_ref=finding.session_id,
            tags=tokenize(" ".join(files))[:8],
            confidence=finding.confidence,
            created_at=now,
            updated_at=now,
        )
        return None, memory, None
    artifact_type = (
        MemoryArtifactType.GOTCHA
        if finding.kind == "gotcha"
        else MemoryArtifactType.DID_NOT_WORK
    )
    if task is not None:
        artifact = MemoryArtifactRecord(
            memory_id=stable_id(finding.session_id, finding.title, prefix="artifact"),
            task_id=task.task_id,
            type=artifact_type,
            title=finding.title,
            summary=finding.summary,
            why_it_matters="Mined from a Claude Code session transcript.",
            apply_when=None,
            avoid_when=None,
            evidence=f"Session: {finding.session_id}",
            related_files=files,
            related_modules=[],
            confidence=finding.confidence,
            created_at=now,
        )
        return None, None, artifact
    memory = MemoryEntry(
        id=stable_id(finding.session_id, finding.title, prefix=MemoryKind.GOTCHA.value),
        kind=MemoryKind.GOTCHA if finding.kind == "gotcha" else MemoryKind.FAILED_APPROACH,
        title=finding.title,
        summary=finding.summary,
        details=f"Session: {finding.session_id}",
        source_type=SourceType.TRANSCRIPT,
        source_ref=finding.session_id,
        tags=tokenize(" ".join(files))[:8],
        confidence=finding.confidence,
        created_at=now,
        updated_at=now,
    )
    return None, memory, None


def _link_task(tasks: list[TaskRecord], files: list[str]) -> TaskRecord | None:
    if not files:
        return None
    file_tokens = set(tokenize(" ".join(files)))
    if not file_tokens:
        return None
    best_task: TaskRecord | None = None
    best_score = 0.0
    for task in tasks:
        task_tokens = set(tokenize(f"{task.title} {task.description}"))
        overlap = len(file_tokens & task_tokens) / max(len(file_tokens), 1)
        if overlap > 0.3 and overlap > best_score:
            best_task = task
            best_score = overlap
    return best_task


def _transcript_prompt(transcript_text: str, session_id: str) -> str:
    return (
        "You are extracting structured engineering memory from a Claude Code "
        "session transcript.\n\n"
        "The transcript shows what an AI coding agent did during a working session.\n\n"
        "Extract:\n"
        "1. attempts: things the agent tried (successful or not)\n"
        "2. decisions: architectural choices made during the session\n"
        "3. did_not_work: approaches that failed and why\n"
        "4. gotchas: non-obvious issues discovered\n\n"
        "For each item, return:\n"
        "{\n"
        '  "kind": "attempt" | "decision" | "did_not_work" | "gotcha",\n'
        '  "title": "short title",\n'
        '  "summary": "what happened, 1-2 sentences",\n'
        '  "files_touched": ["list of files mentioned"],\n'
        '  "confidence": 0.0-1.0,\n'
        f'  "session_id": "{session_id}"\n'
        "}\n\n"
        "Only include items with confidence >= 0.8.\n"
        "Do not include routine operations (file reads, directory listings).\n"
        "Focus on decisions, discoveries, failures, and non-obvious findings.\n\n"
        f"Transcript:\n{transcript_text}"
    )
