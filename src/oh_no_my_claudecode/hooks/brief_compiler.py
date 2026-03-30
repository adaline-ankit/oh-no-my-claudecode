from __future__ import annotations

from oh_no_my_claudecode.models import CompactionSnapshotRecord, MemoryEntry, TaskRecord
from oh_no_my_claudecode.utils.text import shorten, tokenize


def compile_continuation_brief(
    *,
    snapshot: CompactionSnapshotRecord,
    task: TaskRecord | None,
    decisions: list[MemoryEntry],
) -> tuple[str, int]:
    """Compile a compact continuation brief from the latest snapshot state."""
    lines = [
        "## Where we are",
        _where_we_are(task=task, snapshot=snapshot),
        "",
        "## What was just decided",
        _what_was_decided(decisions),
        "",
        "## What was being attempted",
        _what_was_being_attempted(snapshot),
        "",
        "## Next step",
        _next_step(snapshot),
        "",
    ]
    markdown = "\n".join(lines)
    token_count = len(tokenize(markdown))
    if token_count <= 400:
        return markdown, token_count

    trimmed = "\n".join(
        [
            "## Where we are",
            shorten(_where_we_are(task=task, snapshot=snapshot), max_length=180),
            "",
            "## What was just decided",
            shorten(_what_was_decided(decisions), max_length=220),
            "",
            "## What was being attempted",
            shorten(_what_was_being_attempted(snapshot), max_length=160),
            "",
            "## Next step",
            shorten(_next_step(snapshot), max_length=140),
            "",
        ]
    )
    return trimmed, len(tokenize(trimmed))


def _where_we_are(*, task: TaskRecord | None, snapshot: CompactionSnapshotRecord) -> str:
    if task is None:
        return "Active task context is unavailable."
    progress = (
        snapshot.next_step
        or snapshot.working_hypothesis
        or "Recent progress is unavailable."
    )
    return shorten(
        (
            f"The active task is {task.title}. "
            f"Last confirmed progress: {progress}"
        ),
        max_length=220,
    )


def _what_was_decided(decisions: list[MemoryEntry]) -> str:
    if not decisions:
        return "- unavailable."
    lines = []
    for memory in decisions[:5]:
        lines.append(f"- {memory.title}: {shorten(memory.summary, max_length=120)}")
    return "\n".join(lines)


def _what_was_being_attempted(snapshot: CompactionSnapshotRecord) -> str:
    if snapshot.working_hypothesis:
        return shorten(snapshot.working_hypothesis, max_length=180)
    if snapshot.last_error_trace:
        return shorten(snapshot.last_error_trace, max_length=180)
    return "The working hypothesis was unavailable."


def _next_step(snapshot: CompactionSnapshotRecord) -> str:
    if snapshot.next_step:
        return shorten(snapshot.next_step, max_length=160)
    if snapshot.active_files:
        return f"Re-open {snapshot.active_files[0]} and resume from the last recorded task state."
    return "Next step unavailable."
