"""Ask compiler — natural-language query over the repo memory brain.

Architecture
------------
1. **Offline ranking**: tokenize the question → run ``compile_recall`` to get
   ranked, cited ``RecallEntry`` items.  This path is always available with
   zero network/LLM dependency.

2. **Optional LLM synthesis**: when a ``BaseLLMProvider`` is supplied, build a
   tight prompt ("answer using ONLY these memories; cite memory ids") and call
   the provider inside a ``try/except`` block.  Any failure (network, auth,
   parse) is silently swallowed — the function still returns the ranked entries
   with ``answer=None`` and ``used_synthesis=False``.

The result is a plain dataclass (``AskResult``) so callers can JSON-serialise
it or render it with Rich without coupling to the compiler internals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from oh_no_my_claudecode.models import LLMGenerationRequest
from oh_no_my_claudecode.recall.compiler import RecallEntry, compile_recall

if TYPE_CHECKING:
    from oh_no_my_claudecode.llm.base import BaseLLMProvider
    from oh_no_my_claudecode.storage import SQLiteStorage

logger = logging.getLogger(__name__)

# Maximum tokens for synthesis prompt memory section to avoid blowing context.
_MAX_MEMORY_CHARS = 6_000

# Synthesis prompt template.
_SYNTHESIS_SYSTEM = (
    "You are a concise engineering assistant. "
    "Answer questions using ONLY the memory entries provided. "
    "Cite each memory you use by its id in parentheses, e.g. (mem-id). "
    "If the memories do not contain enough information, say so plainly. "
    "Keep the answer under 200 words."
)


@dataclass
class AskResult:
    """Result of ``compile_ask``."""

    question: str
    """The original question string."""

    entries: list[RecallEntry] = field(default_factory=list)
    """Ranked, cited memory entries relevant to the question."""

    answer: str | None = None
    """LLM-synthesized answer, or ``None`` when offline / synthesis failed."""

    used_synthesis: bool = False
    """True iff the LLM synthesis pass completed successfully."""

    no_data_hint: str = ""
    """Populated when no relevant memories were found."""


def compile_ask(
    storage: SQLiteStorage,
    repo_root: Path,  # noqa: ARG001  # accepted for API symmetry with other compilers
    question: str,
    *,
    limit: int = 8,
    provider: BaseLLMProvider | None = None,
) -> AskResult:
    """Query the memory brain for *question* and optionally synthesize an answer.

    Args:
        storage: Initialised ``SQLiteStorage`` instance.
        repo_root: Repository root (accepted for API symmetry; not used here).
        question: Natural-language question to answer from memory.
        limit: Maximum number of ranked memory entries to return.
        provider: Optional LLM provider for synthesis.  When ``None`` the
            function returns ranked+cited entries with ``answer=None``.

    Returns:
        An ``AskResult`` with ranked entries and an optional synthesized answer.
        Never raises — LLM failures produce ``answer=None`` with entries intact.
    """
    if not question or not question.strip():
        return AskResult(
            question=question,
            no_data_hint="Provide a non-empty question.",
        )

    # Step 1 — offline ranking via recall (reuses compile_recall's normalisation
    # + FTS + token-overlap scoring + citation building).
    recall_result = compile_recall(storage, question, limit=limit)

    result = AskResult(
        question=question,
        entries=recall_result.entries,
        no_data_hint=recall_result.no_data_hint if not recall_result.has_matches else "",
    )

    if not result.entries or provider is None:
        return result

    # Step 2 — optional best-effort LLM synthesis.
    result.answer = _synthesize(provider, question, result.entries)
    result.used_synthesis = result.answer is not None
    return result


# ---------------------------------------------------------------------------
# Synthesis helpers
# ---------------------------------------------------------------------------


def _build_memory_block(entries: list[RecallEntry]) -> str:
    """Return a compact text block describing each entry for the LLM prompt."""
    lines: list[str] = []
    for entry in entries:
        lines.append(f"[{entry.memory_id}] {entry.title}")
        lines.append(f"  kind: {entry.kind}")
        lines.append(f"  summary: {entry.what_happened}")
        if entry.resolution and entry.resolution != entry.what_happened:
            lines.append(f"  resolution: {entry.resolution}")
        if entry.citation:
            lines.append(f"  provenance: {entry.citation}")
        lines.append("")
    block = "\n".join(lines)
    return block[:_MAX_MEMORY_CHARS]


def _synthesize(
    provider: BaseLLMProvider,
    question: str,
    entries: list[RecallEntry],
) -> str | None:
    """Call the provider and return synthesis text, or ``None`` on any failure."""
    memory_block = _build_memory_block(entries)
    prompt = (
        f"Question: {question}\n\n"
        f"Memory entries:\n{memory_block}\n\n"
        "Answer the question using ONLY the memory entries above. "
        "Cite each memory you draw from by its id in parentheses."
    )
    try:
        response = provider.generate(
            LLMGenerationRequest(
                system_prompt=_SYNTHESIS_SYSTEM,
                prompt=prompt,
                temperature=0.0,
                max_tokens=400,
            )
        )
        text = response.text.strip()
        return text if text else None
    except Exception:  # noqa: BLE001
        logger.debug("ask synthesis failed; returning offline result", exc_info=True)
        return None
