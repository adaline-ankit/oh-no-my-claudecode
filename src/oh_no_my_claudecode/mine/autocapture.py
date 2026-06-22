"""Heuristic auto-capture: extract durable memory from a session transcript.

Design invariants
-----------------
- **No LLM.**  All extraction is regex/heuristic.  This keeps the path free,
  fast (< 1 s on typical sessions), and safe to run on every SessionEnd hook.
- **Precision over recall.**  A noisy brain is worse than a sparse one.  Only
  emit a memory entry when the signal pattern is unambiguous.
- **Capped output.**  At most ``MAX_MEMORIES_PER_SESSION`` entries per call so
  a chatty session cannot flood the store.
- **Dedup.**  ``stable_id`` ensures identical (kind, title, summary) tuples
  collide to the same row and do nothing on re-capture.
- **Traceable.**  All entries carry ``source_type=SourceType.SESSION`` and
  ``source_ref=<session_id>`` so they can be listed or pruned later.
- **Opt-out.**  Callers must check ``ONMC_AUTOCAPTURE`` before calling; this
  module itself does not read env vars so it remains testable in isolation.
"""

from __future__ import annotations

import re
from pathlib import Path

from oh_no_my_claudecode.mine.transcript import parse_assistant_turns
from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.utils.text import shorten, stable_id, tokenize
from oh_no_my_claudecode.utils.time import utc_now

# Maximum memories written per session — guards against transcript floods.
MAX_MEMORIES_PER_SESSION: int = 12

# Minimum character length for a summary to be worth storing.
_MIN_SUMMARY_LEN: int = 20

# Confidence score for all heuristic entries (lower than LLM-extracted 0.8+
# since we have no model judgment, but higher than zero because pattern match
# gives real signal).
_HEURISTIC_CONFIDENCE: float = 0.65

# ---------------------------------------------------------------------------
# Decision / fix patterns — phrases that signal a clear, durable decision.
# We anchor to line starts and sentence-level spans so we don't pick up
# casual references.  Each pattern captures a "summary fragment" group.
# ---------------------------------------------------------------------------

# "Fixed by …" / "The fix is …" / "Root cause: …"
_FIX_RE = re.compile(
    r"(?:^|\n)"
    r"(?:fixed(?: it| this| the bug| the issue)? by|the fix (?:is|was)|"
    r"root cause[:\s]+|resolved by|the solution (?:is|was))[:\s]+"
    r"(.{20,300}?)(?:[.!?\n]|$)",
    re.IGNORECASE | re.MULTILINE,
)

# "Decision: …" / "We decided to …" / "Decided to …"
_DECISION_RE = re.compile(
    r"(?:^|\n)"
    r"(?:decision[:\s]+|we decided to|decided to|choosing to|chose to)[:\s]*"
    r"(.{20,300}?)(?:[.!?\n]|$)",
    re.IGNORECASE | re.MULTILINE,
)

# "Note: …" / "Important: …" / "Key insight: …"  — durable notes
_NOTE_RE = re.compile(
    r"(?:^|\n)"
    r"(?:note[:\s]+|important[:\s]+|key insight[:\s]+|gotcha[:\s]+|"
    r"warning[:\s]+|caveat[:\s]+)"
    r"(.{20,300}?)(?:[.!?\n]|$)",
    re.IGNORECASE | re.MULTILINE,
)

# "Never …" / "Always …" — strong invariant phrasing
_INVARIANT_RE = re.compile(
    r"(?:^|\n)"
    r"(?:never|always|must never|must always|do not|don't)[:\s]+"
    r"(.{20,300}?)(?:[.!?\n]|$)",
    re.IGNORECASE | re.MULTILINE,
)

# Map pattern → (MemoryKind, short_kind_label_for_title)
_PATTERNS: list[tuple[re.Pattern[str], MemoryKind, str]] = [
    (_DECISION_RE, MemoryKind.DECISION, "decision"),
    (_FIX_RE, MemoryKind.GOTCHA, "fix"),
    (_NOTE_RE, MemoryKind.GOTCHA, "note"),
    (_INVARIANT_RE, MemoryKind.INVARIANT, "invariant"),
]

# Noise phrases that produce too many false positives — skip matches containing
# any of these substrings (case-insensitive).
_NOISE_PHRASES: frozenset[str] = frozenset(
    {
        "let me",
        "i'll",
        "i will",
        "i can",
        "i'll check",
        "looking at",
        "reading the",
        "will run",
        "going to",
        "let's",
    }
)


def _is_noise(text: str) -> bool:
    low = text.lower()
    return any(phrase in low for phrase in _NOISE_PHRASES)


def _make_title(kind_label: str, summary: str) -> str:
    """Generate a short title from the kind label and first words of summary."""
    words = summary.split()[:8]
    truncated = " ".join(words)
    if len(summary.split()) > 8:
        truncated += "..."
    return f"[auto] {kind_label}: {truncated}"


def capture_from_transcript(
    transcript_path: Path,
    *,
    session_id: str,
    repo_root: Path | None = None,
) -> list[MemoryEntry]:
    """Extract durable memory entries from a single transcript file.

    Returns at most ``MAX_MEMORIES_PER_SESSION`` ``MemoryEntry`` objects.
    Never raises — any parse error returns an empty list.
    """
    try:
        full_text, touched_files = parse_assistant_turns(transcript_path, repo_root=repo_root)
    except Exception:  # noqa: BLE001
        return []

    if not full_text.strip():
        return []

    now = utc_now()
    seen_ids: set[str] = set()
    results: list[MemoryEntry] = []

    for pattern, kind, kind_label in _PATTERNS:
        if len(results) >= MAX_MEMORIES_PER_SESSION:
            break
        for match in pattern.finditer(full_text):
            if len(results) >= MAX_MEMORIES_PER_SESSION:
                break
            raw = match.group(1).strip()
            summary = shorten(raw, max_length=200)
            if len(summary) < _MIN_SUMMARY_LEN:
                continue
            if _is_noise(summary):
                continue
            title = _make_title(kind_label, summary)
            entry_id = stable_id(session_id, kind.value, summary, prefix="session")
            if entry_id in seen_ids:
                continue
            seen_ids.add(entry_id)
            tags = tokenize(summary)[:6]
            if touched_files:
                tags = list(dict.fromkeys(tags + tokenize(touched_files[0])))[:8]
            results.append(
                MemoryEntry(
                    id=entry_id,
                    kind=kind,
                    title=title,
                    summary=summary,
                    details=f"Auto-captured from session {session_id}.",
                    source_type=SourceType.SESSION,
                    source_ref=session_id,
                    tags=tags,
                    confidence=_HEURISTIC_CONFIDENCE,
                    created_at=now,
                    updated_at=now,
                )
            )

    return results
