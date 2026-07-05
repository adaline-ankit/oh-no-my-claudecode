"""Pure, deterministic learning extractor for ``onmc selfimprove review``.

Design
------
This module is **side-effect-free and deterministic** — no LLM calls, no
network, no file I/O. Feed it raw transcript text; get back a ranked list of
:class:`Candidate` learning proposals.

Extraction strategy
-------------------
Three signal categories are detected via regex heuristics:

``correction``
    The user corrects or overrides something the assistant said or did.
    Phrases like "actually, do X", "no, you should", "wrong — it should",
    "don't do X, do Y", "stop doing X".

``preference``
    The user states a preference or convention they want always honoured.
    Phrases like "always use X", "I prefer X", "use X not Y", "prefer X",
    "make sure to X", "remember to X", "going forward X".

``confirmation``
    The user confirms or validates a pattern/approach.
    Phrases like "yes, that's right", "exactly", "correct, keep doing",
    "perfect, that's the convention", "good, stick to that".

Each match yields one :class:`Candidate`. Candidates are de-duplicated by
normalised text and ranked: corrections first (highest signal), preferences
second, confirmations third; then by text length descending (more context =
more informative).

The caller decides whether to stage them via ``memstage.queue.stage()``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

SignalKind = Literal["correction", "preference", "confirmation"]

# Memory kind mapping — each signal kind maps to a MemoryKind string value
# so callers can pass it directly to memstage.queue.stage(kind=...).
_KIND_MAP: dict[SignalKind, str] = {
    "correction": "decision",
    "preference": "invariant",
    "confirmation": "doc_fact",
}

_RANK: dict[SignalKind, int] = {
    "correction": 0,
    "preference": 1,
    "confirmation": 2,
}


@dataclass(slots=True)
class Candidate:
    """A candidate learning extracted from a transcript.

    Attributes
    ----------
    signal:
        Which heuristic fired: ``"correction"``, ``"preference"``, or
        ``"confirmation"``.
    text:
        The extracted sentence or clause that contains the learning.
    rationale:
        Human-readable explanation of why this text was flagged.
    memory_kind:
        The MemoryKind string value recommended for staging (e.g.
        ``"decision"`` for corrections).
    title:
        Short title derived from the extracted text (first 72 chars).
    """

    signal: SignalKind
    text: str
    rationale: str
    memory_kind: str
    title: str

    # derived rank — lower = higher priority (not exposed in JSON output)
    _rank: int = field(default=0, repr=False, compare=False)

    def to_dict(self) -> dict[str, object]:
        """JSON-serialisable representation."""
        return {
            "signal": self.signal,
            "text": self.text,
            "rationale": self.rationale,
            "memory_kind": self.memory_kind,
            "title": self.title,
        }


# ---------------------------------------------------------------------------
# Heuristic patterns
# ---------------------------------------------------------------------------
#
# Each entry is (signal_kind, compiled_pattern, rationale_template).
# Patterns are tried against every sentence in the input text.
# The first match in a sentence wins (no double-counting).

_CORRECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\b(?:actually|no[,.]?\s+(?:you\s+should|we\s+should|it\s+should|don'?t)|"
            r"wrong[,.]|that'?s\s+wrong|incorrect[,.]|not\s+right[,.]|"
            r"don'?t\s+do\s+that|stop\s+doing|never\s+do\s+that|"
            r"instead[,\s]+(?:use|do|call|write)|"
            r"you\s+should(?:n'?t)?\s+(?:use|do|call|write|add|remove|include|exclude))\b",
            re.IGNORECASE,
        ),
        "User correction phrase detected — assistant was corrected or redirected.",
    ),
    (
        re.compile(
            r"\b(?:do\s+(?:X|it|this)\s+not\s+Y|"
            r"use\s+\S+\s+not\s+\S+|"
            r"not\s+\S+[,;]\s+use\s+\S+|"
            r"avoid\s+(?:using\s+)?\S+[,;]\s+(?:use|prefer)\s+\S+)\b",
            re.IGNORECASE,
        ),
        "Explicit X-not-Y correction pattern detected.",
    ),
]

_PREFERENCE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\b(?:always\s+(?:use|do|call|write|prefer|add|include|keep)|"
            r"I\s+(?:prefer|want|need|like)\s+(?:to\s+)?(?:use|do|have|keep|see)|"
            r"prefer\s+\S+(?:\s+over\s+\S+)?|"
            r"make\s+sure\s+(?:to\s+)?(?:always\s+)?(?:use|include|add|keep)|"
            r"remember\s+to\s+(?:always\s+)?(?:use|add|include)|"
            r"going\s+forward[,\s]+(?:use|always|prefer|we\s+(?:use|should))|"
            r"from\s+now\s+on[,\s]+(?:use|always|prefer|we\s+(?:use|should))|"
            r"our\s+convention\s+is|the\s+convention\s+(?:is|here\s+is)|"
            r"we\s+(?:always|never|use|prefer)\s+\S+|"
            r"standard\s+(?:is|here\s+is|approach\s+is))\b",
            re.IGNORECASE,
        ),
        "User preference or convention stated.",
    ),
]

_CONFIRMATION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\b(?:yes[,.]?\s+(?:that'?s\s+(?:right|correct|it|the\s+way)|exactly|perfect)|"
            r"exactly[,.]?\s+(?:right|correct|keep|that'?s)|"
            r"correct[,.]?\s+(?:keep|that'?s|do|always)|"
            r"perfect[,.]?\s+(?:that'?s\s+the\s+convention|keep|do|always|stick)|"
            r"good[,.]?\s+(?:stick\s+to\s+that|keep\s+(?:doing|using)|that'?s\s+the\s+(?:right|correct))|"
            r"great[,.]?\s+(?:keep|that'?s\s+the\s+(?:right|correct|convention)))\b",
            re.IGNORECASE,
        ),
        "User confirmation of a pattern or approach.",
    ),
]

# Map signal kind → list of (pattern, rationale) pairs
_PATTERN_REGISTRY: dict[SignalKind, list[tuple[re.Pattern[str], str]]] = {
    "correction": _CORRECTION_PATTERNS,
    "preference": _PREFERENCE_PATTERNS,
    "confirmation": _CONFIRMATION_PATTERNS,
}

# ---------------------------------------------------------------------------
# Sentence splitter
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")


def _split_sentences(text: str) -> list[str]:
    """Split text into sentence-like chunks for per-sentence matching."""
    parts = _SENTENCE_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Noise / false-positive filters
# ---------------------------------------------------------------------------

# Sentences shorter than this threshold are too context-free to be useful.
_MIN_SENTENCE_LEN = 15

# Code blocks and tool output lines are not human corrections.
_CODE_BLOCK_RE = re.compile(r"^(?:```|~~~|\$\s|\s{4,}|>\s*```)")

# Lines that look like assistant output markers — skip them.
_ASSISTANT_PREFIX_RE = re.compile(
    r"^(?:assistant|claude|ai|model|bot)\s*[:\-]\s*",
    re.IGNORECASE,
)


def _is_noise(sentence: str) -> bool:
    """Return True when a sentence should be filtered before pattern matching."""
    if len(sentence) < _MIN_SENTENCE_LEN:
        return True
    if _CODE_BLOCK_RE.match(sentence):
        return True
    # Skip assistant-attributed lines — we only want user signals.
    return bool(_ASSISTANT_PREFIX_RE.match(sentence))


# ---------------------------------------------------------------------------
# Title derivation
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")


def _make_title(text: str, max_len: int = 72) -> str:
    """Derive a short title from the extracted sentence."""
    # Collapse whitespace
    t = _WHITESPACE_RE.sub(" ", text).strip()
    if len(t) <= max_len:
        return t
    # Truncate at last word boundary before max_len
    truncated = t[:max_len].rsplit(" ", 1)[0]
    return truncated + "…"


# ---------------------------------------------------------------------------
# Deduplication key
# ---------------------------------------------------------------------------

_NON_ALPHA_RE = re.compile(r"[^a-z0-9\s]")


def _norm_key(text: str) -> str:
    """Normalised dedup key — lowercase, alphanumeric + spaces only."""
    lowered = text.lower()
    return _NON_ALPHA_RE.sub("", lowered).strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_learnings(text: str) -> list[Candidate]:
    """Extract candidate learnings from *text* using pure heuristics.

    Parameters
    ----------
    text:
        Raw transcript or session text to scan. May be multi-line, may
        contain code blocks (they are skipped).

    Returns
    -------
    list[Candidate]
        Ranked list of learning candidates — corrections first, then
        preferences, then confirmations; within each tier, longer sentences
        rank higher (more context). Empty when no signal is found.

    Notes
    -----
    - Deterministic: same input always yields the same output.
    - De-duplicated: two sentences that normalise to the same key produce
      only one candidate.
    - Offline: no LLM calls, no network.
    """
    if not text or not text.strip():
        return []

    sentences = _split_sentences(text)
    seen: set[str] = set()
    candidates: list[Candidate] = []

    for sentence in sentences:
        if _is_noise(sentence):
            continue

        key = _norm_key(sentence)
        if key in seen:
            continue

        for signal_kind, patterns in _PATTERN_REGISTRY.items():
            matched = False
            for pattern, rationale in patterns:
                if pattern.search(sentence):
                    matched = True
                    seen.add(key)
                    memory_kind = _KIND_MAP[signal_kind]
                    title = _make_title(sentence)
                    candidates.append(
                        Candidate(
                            signal=signal_kind,
                            text=sentence,
                            rationale=rationale,
                            memory_kind=memory_kind,
                            title=title,
                            _rank=_RANK[signal_kind],
                        )
                    )
                    break
            if matched:
                break

    # Sort: by rank asc (correction < preference < confirmation),
    # then by text length desc (more context = more informative).
    candidates.sort(key=lambda c: (c._rank, -len(c.text)))
    return candidates
