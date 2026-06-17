"""Per-prompt surgical memory recall for the UserPromptSubmit hook.

This module is pure and testable — it reads from storage and produces markdown;
it never touches stdin/stdout directly.

Terse mode (default for hooks):
  Set ONMC_VERBOSE=1 to get full markdown output.
  Set ONMC_TERSE=1 to force terse even when not a hook.
"""

from __future__ import annotations

import contextlib
import os

from oh_no_my_claudecode.models import MemoryEntry
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import tokenize

# Staleness labels that carry a ranking penalty (not full exclusion so that a
# repository with only stale memories still surfaces something rather than
# nothing).
_STALE_LABELS = frozenset({"stale", "orphaned", "unanchored"})

# Penalty multiplier applied to stale/orphaned/unanchored memories.
_STALE_WEIGHT = 0.35

# Approximate chars-per-token for the whitespace-word tokeniser used by
# limit_markdown_tokens().  We use the same split-on-whitespace approximation.
_CHARS_PER_TOKEN = 5

# Minimum score a memory must achieve to be included in the output.
_MIN_SCORE = 0.1


def _count_tokens(text: str) -> int:
    """Approximate token count using whitespace splitting (no LLM dependency)."""
    return len(text.split())


def _score_memory(memory: MemoryEntry, query_tokens: set[str]) -> float:
    """Compute a relevance score in [0, ∞) for one memory against query tokens.

    Scoring components (all additive before staleness weighting):
    - Token overlap (×3 per matching token): the primary relevance signal.
    - Confidence bonus: directly incorporated from the memory record.
    - Feedback bonus (×0.2): lightweight human-signal amplifier.

    Memories with feedback_score ≤ -0.5 (explicitly rejected) are excluded
    entirely by returning 0.  Zero-confidence memories are also excluded.

    Stale/orphaned/unanchored memories have their raw score multiplied by
    _STALE_WEIGHT to push them below fresh memories without hiding them
    completely when no fresh alternatives exist.
    """
    if memory.feedback_score <= -0.5:
        return 0.0
    if memory.confidence <= 0.0:
        return 0.0

    haystack_tokens = set(
        tokenize(
            " ".join(
                [
                    memory.title,
                    memory.summary,
                    memory.details,
                    memory.source_ref,
                    " ".join(memory.tags),
                ]
            )
        )
    )

    overlap = query_tokens & haystack_tokens
    raw = (
        float(len(overlap) * 3)
        + memory.confidence
        + (memory.feedback_score * 0.2)
    )

    if memory.staleness in _STALE_LABELS:
        return raw * _STALE_WEIGHT

    return raw


