"""Guard compiler — retrieve and rank recorded dead-ends for a given task.

The guard surfaces ``FAILED_APPROACH`` memories and ``did_not_work``
memory artifacts so that coding agents can avoid repeating known failures.

Ranking strategy
----------------
1. FTS5 candidate retrieval (broad recall) filtered to ``FAILED_APPROACH`` kind.
2. ``did_not_work`` memory artifacts from the same candidate set.
3. Token-overlap score against the task query (same formula as prompt_recall).
4. Staleness penalty: stale/orphaned/unanchored memories are weighted at 0.35×.
5. Confidence + feedback_score incorporated additively.
6. Top *limit* entries returned, deduplicated by memory id.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from oh_no_my_claudecode.models import MemoryArtifactType, MemoryEntry, MemoryKind
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import tokenize

# Staleness labels that incur a penalty (same as prompt_recall).
_STALE_LABELS = frozenset({"stale", "orphaned", "unanchored"})
_STALE_WEIGHT = 0.35

# Minimum relevance score to include an entry (avoids zero-overlap noise).
_MIN_SCORE = 0.1

# FTS retrieval multiplier — fetch more candidates than needed so the
# token-overlap reranker has enough material to work with.
_FTS_MULTIPLIER = 4


@dataclass
class GuardEntry:
    """One recorded dead-end that an agent should not retry."""

    memory_id: str
    title: str
    what_was_tried: str  # memory summary
    why_it_failed: str  # evidence_against from artifact, else memory details
    related_files: list[str]
    source_ref: str
    confidence: float
    score: float  # internal ranking score (not exposed to callers verbatim)


@dataclass
class GuardResult:
    """Ranked list of dead-ends for a task query."""

    task: str
    entries: list[GuardEntry] = field(default_factory=list)

    @property
    def has_dead_ends(self) -> bool:
        return len(self.entries) > 0

    def to_markdown(self) -> str:
        """Render the guard result as a markdown "DO NOT retry" panel."""
        if not self.has_dead_ends:
            return (
                f"## Guard: no recorded dead-ends for task\n\n"
                f"> Task: {self.task}\n\n"
                "No `failed_approach` memories match this task. Proceed without constraint.\n"
            )

        lines: list[str] = [
            "## Guard: DO NOT retry these recorded dead-ends",
            "",
            f"> Task: {self.task}",
            "",
        ]
        for i, entry in enumerate(self.entries, 1):
            lines.append(f"### {i}. {entry.title}")
            lines.append("")
            lines.append(f"**What was tried:** {entry.what_was_tried}")
            lines.append("")
            lines.append(f"**Why it failed:** {entry.why_it_failed}")
            if entry.related_files:
                lines.append("")
                files_str = ", ".join(f"`{f}`" for f in entry.related_files[:5])
                lines.append(f"**Related files:** {files_str}")
            lines.append("")
            lines.append(
                f"_Source: `{entry.source_ref}` | confidence: {entry.confidence:.2f}_"
            )
            lines.append("")

        return "\n".join(lines)


def _score(memory: MemoryEntry, query_tokens: set[str]) -> float:
    """Relevance score for one memory against query tokens.

    Excluded (returns 0.0):
    - feedback_score <= -0.5 (explicitly rejected by human)
    - confidence <= 0.0
    """
    if memory.feedback_score <= -0.5:
        return 0.0
    if memory.confidence <= 0.0:
        return 0.0

    haystack = " ".join(
        [
            memory.title,
            memory.summary,
            memory.details,
            memory.source_ref,
            " ".join(memory.tags),
        ]
    )
    haystack_tokens = set(tokenize(haystack))
    overlap = query_tokens & haystack_tokens

    raw = float(len(overlap) * 3) + memory.confidence + (memory.feedback_score * 0.2)

    if memory.staleness in _STALE_LABELS:
        return raw * _STALE_WEIGHT

    return raw


def compile_guard(
    storage: SQLiteStorage,
    task: str,
    *,
    limit: int = 8,
) -> GuardResult:
    """Retrieve and rank dead-ends relevant to *task*.

    Args:
        storage: Initialised SQLiteStorage instance.
        task: Free-text task description (used as the search query).
        limit: Maximum number of dead-end entries to return.

    Returns:
        A ``GuardResult`` with zero or more ranked ``GuardEntry`` items.
        Returns an empty result (``has_dead_ends=False``) when no relevant
        failed approaches are found — callers must not treat this as an error.
    """
    if not task or not task.strip():
        return GuardResult(task=task)

    # Step 1 — FTS5 candidate retrieval filtered to FAILED_APPROACH kind.
    try:
        fts_candidates = storage.search_memories(
            query=task,
            kind=MemoryKind.FAILED_APPROACH,
            limit=limit * _FTS_MULTIPLIER,
        )
    except Exception:  # noqa: BLE001
        fts_candidates = []

    # Fall back to listing all FAILED_APPROACH memories if FTS returned nothing.
    if not fts_candidates:
        try:
            fts_candidates = storage.list_memories(kind=MemoryKind.FAILED_APPROACH)
        except Exception:  # noqa: BLE001
            return GuardResult(task=task)

    # Step 2 — Load did_not_work artifacts for the candidate set (by memory id).
    candidate_ids = {m.id for m in fts_candidates}
    artifact_index: dict[str, str] = {}  # memory_id -> evidence text
    artifact_files: dict[str, list[str]] = {}  # memory_id -> related_files
    try:
        dnw_artifacts = storage.list_memory_artifacts(
            artifact_type=MemoryArtifactType.DID_NOT_WORK
        )
        for artifact in dnw_artifacts:
            if artifact.memory_id in candidate_ids:
                artifact_index[artifact.memory_id] = artifact.evidence or artifact.summary
                artifact_files[artifact.memory_id] = list(artifact.related_files)
    except Exception:  # noqa: BLE001, S110
        pass  # artifact retrieval failure must not break guard

    # Step 3 — Token-overlap reranking with staleness penalty.
    query_tokens = set(tokenize(task))
    if not query_tokens:
        return GuardResult(task=task)

    scored: list[tuple[float, MemoryEntry]] = []
    seen: set[str] = set()
    for memory in fts_candidates:
        if memory.id in seen:
            continue
        seen.add(memory.id)
        s = _score(memory, query_tokens)
        if s >= _MIN_SCORE:
            scored.append((s, memory))

    scored.sort(key=lambda item: (-item[0], item[1].title))
    top = scored[:limit]

    if not top:
        return GuardResult(task=task)

    # Step 4 — Build GuardEntry items.
    entries: list[GuardEntry] = []
    for s, memory in top:
        why_it_failed = artifact_index.get(memory.id) or memory.details or memory.summary
        related_files = artifact_files.get(memory.id, [])
        entries.append(
            GuardEntry(
                memory_id=memory.id,
                title=memory.title,
                what_was_tried=memory.summary,
                why_it_failed=why_it_failed,
                related_files=related_files,
                source_ref=memory.source_ref,
                confidence=memory.confidence,
                score=s,
            )
        )

    return GuardResult(task=task, entries=entries)
