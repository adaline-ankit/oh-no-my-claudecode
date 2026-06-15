from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.models import FileStat, MemoryArtifactRecord, MemoryEntry, MemoryKind
from oh_no_my_claudecode.storage import SQLiteStorage

# Memory kinds considered "why it looks this way"
_DECISION_KINDS = {MemoryKind.DECISION, MemoryKind.INVARIANT}
# Memory kinds considered "what was tried and failed"
_FAILED_KINDS = {MemoryKind.FAILED_APPROACH}
# Memory kinds considered "dangerous to change because"
_RISK_KINDS = {MemoryKind.HOTSPOT, MemoryKind.GIT_PATTERN}
# Memory kinds considered "related context"
_CONTEXT_KINDS = {MemoryKind.GOTCHA, MemoryKind.VALIDATION_RULE, MemoryKind.DESIGN_CONFLICT}

# Commit subject max length for display
_MAX_SUBJECT_LEN = 72
# Maximum recent commit subjects to surface
_MAX_RECENT_SUBJECTS = 5
# Churn threshold for "high-churn hotspot" verdict
_HIGH_CHURN_THRESHOLD = 3


@dataclass
class GitHistory:
    """Lightweight git history for a single file path."""

    commit_count: int
    recent_subjects: list[str] = field(default_factory=list)


@dataclass
class WhyReport:
    """Structured result of `onmc why <path>`."""

    path: str
    risk_verdict: str  # e.g. "high-churn hotspot" or "stable"

    # Section: why it looks this way (decisions + invariants)
    decisions: list[MemoryEntry] = field(default_factory=list)

    # Section: what was tried and failed
    failed_approaches: list[MemoryEntry] = field(default_factory=list)

    # Section: dangerous to change because
    hotspot_memories: list[MemoryEntry] = field(default_factory=list)
    file_stat: FileStat | None = None

    # Section: related context
    context_memories: list[MemoryEntry] = field(default_factory=list)
    related_artifacts: list[MemoryArtifactRecord] = field(default_factory=list)

    # Git history surface
    git_history: GitHistory | None = None

    # Whether the store has any data at all for this path
    has_data: bool = False

    # Optional LLM-generated narrative paragraph (empty string = not generated)
    llm_narrative: str = ""

    # Path to the written markdown artifact
    output_path: str = ""


def _normalize_path(repo_root: Path, raw_path: str) -> str:
    """Return a repo-relative path string regardless of whether input is absolute or relative."""
    candidate = Path(raw_path)
    if candidate.is_absolute():
        try:
            return candidate.relative_to(repo_root).as_posix()
        except ValueError:
            return raw_path
    return Path(raw_path).as_posix()


def _matches_path(text: str, rel_path: str) -> bool:
    """Return True if ``text`` plausibly references ``rel_path``."""
    if not text:
        return False
    # Direct substring match or basename match
    base = Path(rel_path).name
    return rel_path in text or base in text


def _memory_references_path(memory: MemoryEntry, rel_path: str) -> bool:
    """Return True if this memory entry is related to the given path."""
    return any(
        _matches_path(field, rel_path)
        for field in (memory.source_ref, memory.title, memory.summary, memory.details)
    )


def _artifact_references_path(artifact: MemoryArtifactRecord, rel_path: str) -> bool:
    """Return True if this artifact is related to the given path."""
    base = Path(rel_path).name
    return any(
        rel_path in f or base in f or f in rel_path for f in artifact.related_files
    )


def _fetch_git_history(repo_root: Path, rel_path: str) -> GitHistory | None:
    """Shell out to git log for the given repo-relative path."""
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--follow",
                "--oneline",
                "--",
                rel_path,
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    if not lines:
        return None

    subjects: list[str] = []
    for line in lines[:_MAX_RECENT_SUBJECTS]:
        # strip the short hash prefix
        parts = line.split(" ", 1)
        subject = parts[1] if len(parts) == 2 else line
        subject = subject[:_MAX_SUBJECT_LEN]
        subjects.append(subject)

    return GitHistory(commit_count=len(lines), recent_subjects=subjects)