def compile_prompt_recall(
    storage: SQLiteStorage,
    prompt: str,
    *,
    limit: int = 5,
    budget_tokens: int = 300,
    terse: bool | None = None,
) -> tuple[str, int]:
    """Return a tight "Relevant repo memory" block for *prompt*.

    Args:
        storage: Initialised SQLiteStorage instance.
        prompt: The raw user prompt text used as the search query.
        limit: Maximum number of memory entries to include.
        budget_tokens: Hard token cap for the returned markdown (full mode only).
        terse: When None, checks ONMC_VERBOSE/ONMC_TERSE env vars with
            hook default (terse=True).  Pass True/False to override.

    Returns:
        ``(text, token_count)`` where *text* is the formatted block and
        *token_count* is the approximate whitespace-token count.  Returns
        ``("", 0)`` when no relevant memories are found.
    """
    if not prompt or not prompt.strip():
        return "", 0

    # Resolve terse flag — hooks default to terse; callers can override.
    if terse is None:
        from oh_no_my_claudecode.serialize.terse import is_terse

        terse = is_terse(default=True)  # hook default: terse

    # Step 1 — FTS candidate retrieval (broad recall, up to limit×4 candidates).
    try:
        candidates = storage.search_memories(query=prompt, limit=limit * 4)
    except Exception:  # noqa: BLE001
        candidates = []

    if not candidates:
        # FTS may have failed or returned nothing; fall back to full list.
        try:
            candidates = storage.list_memories()
        except Exception:  # noqa: BLE001
            return "", 0

    # Step 2 — Token-overlap + confidence + feedback reranking with staleness
    # penalty.
    query_tokens = set(tokenize(prompt))
    if not query_tokens:
        return "", 0

    scored: list[tuple[float, MemoryEntry]] = []
    seen_ids: set[str] = set()
    for memory in candidates:
        if memory.id in seen_ids:
            continue
        seen_ids.add(memory.id)
        score = _score_memory(memory, query_tokens)
        if score >= _MIN_SCORE:
            scored.append((score, memory))

    if not scored:
        return "", 0

    # Sort descending by score, then title for deterministic tie-breaking.
    scored.sort(key=lambda item: (-item[0], item[1].title))

    # Step 2b — Optional embeddings rerank (applied to the top candidates
    # before token-budget truncation so the most semantically relevant entries
    # survive the budget cut).
    top_candidates = [m for _, m in scored[:limit]]
    top_scores = [s for s, _ in scored[:limit]]
    with contextlib.suppress(Exception):  # noqa: BLE001
        # Lazy import: embeddings are heavy — only load when rerank is available.
        from oh_no_my_claudecode.embeddings.rerank import rerank_with_embeddings

        top_candidates = rerank_with_embeddings(top_candidates, prompt, top_scores, storage)

    # Step 3 — Render output.
    if terse:
        from oh_no_my_claudecode.serialize.terse import render_recall_terse

        text = render_recall_terse(top_candidates, max_items=limit)
        if not text:
            return "", 0
        return text, _count_tokens(text)

    # Full markdown mode.
    header = "## Relevant repo memory\n\n"
    token_used = _count_tokens(header)
    lines: list[str] = [header]
    included = 0

    for memory in top_candidates:
        entry_lines = [
            f"**{memory.title}** ({memory.kind.value})",
            f"  {memory.summary}",
        ]
        # Surface details only when they differ meaningfully from the summary.
        if memory.details and memory.details.strip() != memory.summary.strip():
            entry_lines.append(f"  _{memory.details}_")
        entry_lines.append("")  # blank line between entries
        entry_text = "\n".join(entry_lines)
        entry_tokens = _count_tokens(entry_text)

        if token_used + entry_tokens > budget_tokens and included > 0:
            # Budget exhausted; stop adding entries (always include at least one).
            break

        lines.append(entry_text)
        token_used += entry_tokens
        included += 1

    if included == 0:
        return "", 0

    markdown = "\n".join(lines).rstrip() + "\n"
    return markdown, _count_tokens(markdown)


# ---------------------------------------------------------------------------
# Hot-path compile with timeout guard
# ---------------------------------------------------------------------------


def compile_prompt_recall_safe(
    storage: SQLiteStorage,
    prompt: str,
    *,
    limit: int = 5,
    budget_tokens: int = 300,
    terse: bool | None = None,
    timeout_ms: int | None = None,
) -> tuple[str, int]:
    """compile_prompt_recall wrapped with a wall-clock timeout.

    When the compile exceeds *timeout_ms* (default: ONMC_HOOK_TIMEOUT_MS env
    var, else 800 ms) the function returns ("", 0) so the hook exits 0
    without blocking the host agent.

    Any exception is also swallowed — hooks must never crash the session.
    """
    import threading

    if timeout_ms is None:
        try:
            timeout_ms = int(os.environ.get("ONMC_HOOK_TIMEOUT_MS", "800"))
        except (TypeError, ValueError):
            timeout_ms = 800

    result: list[tuple[str, int]] = [("", 0)]
    exc_box: list[BaseException] = []

    def _run() -> None:
        try:
            result[0] = compile_prompt_recall(
                storage,
                prompt,
                limit=limit,
                budget_tokens=budget_tokens,
                terse=terse,
            )
        except Exception as exc:  # noqa: BLE001
            exc_box.append(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout_ms / 1000.0)

    if thread.is_alive() or exc_box:
        # Timeout or error — return empty; hook exits 0.
        return "", 0

    return result[0]
