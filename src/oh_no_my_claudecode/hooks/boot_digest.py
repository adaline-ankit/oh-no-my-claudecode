from __future__ import annotations

from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, TaskRecord, TaskStatus
from oh_no_my_claudecode.utils.text import shorten, tokenize

# Maximum token budget for the entire boot digest.
BOOT_DIGEST_MAX_TOKENS = 400

# How many entries to include per high-signal section.
_MAX_INVARIANTS = 3
_MAX_HOTSPOTS = 3
_MAX_ACTIVE_TASKS = 2


def compile_boot_digest(
    *,
    memories: list[MemoryEntry],
    tasks: list[TaskRecord],
    repo_name: str,
) -> tuple[str, int]:
    """Compile a compact boot digest from repo memory for session startup injection.

    The digest is intentionally small (≤ ~400 tokens) so it is a helpful reminder
    rather than a full brief. It is emitted on every session start (startup / resume /
    clear) so agents always boot with the repo brain.

    Returns ``(markdown, token_count)``. When there is nothing to say (empty
    memories and no active tasks) the function returns ``("", 0)`` so callers can
    skip injection entirely.
    """
    invariants = _select_kind(
        memories, {MemoryKind.INVARIANT, MemoryKind.DECISION, MemoryKind.VALIDATION_RULE}
    )
    hotspots = _select_kind(
        memories, {MemoryKind.HOTSPOT, MemoryKind.GOTCHA, MemoryKind.FAILED_APPROACH}
    )
    active_tasks = [t for t in tasks if t.status == TaskStatus.ACTIVE]

    if not invariants and not hotspots and not active_tasks:
        return "", 0

    lines: list[str] = [f"## Repo brain: {repo_name}", ""]

    if invariants:
        lines.append("### Key invariants & decisions")
        for memory in invariants[:_MAX_INVARIANTS]:
            lines.append(f"- **{memory.title}**: {shorten(memory.summary, max_length=120)}")
        lines.append("")

    if hotspots:
        lines.append("### Hotspots & gotchas")
        for memory in hotspots[:_MAX_HOTSPOTS]:
            lines.append(f"- **{memory.title}**: {shorten(memory.summary, max_length=120)}")
        lines.append("")

    if active_tasks:
        lines.append("### Active tasks")
        for task in active_tasks[:_MAX_ACTIVE_TASKS]:
            lines.append(f"- `{task.task_id}` {shorten(task.title, max_length=80)}")
        lines.append("")

    markdown = "\n".join(lines).rstrip() + "\n"
    token_count = len(tokenize(markdown))

    if token_count <= BOOT_DIGEST_MAX_TOKENS:
        return markdown, token_count

    # Trim to fit the token budget.
    markdown = _trim_boot_digest(
        invariants=invariants,
        hotspots=hotspots,
        active_tasks=active_tasks,
        repo_name=repo_name,
    )
    return markdown, len(tokenize(markdown))


def _select_kind(memories: list[MemoryEntry], kinds: set[MemoryKind]) -> list[MemoryEntry]:
    """Return memories of the given kinds, sorted by confidence descending."""
    selected = [m for m in memories if m.kind in kinds and m.feedback_score > -0.5]
    selected.sort(key=lambda m: (-m.confidence, m.title))
    return selected


def _trim_boot_digest(
    *,
    invariants: list[MemoryEntry],
    hotspots: list[MemoryEntry],
    active_tasks: list[TaskRecord],
    repo_name: str,
) -> str:
    """Produce a hard-trimmed version that fits within the token budget."""
    lines: list[str] = [f"## Repo brain: {repo_name}", ""]

    if invariants:
        lines.append("### Key invariants & decisions")
        for memory in invariants[:2]:
            lines.append(f"- **{memory.title}**: {shorten(memory.summary, max_length=80)}")
        lines.append("")

    if hotspots:
        lines.append("### Hotspots & gotchas")
        for memory in hotspots[:2]:
            lines.append(f"- **{memory.title}**: {shorten(memory.summary, max_length=80)}")
        lines.append("")

    if active_tasks:
        lines.append("### Active tasks")
        task = active_tasks[0]
        lines.append(f"- `{task.task_id}` {shorten(task.title, max_length=60)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
