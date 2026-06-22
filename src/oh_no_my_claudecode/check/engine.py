"""Offline check engine: flag staged/changed files that carry INVARIANT or dead-end memory.

This module is deliberately free of side-effects:
- No LLM calls, no network, no git subprocess inside ``run_check`` itself.
- All git interaction is handled by the caller (CLI) and the result passed as
  a plain list of repo-relative path strings.
- All storage interaction is read-only.

CheckResult shape:
  findings: list[CheckFinding]   — one entry per (file, memory) pair
  warn_count: int                — number of warn-severity findings
  info_count: int                — number of info-severity findings
  has_warnings: bool             — True when warn_count > 0

CheckFinding shape:
  rel_path: str
  severity: CheckSeverity        — "warn" or "info"
  kind: str                      — memory kind value (e.g. "invariant")
  memory_id: str
  title: str
  summary: str
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from oh_no_my_claudecode.models.memory import MemoryKind
from oh_no_my_claudecode.models.memory_artifact import MemoryArtifactRecord, MemoryArtifactType
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.why.compiler import (  # noqa: PLC2701
    _memory_references_path,
    _normalize_path,
)

# Memory kinds that are hard-blockers — surface as "warn" severity.
_WARN_KINDS: frozenset[MemoryKind] = frozenset(
    {MemoryKind.INVARIANT, MemoryKind.FAILED_APPROACH}
)

# Memory kinds that are informational — surface as "info" severity.
_INFO_KINDS: frozenset[MemoryKind] = frozenset(
    {
        MemoryKind.HOTSPOT,
        MemoryKind.GIT_PATTERN,
        MemoryKind.GOTCHA,
        MemoryKind.VALIDATION_RULE,
        MemoryKind.DESIGN_CONFLICT,
        MemoryKind.DECISION,
        MemoryKind.DOC_FACT,
    }
)

# Artifact types that represent dead-ends — surface as "warn" severity.
_WARN_ARTIFACT_TYPES: frozenset[MemoryArtifactType] = frozenset(
    {MemoryArtifactType.DID_NOT_WORK}
)


class CheckSeverity(StrEnum):
    WARN = "warn"
    INFO = "info"


@dataclass
class CheckFinding:
    """A single memory-backed finding for one changed file."""

    rel_path: str
    severity: CheckSeverity
    kind: str
    memory_id: str
    title: str
    summary: str


@dataclass
class CheckResult:
    """Aggregated result from ``run_check``."""

    findings: list[CheckFinding] = field(default_factory=list)

    @property
    def warn_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == CheckSeverity.WARN)

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == CheckSeverity.INFO)

    @property
    def has_warnings(self) -> bool:
        return self.warn_count > 0

    def findings_for(self, rel_path: str) -> list[CheckFinding]:
        return [f for f in self.findings if f.rel_path == rel_path]


def run_check(
    repo_root: Path,
    storage: SQLiteStorage,
    files: list[str],
) -> CheckResult:
    """Check *files* against stored memories and return a :class:`CheckResult`.

    Parameters
    ----------
    repo_root:
        Absolute path to the repo root.  Used for path normalisation only.
    storage:
        Initialized :class:`SQLiteStorage`.  Only read operations are performed.
    files:
        Repo-relative or absolute paths to check (e.g. from ``git diff --cached
        --name-only``).  Absolute paths are normalised to repo-relative form.

    Returns
    -------
    CheckResult
        A deterministic, offline result.  The caller decides whether to block
        (``--strict``) or warn only.
    """
    if not files:
        return CheckResult()

    memories = storage.list_memories()
    artifacts = storage.list_memory_artifacts()

    # Normalise all paths to repo-relative POSIX strings.
    rel_paths: list[str] = [_normalize_path(repo_root, f) for f in files]

    # Build a quick lookup: memory_id -> list[MemoryArtifactRecord] for
    # DID_NOT_WORK artifacts so we can enrich the finding summary.
    dead_end_artifacts_by_memory: dict[str, list[MemoryArtifactRecord]] = {}
    for artifact in artifacts:
        if artifact.type in _WARN_ARTIFACT_TYPES:
            dead_end_artifacts_by_memory.setdefault(artifact.memory_id, []).append(artifact)

    findings: list[CheckFinding] = []

    for rel_path in rel_paths:
        # Deduplicate: only one finding per (file, memory_id) pair.
        seen_memory_ids: set[str] = set()

        for memory in memories:
            if memory.id in seen_memory_ids:
                continue
            if not _memory_references_path(memory, rel_path):
                continue

            if memory.kind in _WARN_KINDS:
                severity = CheckSeverity.WARN
            elif memory.kind in _INFO_KINDS:
                severity = CheckSeverity.INFO
            else:
                # Unknown/future kind — surface as info so we don't miss it.
                severity = CheckSeverity.INFO

            # Enrich summary with dead-end artifact evidence when available.
            summary = memory.summary
            if memory.kind == MemoryKind.FAILED_APPROACH:
                dnw = dead_end_artifacts_by_memory.get(memory.id, [])
                if dnw:
                    evidence_snippet = dnw[0].evidence[:120]
                    summary = f"{summary} | Evidence: {evidence_snippet}"

            findings.append(
                CheckFinding(
                    rel_path=rel_path,
                    severity=severity,
                    kind=memory.kind.value,
                    memory_id=memory.id,
                    title=memory.title,
                    summary=summary,
                )
            )
            seen_memory_ids.add(memory.id)

        # Also surface dead-end artifacts that directly reference this file via
        # related_files — even when the parent memory may not textually mention
        # the path (e.g. the path was recorded as a related_file, not in summary).
        for artifact in artifacts:
            if artifact.type not in _WARN_ARTIFACT_TYPES:
                continue
            # Avoid duplicates: if we already surfaced the parent memory, skip.
            if artifact.memory_id in seen_memory_ids:
                continue
            file_refs: list[str] = artifact.related_files or []
            base = Path(rel_path).name
            if any(rel_path in ref or base in ref or ref in rel_path for ref in file_refs):
                findings.append(
                    CheckFinding(
                        rel_path=rel_path,
                        severity=CheckSeverity.WARN,
                        kind=MemoryArtifactType.DID_NOT_WORK.value,
                        memory_id=artifact.memory_id,
                        title=artifact.title,
                        summary=artifact.evidence[:200],
                    )
                )
                seen_memory_ids.add(artifact.memory_id)

    return CheckResult(findings=findings)
