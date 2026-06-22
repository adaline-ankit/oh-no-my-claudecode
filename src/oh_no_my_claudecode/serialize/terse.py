"""Terse rendering utilities for agent-facing onmc output.

Terse mode emits only high-signal, relevant tokens — no section scaffolding,
no prose preamble.  It is the default for all hook-injected output
(prompt_recall, boot_digest) because those run on every prompt/session.

Gate priority (highest wins):
  ONMC_VERBOSE=1  → always full
  ONMC_TERSE=1    → always terse
  hooks           → terse by default (unless ONMC_VERBOSE=1)
  CLI commands    → full by default (unless ONMC_TERSE=1 or --terse)

Format compact lines:
  INVARIANT: <title> — <summary>
  FAILED(don't retry): <title> — <summary>
  FIX(worked): <title> — <summary>
  HOTSPOT: <title> — <summary>
  GOTCHA: <title> — <summary>
  DECISION: <title> — <summary>
  MEM: <title> — <summary>        (catch-all)
  TASK: <id> <title>
  PREF: <title> — <summary>
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, TaskRecord, TaskStatus

# Prefix labels per memory kind.
_KIND_PREFIX: dict[MemoryKind, str] = {
    MemoryKind.INVARIANT: "INVARIANT",
    MemoryKind.DECISION: "DECISION",
    MemoryKind.FAILED_APPROACH: "FAILED(don't retry)",
    MemoryKind.HOTSPOT: "HOTSPOT",
    MemoryKind.GOTCHA: "GOTCHA",
    MemoryKind.GIT_PATTERN: "GIT_PATTERN",
    MemoryKind.VALIDATION_RULE: "RULE",
    MemoryKind.DESIGN_CONFLICT: "CONFLICT",
    MemoryKind.DOC_FACT: "FACT",
}

# Max chars for summary in a terse line (hard truncation).
_TERSE_SUMMARY_CHARS = 120

# Max chars for the whole terse block (absolute ceiling).
_TERSE_BLOCK_CHARS = 800

# Max items to include in the terse block.
_TERSE_MAX_ITEMS = 5


def is_terse(*, default: bool = False) -> bool:
    """Return True when terse mode is active.

    Args:
        default: The fallback value when neither ONMC_TERSE nor ONMC_VERBOSE
            is set.  Hook paths pass ``default=True``; CLI commands pass
            ``default=False``.
    """
    if os.environ.get("ONMC_VERBOSE", "").strip() in {"1", "true", "yes"}:
        return False
    if os.environ.get("ONMC_TERSE", "").strip() in {"1", "true", "yes"}:
        return True
    return default


def _truncate(text: str, max_chars: int) -> str:
    """Hard-truncate *text* to *max_chars*, appending '…' when cut."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _kind_label(kind: MemoryKind) -> str:
    return _KIND_PREFIX.get(kind, "MEM")


def render_memories_terse(
    memories: list[MemoryEntry],
    *,
    max_items: int = _TERSE_MAX_ITEMS,
) -> str:
    """Render a list of memories as compact terse lines.

    Returns a newline-joined string (no trailing newline) or "" when empty.
    """
    if not memories:
        return ""
    lines: list[str] = []
    for memory in memories[:max_items]:
        label = _kind_label(memory.kind)
        summary = _truncate(memory.summary, _TERSE_SUMMARY_CHARS)
        lines.append(f"{label}: {memory.title} — {summary}")
    return "\n".join(lines)


def render_tasks_terse(
    tasks: list[TaskRecord],
    *,
    max_items: int = 2,
) -> str:
    """Render active tasks as compact terse lines."""
    active = [t for t in tasks if t.status == TaskStatus.ACTIVE]
    if not active:
        return ""
    lines: list[str] = []
    for task in active[:max_items]:
        title = _truncate(task.title, 60)
        lines.append(f"TASK: {task.task_id} {title}")
    return "\n".join(lines)


