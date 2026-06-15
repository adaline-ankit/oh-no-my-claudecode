"""Memory consolidation — deterministic, offline "dreaming" pass.

Inspired by hippocampal-replay memory consolidation: after a session, the
system replays existing memories, detects redundancies and contradictions,
and strengthens high-signal entries while retiring noise.

No LLM is required.  All heuristics are documented below so callers can
reason about them and tests can assert on them precisely.

Heuristics
----------
DEDUP / DUPLICATE_OF
    Two memories are near-duplicates when:
    - Same ``kind``.
    - Token-overlap (Jaccard) on ``title + summary + details`` >= 0.55.
    OR
    - Same ``source_ref`` AND ``kind``, AND at least one non-trivial token in
      common across their summaries.

    The survivor is the one with higher ``confidence + feedback_score * 0.5``.
    On a tie the lexicographically smaller ``id`` wins (deterministic).
    Protected MANUAL/MANUAL_SEED memories can be the *survivor* but are never
    retired — a DUPLICATE_OF edge is still written; the non-protected copy is
    the one retired.

MERGE
    When a duplicate pair is found, the survivor's confidence is raised to
    ``max(survivor.confidence, duplicate.confidence)`` and its feedback_score
    to ``survivor.feedback_score + duplicate.feedback_score`` (clamped to 1.0).

PROMOTE / DEMOTE
    Promote: bump confidence by 0.05 (capped 1.0) for memories with
    ``feedback_score >= 0.3`` and current confidence < 0.95.
    Demote: lower confidence by 0.05 (floor 0.0) for STALE or ORPHANED
    memories (via classify_staleness) that are not MANUAL/MANUAL_SEED.

CONTRADICTION
    Two DECISION or INVARIANT memories with the same ``source_ref`` are
    flagged as contradictory when:
    - Their topic-token sets overlap >= 0.3 (Jaccard on title tokens).
    - At least one negation marker ("not", "no", "never", "avoid", "don't",
      "do not", "instead", "without") appears in exactly one of the two
      summaries (XOR sense: one says "do X", the other says "never X").

RELATES
    Two non-duplicate memories relate when:
    - They share >= 3 non-trivial topic tokens AND they are not the same id.
    - OR they share the same ``source_ref`` (pointing at the same file).
    - Confidence 0.7 (weaker signal than dedup).
    Conservative: at most one RELATES edge per pair (undirected by convention:
    from = lexicographically smaller id).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind, SourceType, StalenessLabel
from oh_no_my_claudecode.models.memory_edge import EdgeType, MemoryEdge
from oh_no_my_claudecode.utils.text import stable_id, tokenize

# ── tunables ─────────────────────────────────────────────────────────────────

# Token-overlap (Jaccard) threshold for near-duplicate detection.
_DEDUP_JACCARD_THRESHOLD = 0.55

# Minimum shared tokens for RELATES edges (besides same source_ref).
_RELATES_SHARED_TOKENS = 3

# Jaccard threshold for topic-overlap required to test for contradictions.
_CONTRADICTION_TOPIC_OVERLAP = 0.30

# Negation/divergence markers for contradiction detection.
_NEGATION_MARKERS: frozenset[str] = frozenset(
    {
        "not",
        "no",
        "never",
        "avoid",
        "don't",
        "dont",
        "do",  # "do not" splits to ["do", "not"]; "not" alone triggers
        "instead",
        "without",
    }
)

# Memory kinds eligible for contradiction detection.
_CONTRADICTION_KINDS: frozenset[MemoryKind] = frozenset(
    {MemoryKind.DECISION, MemoryKind.INVARIANT}
)

# Protected source types — never retired, but edges still written.
_PROTECTED_SOURCES: frozenset[SourceType] = frozenset(
    {SourceType.MANUAL, SourceType.MANUAL_SEED}
)

# Confidence bump/dip for promote/demote.
_PROMOTE_DELTA = 0.05
_DEMOTE_DELTA = 0.05

# Feedback threshold for promote.
_PROMOTE_FEEDBACK_THRESHOLD = 0.3


# ── result dataclass ─────────────────────────────────────────────────────────


@dataclass
class ConsolidationResult:
    """Counts of changes made (or planned, in dry-run mode) by consolidate()."""

    duplicates_detected: int = 0
    merged: int = 0
    promoted: int = 0
    demoted: int = 0
    edges_added: dict[str, int] = field(default_factory=lambda: {t.value: 0 for t in EdgeType})

    def total_edges(self) -> int:
        return sum(self.edges_added.values())

    def summary_lines(self) -> list[str]:
        """Human-readable lines suitable for CLI rendering."""
        lines = [
            f"Duplicates detected:  {self.duplicates_detected}",
            f"Merged (survivors):   {self.merged}",
            f"Promoted:             {self.promoted}",
            f"Demoted:              {self.demoted}",
            "Edges added:",
        ]
        for edge_type, count in sorted(self.edges_added.items()):
            lines.append(f"  {edge_type}: {count}")
        lines.append(f"  (total: {self.total_edges()})")
        return lines


# ── helpers ───────────────────────────────────────────────────────────────────


def _jaccard(set_a: set[str], set_b: set[str]) -> float:
    """Return Jaccard similarity between two token sets."""
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def _memory_tokens(memory: MemoryEntry) -> set[str]:
    """Return the union token set for a memory (title + summary + details)."""
    return set(tokenize(f"{memory.title} {memory.summary} {memory.details}"))


def _title_tokens(memory: MemoryEntry) -> set[str]:
    """Return the title-only token set (for topic-overlap checks)."""
    return set(tokenize(memory.title))


def _has_negation(summary: str) -> bool:
    """Return True if any negation marker appears in the summary tokens."""
    return bool(_NEGATION_MARKERS & set(tokenize(summary)))


def _survivor(mem_a: MemoryEntry, mem_b: MemoryEntry) -> tuple[MemoryEntry, MemoryEntry]:
    """Return ``(survivor, loser)`` for a duplicate pair.

    Priority:
    1. Protected source type (MANUAL / MANUAL_SEED) always survives.
    2. Higher effective score (confidence + feedback_score * 0.5).
    3. Lexicographically smaller id (deterministic tiebreak).
    """
    a_protected = mem_a.source_type in _PROTECTED_SOURCES
    b_protected = mem_b.source_type in _PROTECTED_SOURCES
    if a_protected and not b_protected:
        return mem_a, mem_b
    if b_protected and not a_protected:
        return mem_b, mem_a
    score_a = mem_a.confidence + mem_a.feedback_score * 0.5
    score_b = mem_b.confidence + mem_b.feedback_score * 0.5
    if score_a > score_b:
        return mem_a, mem_b
    if score_b > score_a:
        return mem_b, mem_a
    # Deterministic tiebreak: lexicographically smaller id wins.
    return (mem_a, mem_b) if mem_a.id <= mem_b.id else (mem_b, mem_a)


def _edge_id(from_id: str, to_id: str, edge_type: EdgeType) -> str:
    """Return a deterministic edge id."""
    return stable_id(from_id, to_id, edge_type.value, prefix="edge")


def _is_near_duplicate(mem_a: MemoryEntry, mem_b: MemoryEntry) -> bool:
    """Return True when two memories are near-duplicates.

    Two checks:
    1. Same kind + same source_ref AND summary token-overlap (Jaccard) >= 0.40.
       "Any shared token" is too loose — contradicting memories share anchor
       files and domain words.  A 40% Jaccard on summaries means they are
       expressing the same idea in different phrasing, not opposing ideas.
    2. High token-overlap (Jaccard) across full text (title+summary+details)
       >= _DEDUP_JACCARD_THRESHOLD (0.55), regardless of source_ref.
    """
    if mem_a.kind != mem_b.kind:
        return False
    # Same source_ref + kind with substantial summary overlap → dedup.
    if mem_a.source_ref and mem_b.source_ref and mem_a.source_ref == mem_b.source_ref:
        a_tokens = set(tokenize(mem_a.summary))
        b_tokens = set(tokenize(mem_b.summary))
        if a_tokens and b_tokens and _jaccard(a_tokens, b_tokens) >= 0.40:
            return True
    # High full-text token-overlap (Jaccard) regardless of source_ref.
    tokens_a = _memory_tokens(mem_a)
    tokens_b = _memory_tokens(mem_b)
    if not tokens_a or not tokens_b:
        return False
    return _jaccard(tokens_a, tokens_b) >= _DEDUP_JACCARD_THRESHOLD


def _is_contradiction(mem_a: MemoryEntry, mem_b: MemoryEntry) -> bool:
    """Return True when two memories likely contradict each other.

    Conservative heuristic:
    - Both must be DECISION or INVARIANT kind.
    - Same non-empty source_ref (same file anchor).
    - Topic tokens (title) overlap >= _CONTRADICTION_TOPIC_OVERLAP.
    - Negation appears in exactly one of the two summaries (XOR).
    """
    if mem_a.kind not in _CONTRADICTION_KINDS or mem_b.kind not in _CONTRADICTION_KINDS:
        return False
    if not mem_a.source_ref or mem_a.source_ref != mem_b.source_ref:
        return False
    topic_a = _title_tokens(mem_a)
    topic_b = _title_tokens(mem_b)
    if _jaccard(topic_a, topic_b) < _CONTRADICTION_TOPIC_OVERLAP:
        return False
    neg_a = _has_negation(mem_a.summary)
    neg_b = _has_negation(mem_b.summary)
    return neg_a != neg_b  # XOR: exactly one has a negation marker


def _is_related(mem_a: MemoryEntry, mem_b: MemoryEntry) -> bool:
    """Return True when two distinct memories are related by co-reference."""
    if mem_a.id == mem_b.id:
        return False
    # Same file anchor (non-empty source_ref).
    if mem_a.source_ref and mem_b.source_ref and mem_a.source_ref == mem_b.source_ref:
        return True
    # Shared topic tokens (>= _RELATES_SHARED_TOKENS).
    tokens_a = _memory_tokens(mem_a)
    tokens_b = _memory_tokens(mem_b)
    return len(tokens_a & tokens_b) >= _RELATES_SHARED_TOKENS


# ── core consolidation logic ──────────────────────────────────────────────────


def consolidate_memories(
    memories: list[MemoryEntry],
    repo_root: Path,
    *,
    existing_edge_ids: set[str] | None = None,
) -> tuple[list[MemoryEntry], list[MemoryEdge], ConsolidationResult]:
    """Run the full consolidation pass on *memories*.

    This is a pure function — no I/O.  The caller decides whether to persist
    the returned updates (``dry_run`` logic lives in the service layer).

    Parameters
    ----------
    memories:
        All memories currently in the store.
    repo_root:
        Repository root (used by classify_staleness for promote/demote).
    existing_edge_ids:
        Set of edge ids already in the store; used to avoid duplicating edges
        across repeated consolidation runs.

    Returns
    -------
    updated_memories:
        MemoryEntry instances that differ from their input (need persisting).
    new_edges:
        MemoryEdge instances to upsert.
    result:
        ConsolidationResult with counts.
    """
    from oh_no_my_claudecode.memory.staleness import classify_staleness

    if existing_edge_ids is None:
        existing_edge_ids = set()

    now = datetime.now(tz=UTC)
    result = ConsolidationResult()
    updated: dict[str, MemoryEntry] = {m.id: m for m in memories}
    new_edges: list[MemoryEdge] = []
    retired_ids: set[str] = set()

    # ── 1. DEDUP ────────────────────────────────────────────────────────────
    # O(n²) but memory stores are typically small (< 1000 entries).
    # duplicate_pairs tracks pairs identified as duplicates so the RELATES loop
    # can skip them (we don't want RELATES edges on top of DUPLICATE_OF edges).
    duplicate_pairs: set[frozenset[str]] = set()

    for i, mem_a in enumerate(memories):
        for mem_b in memories[i + 1 :]:
            pair = frozenset({mem_a.id, mem_b.id})
            if pair in duplicate_pairs:
                continue

            if not _is_near_duplicate(mem_a, mem_b):
                continue

            duplicate_pairs.add(pair)

            result.duplicates_detected += 1
            survivor, loser = _survivor(mem_a, mem_b)

            eid = _edge_id(loser.id, survivor.id, EdgeType.DUPLICATE_OF)
            if eid not in existing_edge_ids:
                new_edges.append(
                    MemoryEdge(
                        id=eid,
                        from_memory_id=loser.id,
                        to_memory_id=survivor.id,
                        edge_type=EdgeType.DUPLICATE_OF,
                        confidence=1.0,
                        created_at=now,
                    )
                )
                existing_edge_ids.add(eid)
                result.edges_added[EdgeType.DUPLICATE_OF.value] += 1

            # Carry forward max confidence + summed feedback to survivor.
            current_survivor = updated[survivor.id]
            merged_confidence = max(current_survivor.confidence, loser.confidence)
            merged_feedback = min(current_survivor.feedback_score + loser.feedback_score, 1.0)
            if (
                merged_confidence != current_survivor.confidence
                or merged_feedback != current_survivor.feedback_score
            ):
                updated[survivor.id] = current_survivor.model_copy(
                    update={
                        "confidence": merged_confidence,
                        "feedback_score": merged_feedback,
                        "updated_at": now,
                    }
                )
                result.merged += 1

            # Retire non-protected loser.
            if loser.source_type not in _PROTECTED_SOURCES and loser.id not in retired_ids:
                retired_ids.add(loser.id)
                updated[loser.id] = updated[loser.id].model_copy(
                    update={"staleness": "orphaned", "updated_at": now}
                )

    # ── 2. PROMOTE / DEMOTE ────────────────────────────────────────────────
    for memory in memories:
        if memory.id in retired_ids:
            continue
        current = updated[memory.id]

        # Promote: high feedback, not already near-max confidence.
        if (
            current.feedback_score >= _PROMOTE_FEEDBACK_THRESHOLD
            and current.confidence < 0.95
        ):
            updated[current.id] = current.model_copy(
                update={
                    "confidence": min(current.confidence + _PROMOTE_DELTA, 1.0),
                    "updated_at": now,
                }
            )
            result.promoted += 1
            current = updated[current.id]

        # Demote: stale/orphaned non-protected entries.
        if current.source_type in _PROTECTED_SOURCES:
            continue
        staleness: StalenessLabel = classify_staleness(repo_root, current)
        if staleness in ("stale", "orphaned"):
            updated[current.id] = current.model_copy(
                update={
                    "staleness": staleness,
                    "confidence": max(current.confidence - _DEMOTE_DELTA, 0.0),
                    "updated_at": now,
                }
            )
            result.demoted += 1

    # ── 3. CONTRADICTION edges ────────────────────────────────────────────
    active_memories = [m for m in memories if m.id not in retired_ids]
    for i, mem_a in enumerate(active_memories):
        for mem_b in active_memories[i + 1 :]:
            if not _is_contradiction(mem_a, mem_b):
                continue
            # Convention: from = smaller id (undirected).
            from_id, to_id = (
                (mem_a.id, mem_b.id) if mem_a.id <= mem_b.id else (mem_b.id, mem_a.id)
            )
            eid = _edge_id(from_id, to_id, EdgeType.CONTRADICTS)
            if eid not in existing_edge_ids:
                new_edges.append(
                    MemoryEdge(
                        id=eid,
                        from_memory_id=from_id,
                        to_memory_id=to_id,
                        edge_type=EdgeType.CONTRADICTS,
                        confidence=0.6,  # conservative — heuristic, not ground truth
                        created_at=now,
                    )
                )
                existing_edge_ids.add(eid)
                result.edges_added[EdgeType.CONTRADICTS.value] += 1

    # ── 4. RELATES edges ─────────────────────────────────────────────────
    for i, mem_a in enumerate(active_memories):
        for mem_b in active_memories[i + 1 :]:
            # Skip pairs that already have a stronger edge.
            pair = frozenset({mem_a.id, mem_b.id})
            if pair in duplicate_pairs:  # already has DUPLICATE_OF edge
                continue
            from_id, to_id = (
                (mem_a.id, mem_b.id) if mem_a.id <= mem_b.id else (mem_b.id, mem_a.id)
            )
            eid_relates = _edge_id(from_id, to_id, EdgeType.RELATES)
            eid_dup = _edge_id(
                *((mem_a.id, mem_b.id) if mem_a.id <= mem_b.id else (mem_b.id, mem_a.id)),
                EdgeType.DUPLICATE_OF,
            )
            eid_cont = _edge_id(from_id, to_id, EdgeType.CONTRADICTS)
            if (
                eid_relates in existing_edge_ids
                or eid_dup in existing_edge_ids
                or eid_cont in existing_edge_ids
            ):
                continue
            if not _is_related(mem_a, mem_b):
                continue
            new_edges.append(
                MemoryEdge(
                    id=eid_relates,
                    from_memory_id=from_id,
                    to_memory_id=to_id,
                    edge_type=EdgeType.RELATES,
                    confidence=0.7,
                    created_at=now,
                )
            )
            existing_edge_ids.add(eid_relates)
            result.edges_added[EdgeType.RELATES.value] += 1

    # ── collect changed memories ──────────────────────────────────────────
    changed_memories: list[MemoryEntry] = []
    for original in memories:
        current = updated[original.id]
        if current != original:
            changed_memories.append(current)

    return changed_memories, new_edges, result
