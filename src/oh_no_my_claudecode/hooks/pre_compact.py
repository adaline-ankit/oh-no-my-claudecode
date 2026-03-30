from __future__ import annotations

import secrets

from oh_no_my_claudecode.models import (
    AttemptRecord,
    CompactionSnapshotRecord,
    MemoryArtifactRecord,
    MemoryEntry,
    MemoryKind,
    TaskOutputRecord,
    TaskRecord,
)
from oh_no_my_claudecode.utils.text import tokenize, unique_preserve
from oh_no_my_claudecode.utils.time import utc_now


def build_compaction_snapshot(
    *,
    task: TaskRecord | None,
    attempts: list[AttemptRecord],
    artifacts: list[MemoryArtifactRecord],
    outputs: list[TaskOutputRecord],
    memories: list[MemoryEntry],
) -> CompactionSnapshotRecord:
    """Build a compaction snapshot from the most recent task-scoped state."""
    active_files = _active_files(attempts=attempts, artifacts=artifacts)
    recent_decisions = _recent_decisions(task=task, active_files=active_files, memories=memories)
    latest_attempt = attempts[0] if attempts else None
    latest_output = outputs[0] if outputs else None
    return CompactionSnapshotRecord(
        id=f"snapshot-{secrets.token_hex(4)}",
        task_id=task.task_id if task else None,
        timestamp=utc_now(),
        active_files=active_files,
        recent_decisions=recent_decisions,
        working_hypothesis=(
            latest_attempt.reasoning_summary
            if latest_attempt and latest_attempt.reasoning_summary
            else (latest_attempt.summary if latest_attempt else None)
        ),
        last_error_trace=latest_attempt.evidence_against if latest_attempt else None,
        next_step=latest_output.summary if latest_output else None,
        brief_token_count=None,
        continuation_brief_md=None,
    )


def _active_files(
    *,
    attempts: list[AttemptRecord],
    artifacts: list[MemoryArtifactRecord],
) -> list[str]:
    files: list[str] = []
    for attempt in attempts[:5]:
        files.extend(attempt.files_touched)
    for artifact in artifacts[:5]:
        files.extend(artifact.related_files)
    return unique_preserve(file for file in files if file)[:10]


def _recent_decisions(
    *,
    task: TaskRecord | None,
    active_files: list[str],
    memories: list[MemoryEntry],
) -> list[str]:
    task_text = ""
    if task is not None:
        task_text = f"{task.title} {task.description}"
    active_text = " ".join(active_files)
    task_tokens = set(tokenize(f"{task_text} {active_text}"))
    ranked: list[tuple[float, str]] = []
    for memory in memories:
        if memory.kind not in {
            MemoryKind.DECISION,
            MemoryKind.INVARIANT,
            MemoryKind.VALIDATION_RULE,
        }:
            continue
        source_tokens = set(tokenize(f"{memory.title} {memory.summary} {memory.source_ref}"))
        overlap = len(task_tokens & source_tokens)
        score = float(overlap) + memory.confidence
        if any(active_file in memory.source_ref for active_file in active_files):
            score += 2.0
        ranked.append((score, memory.id))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [memory_id for score, memory_id in ranked if score > 0][:5]