def render_boot_digest_terse(
    *,
    invariants: list[MemoryEntry],
    hotspots: list[MemoryEntry],
    active_tasks: list[TaskRecord],
    repo_name: str,
    prefs: list[MemoryEntry] | None = None,
    max_items_per_section: int = 3,
) -> str:
    """Render a boot digest in terse format.

    Returns the terse block string (no trailing newline) or "" when empty.
    """
    parts: list[str] = []

    if prefs:
        for m in prefs[:max_items_per_section]:
            parts.append(f"PREF: {_truncate(m.title, 60)} — {_truncate(m.summary, 100)}")

    if invariants:
        for m in invariants[:max_items_per_section]:
            parts.append(f"INVARIANT: {_truncate(m.title, 60)} — {_truncate(m.summary, 100)}")

    if hotspots:
        for m in hotspots[:max_items_per_section]:
            label = _kind_label(m.kind)
            parts.append(f"{label}: {_truncate(m.title, 60)} — {_truncate(m.summary, 100)}")

    if active_tasks:
        for t in active_tasks[:2]:
            parts.append(f"TASK: {t.task_id} {_truncate(t.title, 60)}")

    if not parts:
        return ""

    header = f"[onmc:{repo_name}]"
    body = "\n".join(parts)
    block = f"{header}\n{body}"
    return block[:_TERSE_BLOCK_CHARS]


def render_recall_terse(
    memories: list[MemoryEntry],
    *,
    max_items: int = _TERSE_MAX_ITEMS,
) -> str:
    """Render prompt-recall memories in terse format.

    Returns the terse block string (no trailing newline) or "" when empty.
    """
    if not memories:
        return ""
    lines: list[str] = []
    for memory in memories[:max_items]:
        label = _kind_label(memory.kind)
        summary = _truncate(memory.summary, _TERSE_SUMMARY_CHARS)
        lines.append(f"{label}: {memory.title} — {summary}")
    block = "\n".join(lines)
    return block[:_TERSE_BLOCK_CHARS]


def render_guard_terse(
    entries: Sequence[object],
    task: str,
    *,
    max_items: int = 5,
) -> str:
    """Render guard dead-ends in terse format.

    *entries* are ``GuardEntry`` dataclass instances — imported lazily to
    avoid circular deps.  We only access .title, .what_was_tried, .why_it_failed.
    """
    if not entries:
        return f"GUARD: no dead-ends for: {_truncate(task, 60)}"
    lines: list[str] = [f"GUARD(don't retry these for: {_truncate(task, 60)}):"]
    for entry in entries[:max_items]:
        tried = _truncate(str(getattr(entry, "what_was_tried", "")), 80)
        lines.append(f"  FAILED(don't retry): {getattr(entry, 'title', '')} — {tried}")
    return "\n".join(lines)


def render_why_terse(report: object) -> str:
    """Render a WhyReport in terse format.

    Accesses WhyReport fields via getattr to avoid circular imports.
    """
    path = str(getattr(report, "path", "?"))
    verdict = str(getattr(report, "risk_verdict", "unknown"))
    lines: list[str] = [f"WHY:{path} verdict={verdict}"]

    decisions: list[MemoryEntry] = list(getattr(report, "decisions", []))
    failed: list[MemoryEntry] = list(getattr(report, "failed_approaches", []))
    hotspots: list[MemoryEntry] = list(getattr(report, "hotspot_memories", []))

    for m in decisions[:2]:
        lines.append(f"  DECISION: {_truncate(m.title, 60)} — {_truncate(m.summary, 80)}")
    for m in failed[:2]:
        lines.append(
            f"  FAILED(don't retry): {_truncate(m.title, 60)} — {_truncate(m.summary, 80)}"
        )
    for m in hotspots[:2]:
        lines.append(f"  HOTSPOT: {_truncate(m.title, 60)} — {_truncate(m.summary, 80)}")

    git_history = getattr(report, "git_history", None)
    if git_history is not None:
        commits = getattr(git_history, "commit_count", 0)
        if commits:
            lines.append(f"  GIT: {commits} commits")

    return "\n".join(lines)


def render_incident_recall_terse(
    entries: Sequence[object],
    query: str,
    *,
    max_items: int = 5,
) -> str:
    """Render incident-recall entries in terse format.

    *entries* are ``RecallEntry`` dataclass instances — imported lazily to
    avoid circular deps.  We access .title, .what_happened, .resolution.
    """
    if not entries:
        return f"RECALL: no prior incidents match: {_truncate(query, 60)}"
    lines: list[str] = [f"RECALL(seen before, for: {_truncate(query, 60)}):"]
    for entry in entries[:max_items]:
        resolution = _truncate(str(getattr(entry, "resolution", "")), 80)
        lines.append(f"  PRIOR: {getattr(entry, 'title', '')} — FIX: {resolution}")
    return "\n".join(lines)


# LLM prompt directive: prepend to any LLM call made in terse paths.
TERSE_LLM_DIRECTIVE = (
    "Respond in terse fragments only. No preamble, no explanation, no filler. "
    "Only repo-relevant facts. Use < 30 words total."
)
