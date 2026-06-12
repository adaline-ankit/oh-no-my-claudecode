from __future__ import annotations

import secrets
from pathlib import Path

from oh_no_my_claudecode.mine.transcript import parse_assistant_turns
from oh_no_my_claudecode.models import (
    AttemptRecord,
    CompactionSnapshotRecord,
    MemoryArtifactRecord,
    MemoryEntry,
    MemoryKind,
    TaskOutputRecord,
    TaskRecord,
)
from oh_no_my_claudecode.utils.text import shorten, tokenize, unique_preserve
from oh_no_my_claudecode.utils.time import utc_now

# Lines opening with these markers in the latest assistant text are treated as
# the in-flight next step when no onmc task records exist. Deliberately simple:
# the hook path must be fast and offline (no LLM call).
_NEXT_STEP_MARKERS = (
    "next",
    "todo",
    "then ",
    "now ",
    "remaining",
    "i'll ",
    "i will ",
    "let me ",
)


def build_compaction_snapshot(
    *,
    task: TaskRecord | None,
    attempts: list[AttemptRecord],
    artifacts: list[MemoryArtifactRecord],
    outputs: list[TaskOutputRecord],
    memories: list[MemoryEntry],
    transcript_path: Path | None = None,
    repo_root: Path | None = None,
) -> CompactionSnapshotRecord:
    """Build a compaction snapshot from task-scoped state and the live transcript.

    Task/attempt records are the primary source. When the PreCompact hook
    payload provides a ``transcript_path``, assistant turns are parsed from the
    actual Claude Code session transcript to enrich the snapshot:

    - transcript-touched files are merged ahead of task-derived files, and
    - when task records are absent, ``working_hypothesis`` and ``next_step``
      are derived heuristically from the tail of the latest assistant text
      (last paragraph; a trailing line starting with a marker like "next"/
      "todo"/"let me" wins for the next step, else the final line is used).
    """
    transcript_text, transcript_files = _transcript_context(transcript_path, repo_root)
    active_files = _active_files(
        attempts=attempts,
        artifacts=artifacts,
        transcript_files=transcript_files,
    )
    recent_decisions = _recent_decisions(task=task, active_files=active_files, memories=memories)
    latest_attempt = attempts[0] if attempts else None
    latest_output = outputs[0] if outputs else None
    assistant_tail = _assistant_tail(transcript_text)
    working_hypothesis = (
        latest_attempt.reasoning_summary
        if latest_attempt and latest_attempt.reasoning_summary
        else (latest_attempt.summary if latest_attempt else None)
    )
    if working_hypothesis is None and assistant_tail:
        working_hypothesis = shorten(assistant_tail, max_length=180)
    next_step = latest_output.summary if latest_output else None
    if next_step is None and assistant_tail:
        next_step = _derive_next_step(assistant_tail) or None
    return CompactionSnapshotRecord(
        id=f"snapshot-{secrets.token_hex(4)}",
        task_id=task.task_id if task else None,
        timestamp=utc_now(),
        active_files=active_files,
        recent_decisions=recent_decisions,
        working_hypothesis=working_hypothesis,
        last_error_trace=latest_attempt.evidence_against if latest_attempt else None,
        next_step=next_step,
        brief_token_count=None,
        continuation_brief_md=None,
    )


def _transcript_context(
    transcript_path: Path | None,
    repo_root: Path | None,
) -> tuple[str, list[str]]:
    """Parse the session transcript, returning ("", []) on any read failure."""
    if transcript_path is None:
        return "", []
    try:
        return parse_assistant_turns(transcript_path, repo_root=repo_root)
    except (OSError, ValueError):
        return "", []


def _assistant_tail(transcript_text: str) -> str:
    """Return the last non-empty paragraph of the parsed assistant text."""
    paragraphs = [part.strip() for part in transcript_text.split("\n\n") if part.strip()]
    return paragraphs[-1] if paragraphs else ""


def _derive_next_step(assistant_tail: str) -> str:
    """Pick the most next-step-like trailing line from the assistant tail."""
    lines = [line.strip() for line in assistant_tail.splitlines() if line.strip()]
    if not lines:
        return ""
    for line in reversed(lines):
        stripped = line.lstrip("-*#0123456789. ").strip()
        if stripped.lower().startswith(_NEXT_STEP_MARKERS):
            return shorten(stripped, max_length=160)
    return shorten(lines[-1], max_length=160)


def _active_files(
    *,
    attempts: list[AttemptRecord],
    artifacts: list[MemoryArtifactRecord],
    transcript_files: list[str],
) -> list[str]:
    files: list[str] = list(transcript_files)
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