def _safe_filename(path: str) -> str:
    """Convert a repo-relative path to a filesystem-safe name."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", path)


def compile_why(
    repo_root: Path,
    storage: SQLiteStorage,
    raw_path: str,
) -> WhyReport:
    """Assemble a WhyReport for *raw_path* from existing store + git history.

    This is entirely offline — no LLM calls, no network.  The optional LLM
    narrative layer is handled by the caller (service / CLI) so the core stays
    deterministic and testable.
    """
    rel_path = _normalize_path(repo_root, raw_path)

    memories = storage.list_memories()
    file_stats = storage.list_file_stats()
    artifacts = storage.list_memory_artifacts()

    # ── file stat ──────────────────────────────────────────────────────────
    file_stat: FileStat | None = next(
        (s for s in file_stats if s.path == rel_path), None
    )

    # ── partition memories by kind & relevance ────────────────────────────
    decisions: list[MemoryEntry] = []
    failed_approaches: list[MemoryEntry] = []
    hotspot_memories: list[MemoryEntry] = []
    context_memories: list[MemoryEntry] = []

    for memory in memories:
        if not _memory_references_path(memory, rel_path):
            continue
        if memory.kind in _DECISION_KINDS:
            decisions.append(memory)
        elif memory.kind in _FAILED_KINDS:
            failed_approaches.append(memory)
        elif memory.kind in _RISK_KINDS:
            hotspot_memories.append(memory)
        elif memory.kind in _CONTEXT_KINDS:
            context_memories.append(memory)
        # DOC_FACT goes into context too
        else:
            context_memories.append(memory)

    # ── related artifacts ─────────────────────────────────────────────────
    related_artifacts = [a for a in artifacts if _artifact_references_path(a, rel_path)]

    # ── git history ───────────────────────────────────────────────────────
    git_history = _fetch_git_history(repo_root, rel_path)

    # ── risk verdict ──────────────────────────────────────────────────────
    churn = file_stat.change_count if file_stat else 0
    recent_churn = file_stat.recent_change_count if file_stat else 0
    if churn >= _HIGH_CHURN_THRESHOLD or recent_churn >= 2:
        risk_verdict = "high-churn hotspot"
    elif hotspot_memories:
        risk_verdict = "flagged as hotspot"
    else:
        risk_verdict = "stable"

    has_data = bool(
        decisions
        or failed_approaches
        or hotspot_memories
        or context_memories
        or related_artifacts
        or (git_history and git_history.commit_count > 0)
        or file_stat is not None
    )

    return WhyReport(
        path=rel_path,
        risk_verdict=risk_verdict,
        decisions=decisions,
        failed_approaches=failed_approaches,
        hotspot_memories=hotspot_memories,
        file_stat=file_stat,
        context_memories=context_memories,
        related_artifacts=related_artifacts,
        git_history=git_history,
        has_data=has_data,
    )


def why_report_to_markdown(report: WhyReport) -> str:
    """Render a WhyReport as a markdown string."""
    lines: list[str] = []
    lines.append(f"# Why does `{report.path}` look this way?")
    lines.append("")
    lines.append(f"**Risk verdict:** {report.risk_verdict}")
    lines.append("")

    if report.llm_narrative:
        lines.append(report.llm_narrative)
        lines.append("")

    if not report.has_data:
        lines.append(
            "> Nothing is known about this file yet.  "
            "Run `onmc ingest` to index git history and docs, "
            "then `onmc mine` to extract memories from session transcripts."
        )
        return "\n".join(lines)

    # ── Why it looks this way ─────────────────────────────────────────────
    if report.decisions:
        lines.append("## Why it looks this way")
        lines.append("")
        for memory in report.decisions:
            lines.append(f"### {memory.title}")
            lines.append(memory.summary)
            if memory.details and memory.details != memory.summary:
                lines.append("")
                lines.append(memory.details)
            lines.append("")

    # ── What was tried and failed ─────────────────────────────────────────
    if report.failed_approaches:
        lines.append("## What was tried and failed")
        lines.append("")
        for memory in report.failed_approaches:
            lines.append(f"### {memory.title}")
            lines.append(memory.summary)
            if memory.details and memory.details != memory.summary:
                lines.append("")
                lines.append(memory.details)
            lines.append("")

    # ── Dangerous to change because ───────────────────────────────────────
    danger_lines: list[str] = []
    if report.hotspot_memories:
        for memory in report.hotspot_memories:
            danger_lines.append(f"- **{memory.title}**: {memory.summary}")
    if report.file_stat and report.file_stat.change_count > 0:
        danger_lines.append(
            f"- **Churn**: {report.file_stat.change_count} modifying commits analyzed; "
            f"{report.file_stat.recent_change_count} in the last 30 days."
        )
    if report.git_history and report.git_history.commit_count > 0:
        danger_lines.append(
            f"- **Git history**: {report.git_history.commit_count} commits touch this file."
        )
    if danger_lines:
        lines.append("## Dangerous to change because")
        lines.append("")
        lines.extend(danger_lines)
        lines.append("")

    # ── Related context ───────────────────────────────────────────────────
    if report.context_memories or report.related_artifacts:
        lines.append("## Related context")
        lines.append("")
        for memory in report.context_memories:
            lines.append(f"- **{memory.title}** ({memory.kind.value}): {memory.summary}")
        for artifact in report.related_artifacts:
            lines.append(
                f"- **[artifact/{artifact.type.value}]** {artifact.title}: {artifact.summary}"
            )
        lines.append("")

    # ── Recent commits ────────────────────────────────────────────────────
    if report.git_history and report.git_history.recent_subjects:
        lines.append("## Recent commits")
        lines.append("")
        for subject in report.git_history.recent_subjects:
            lines.append(f"- {subject}")
        lines.append("")

    return "\n".join(lines)
