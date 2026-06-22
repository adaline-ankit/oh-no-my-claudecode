"""Recall compiler — match error/stacktrace text to past incidents in memory.

This module is the core of ``onmc recall``.  It is entirely offline and
deterministic (no LLM calls, no network).

Architecture
------------
1. **Normalise** the raw error text:
   - Strip line numbers (``at foo.js:42``, ``line 42``, ``File "…", line N``).
   - Strip hex memory addresses (``0x7f3a…``).
   - Strip UUIDs and long hex digests.
   - Strip ISO-8601 timestamps.
   - Strip ANSI escape codes.
   - Collapse whitespace.
   - Preserve: exception class names, error messages, module/file names
     (without the line numbers), Python tracebacks' "most recent call last".

2. **FTS5 retrieval** (broad recall): search_memories with the normalised
   signal tokens, biased toward FAILED_APPROACH / GOTCHA.

3. **Token-overlap reranking** with kind-specific boosts:
   - FAILED_APPROACH: ×3.0 — "we hit this, here is what fixed it"
   - GOTCHA:          ×2.5 — "dangerous edge case"
   - DECISION:        ×1.5 — sometimes explains the root cause
   - INVARIANT:       ×1.2 — invariant violated triggers errors
   - Others:          ×1.0 — general context

   The overlap fraction is normalised by the query token count so that a
   large noisy query with incidental matches does not crowd out a small
   precise match.  Component scores are blended then boosted:

     overlap_ratio = |overlap| / |query_tokens|          # [0, 1]
     base = overlap_ratio + (confidence × 0.3) + (feedback_score × 0.1)
     raw  = base × kind_boost

   Sort order: descending raw score; ties broken by (confidence desc,
   created_at desc) — more confident and more recent memories win ties
   deterministically across runs.

4. **Fix extraction**: the resolution text comes from:
   - ``did_not_work``/``fix`` memory artifact ``evidence`` (richest)
   - ``MemoryArtifactRecord.summary`` (fallback artifact text)
   - ``memory.details`` (inline narrative)
   - ``memory.summary`` (last resort)

5. **Staleness penalty**: stale/orphaned memories are weighted at 0.35×.

6. **Honest empty**: if no match meets ``_MIN_SCORE`` we return an empty
   result with a hint to run ``onmc mine``.

7. **Source citations**: every ``RecallEntry`` carries a ``citation`` string
   derived from the memory's ``source_type`` and ``source_ref`` so callers
   can trace the provenance of each result.  Missing / empty parts are
   omitted gracefully.  Short (terse) and full (verbose) forms are available
   via ``RecallEntry.citation_terse`` and ``RecallEntry.citation``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from oh_no_my_claudecode.models import MemoryArtifactType, MemoryEntry, MemoryKind
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import tokenize

# ---------------------------------------------------------------------------
# Normalisation constants
# ---------------------------------------------------------------------------

# Strip ANSI escape codes
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

# Strip hex addresses (0x... with 6+ hex digits)
_HEX_ADDR_RE = re.compile(r"\b0x[0-9a-fA-F]{6,}\b")

# Strip UUIDs and 32+ char hex digests
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_LONG_HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")

# Strip ISO-8601 timestamps (date + optional time)
_TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"
)

# Strip "at foo.js:42:10" or "at foo.py:42" style references (keep the module name)
_AT_LINE_RE = re.compile(r":(\d+)(:\d+)?(?=[)\s,]|$)", re.MULTILINE)

# Strip "File "foo.py", line 42" — keep the file name
_PYTHON_LINE_RE = re.compile(r",\s+line\s+\d+\b", re.IGNORECASE)

# Strip bare "line N" or "Line N" not preceded by a comma (already handled above)
_BARE_LINE_RE = re.compile(r"\bline\s+\d+\b", re.IGNORECASE)

# Strip repeated whitespace / blank lines
_MULTI_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")

# FTS retrieval multiplier
_FTS_MULTIPLIER = 4

# Kind-specific score multipliers
_KIND_BOOST: dict[MemoryKind, float] = {
    MemoryKind.FAILED_APPROACH: 3.0,
    MemoryKind.GOTCHA: 2.5,
    MemoryKind.DECISION: 1.5,
    MemoryKind.INVARIANT: 1.2,
    MemoryKind.DESIGN_CONFLICT: 1.1,
}

_STALE_LABELS = frozenset({"stale", "orphaned", "unanchored"})
_STALE_WEIGHT = 0.35

# Only entries scoring above this threshold are emitted.
_MIN_SCORE = 0.2

_NO_DATA_HINT = (
    "No recorded match — run `onmc mine` to capture incident history "
    "from session transcripts so the brain can answer this next time."
)

# Artifact types that carry resolution information (preferred over memory.details)
_FIX_ARTIFACT_TYPES = {MemoryArtifactType.FIX, MemoryArtifactType.DID_NOT_WORK}


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


@dataclass
class ScoreBreakdown:
    """Per-component score details for a single recall result."""

    overlap_ratio: float  # |overlap| / |query_tokens| — [0, 1]
    confidence: float  # memory.confidence — [0, 1]
    feedback_score: float  # memory.feedback_score
    kind_boost: float  # kind-specific multiplier
    stale_penalty: float  # 1.0 = fresh, 0.35 = stale
    final_score: float  # the score used for ranking


@dataclass
class RecallEntry:
    """One past incident that matches the queried error."""

    memory_id: str
    title: str
    what_happened: str  # memory.summary — what the problem was
    resolution: str  # best available fix/explanation text
    source_ref: str
    confidence: float
    relevance: float  # internal blended score (not raw)
    kind: str  # MemoryKind.value
    citation: str = ""  # compact provenance string "(source_type · ref_short)"
    score_breakdown: ScoreBreakdown | None = None


@dataclass
class RecallResult:
    """Ranked list of past incidents relevant to the queried error text."""

    query: str
    normalised_query: str
    entries: list[RecallEntry] = field(default_factory=list)
    no_data_hint: str = ""

    @property
    def has_matches(self) -> bool:
        return bool(self.entries)

    def to_markdown(self) -> str:
        """Render the recall result as a markdown "Seen this before?" report."""
        lines: list[str] = ["## Seen this before?", ""]
        if not self.has_matches:
            lines.append(f"> {self.no_data_hint}")
            return "\n".join(lines)

        lines.append(f"> Matched {len(self.entries)} prior incident(s) for this error.\n")
        for i, entry in enumerate(self.entries, 1):
            lines.append(f"### {i}. {entry.title}")
            lines.append("")
            lines.append(f"**What happened:** {entry.what_happened}")
            lines.append("")
            lines.append(f"**Resolution / Fix:** {entry.resolution}")
            lines.append("")
            lines.append(
                f"_kind: {entry.kind} | "
                f"confidence: {entry.confidence:.2f}"
                + (f" | provenance: {entry.citation}" if entry.citation else "")
                + "_"
            )
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def normalise_error_text(raw: str) -> str:
    """Normalise a raw error/stacktrace string to extract signal tokens.

    Strips line numbers, memory addresses, timestamps, UUIDs, and ANSI codes
    while preserving exception class names, error messages, and module/file
    names.  Returns a lower-cased, whitespace-collapsed string suitable for
    FTS5 querying and token-overlap scoring.

    Never raises on weird input — if the input is empty or unparseable, returns
    an empty string.
    """
    if not raw or not raw.strip():
        return ""

    text = raw
    try:
        # Strip ANSI escape codes
        text = _ANSI_RE.sub(" ", text)
        # Strip hex addresses
        text = _HEX_ADDR_RE.sub(" ", text)
        # Strip UUIDs
        text = _UUID_RE.sub(" ", text)
        # Strip long hex digests
        text = _LONG_HEX_RE.sub(" ", text)
        # Strip timestamps
        text = _TIMESTAMP_RE.sub(" ", text)
        # Strip ":42:10" from "foo.js:42:10" (keep "foo.js")
        text = _AT_LINE_RE.sub("", text)
        # Strip ", line 42" (Python tracebacks) — keep the filename
        text = _PYTHON_LINE_RE.sub("", text)
        # Strip bare "line N"
        text = _BARE_LINE_RE.sub("", text)
        # Collapse whitespace
        text = _MULTI_SPACE_RE.sub(" ", text)
        text = _MULTI_NL_RE.sub("\n\n", text)
        text = text.strip().lower()
    except Exception:  # noqa: BLE001
        # Any regex failure returns the raw text lowercased — better than crashing.
        text = raw.strip().lower()

    return text


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score_memory(
    memory: MemoryEntry, query_tokens: set[str]
) -> tuple[float, ScoreBreakdown] | None:
    """Return a (score, breakdown) pair for *memory* against *query_tokens*.

    Returns None when the memory is excluded (rejected or zero-confidence).

    Scoring formula
    ---------------
    The raw token count from before was replaced by an *overlap ratio*
    (|overlap| / |query_tokens|) so that a long noisy query with many
    incidental matches does not outrank a short precise match.  Confidence
    and feedback are blended in at modest weights so they act as a
    secondary signal rather than noise:

        overlap_ratio = |overlap| / |query_tokens|   # normalised [0, 1]
        base          = overlap_ratio
                        + (confidence × 0.3)
                        + (feedback_score × 0.1)
        raw           = base × kind_boost × stale_penalty

    This keeps the scale bounded and the components legible in the breakdown.
    """
    if memory.feedback_score <= -0.5:
        return None
    if memory.confidence <= 0.0:
        return None

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
    if not overlap:
        return None

    overlap_ratio = len(overlap) / len(query_tokens)
    base = overlap_ratio + (memory.confidence * 0.3) + (memory.feedback_score * 0.1)
    kind_boost = _KIND_BOOST.get(memory.kind, 1.0)
    stale_penalty = _STALE_WEIGHT if memory.staleness in _STALE_LABELS else 1.0
    final = base * kind_boost * stale_penalty

    breakdown = ScoreBreakdown(
        overlap_ratio=overlap_ratio,
        confidence=memory.confidence,
        feedback_score=memory.feedback_score,
        kind_boost=kind_boost,
        stale_penalty=stale_penalty,
        final_score=final,
    )
    return final, breakdown


# ---------------------------------------------------------------------------
# Citation builder
# ---------------------------------------------------------------------------

# Maximum characters for the short reference segment of a citation.
_CITATION_REF_CHARS = 16


def _build_citation(memory: MemoryEntry, *, terse: bool = False) -> str:
    """Return a compact provenance string for *memory*.

    Full form:  ``(source_type · ref_abbrev)``
    Terse form: ``[source_type·ref_abbrev]``

    Parts are omitted when they are empty or uninformative.  ``source_ref``
    is abbreviated to ``_CITATION_REF_CHARS`` characters so long git hashes
    or file paths do not overwhelm a line.
    """
    type_label = memory.source_type.value  # e.g. "git", "transcript"
    ref = memory.source_ref.strip()

    # Shorten to the first 16 chars — enough to identify a commit sha or file
    ref_short = ref[:_CITATION_REF_CHARS] if ref else ""

    parts = [p for p in (type_label, ref_short) if p]
    if not parts:
        return ""

    sep = "·"
    inner = f" {sep} ".join(parts)
    if terse:
        return f"[{inner}]"
    return f"({inner})"


# ---------------------------------------------------------------------------
# Fix extraction
# ---------------------------------------------------------------------------


def _extract_resolution(
    memory: MemoryEntry,
    artifact_index: dict[str, str],
) -> str:
    """Return the best available resolution / fix text for *memory*."""
    artifact_text = artifact_index.get(memory.id)
    if artifact_text:
        return artifact_text
    if memory.details and memory.details.strip() and memory.details != memory.summary:
        return memory.details.strip()
    return memory.summary.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_recall(
    storage: SQLiteStorage,
    query: str,
    *,
    limit: int = 8,
) -> RecallResult:
    """Match *query* (error text / stacktrace) against past incidents in memory.

    Args:
        storage: Initialised SQLiteStorage instance.
        query: Raw error text, stacktrace, or exception message.
        limit: Maximum number of recall entries to return.

    Returns:
        A ``RecallResult`` with zero or more ranked ``RecallEntry`` items.
        Returns an empty result with ``no_data_hint`` when nothing matches.
        This is not an error — callers must handle empty results gracefully.
    """
    if not query or not query.strip():
        return RecallResult(
            query=query,
            normalised_query="",
            no_data_hint=_NO_DATA_HINT,
        )

    normalised = normalise_error_text(query)
    if not normalised:
        return RecallResult(
            query=query,
            normalised_query="",
            no_data_hint=_NO_DATA_HINT,
        )

    # Step 1 — FTS5 candidate retrieval, biased to FAILED_APPROACH first.
    fts_candidates: list[MemoryEntry] = []
    seen_ids: set[str] = set()

    for kind_filter in (MemoryKind.FAILED_APPROACH, MemoryKind.GOTCHA, None):
        try:
            hits = storage.search_memories(
                query=normalised,
                kind=kind_filter,
                limit=limit * _FTS_MULTIPLIER,
            )
        except Exception:  # noqa: BLE001
            hits = []

        for hit in hits:
            if hit.id not in seen_ids:
                seen_ids.add(hit.id)
                fts_candidates.append(hit)

        # If we already have enough candidates from targeted FTS, stop early.
        if len(fts_candidates) >= limit * _FTS_MULTIPLIER:
            break

    # Fall back to listing all memories when FTS returns nothing.
    if not fts_candidates:
        try:
            all_memories = storage.list_memories()
        except Exception:  # noqa: BLE001
            all_memories = []
        fts_candidates = all_memories

    if not fts_candidates:
        return RecallResult(
            query=query,
            normalised_query=normalised,
            no_data_hint=_NO_DATA_HINT,
        )

    # Step 2 — Load fix/did_not_work artifacts for the candidate set.
    candidate_ids = {m.id for m in fts_candidates}
    artifact_index: dict[str, str] = {}  # memory_id -> resolution text
    try:
        for artifact_type in _FIX_ARTIFACT_TYPES:
            artifacts = storage.list_memory_artifacts(artifact_type=artifact_type)
            for artifact in artifacts:
                if artifact.memory_id in candidate_ids and artifact.memory_id not in artifact_index:
                    artifact_index[artifact.memory_id] = (
                        artifact.evidence.strip() if artifact.evidence else artifact.summary.strip()
                    )
    except Exception:  # noqa: BLE001, S110
        pass  # artifact retrieval failure must not break recall

    # Step 3 — Token-overlap reranking with kind-specific boosts.
    query_tokens = set(tokenize(normalised))
    if not query_tokens:
        return RecallResult(
            query=query,
            normalised_query=normalised,
            no_data_hint=_NO_DATA_HINT,
        )

    scored: list[tuple[float, ScoreBreakdown, MemoryEntry]] = []
    seen_score: set[str] = set()
    for memory in fts_candidates:
        if memory.id in seen_score:
            continue
        seen_score.add(memory.id)
        result_pair = _score_memory(memory, query_tokens)
        if result_pair is not None:
            s, breakdown = result_pair
            if s >= _MIN_SCORE:
                scored.append((s, breakdown, memory))

    # Sort by score (desc), then confidence (desc), then created_at (desc,
    # i.e. most recent first).  We negate the timestamp as a float so that a
    # single tuple of floats can be sorted ascending for all three criteria.
    def _sort_key(
        item: tuple[float, ScoreBreakdown, MemoryEntry],
    ) -> tuple[float, float, float]:
        s, _, mem = item
        ts = mem.created_at.timestamp() if mem.created_at is not None else 0.0
        return (-s, -mem.confidence, -ts)

    scored.sort(key=_sort_key)
    top = scored[:limit]

    if not top:
        return RecallResult(
            query=query,
            normalised_query=normalised,
            no_data_hint=_NO_DATA_HINT,
        )

    # Step 4 — Build RecallEntry items.
    entries: list[RecallEntry] = []
    for s, breakdown, memory in top:
        resolution = _extract_resolution(memory, artifact_index)
        citation = _build_citation(memory)
        entries.append(
            RecallEntry(
                memory_id=memory.id,
                title=memory.title,
                what_happened=memory.summary,
                resolution=resolution,
                source_ref=memory.source_ref,
                confidence=memory.confidence,
                relevance=s,
                kind=memory.kind.value,
                citation=citation,
                score_breakdown=breakdown,
            )
        )

    return RecallResult(
        query=query,
        normalised_query=normalised,
        entries=entries,
    )
