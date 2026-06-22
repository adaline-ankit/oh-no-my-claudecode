"""Per-prompt surgical memory recall for the UserPromptSubmit hook.

This module is pure and testable — it reads from storage and produces markdown;
it never touches stdin/stdout directly.

Terse mode (default for hooks):
  Set ONMC_VERBOSE=1 to get full markdown output.
  Set ONMC_TERSE=1 to force terse even when not a hook.

Skills injection:
  When auto_inject skills exist and are relevant to the prompt, a compact
  "Relevant skills" block is appended after the memory block.  The combined
  output is returned by compile_prompt_recall_safe.  A surfaced skill's
  use_count is bumped (fire-and-forget; errors are swallowed).
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
# Skills recall
# ---------------------------------------------------------------------------

# Maximum number of auto-inject skills to surface per prompt.
_MAX_SKILLS = 3

# Tags extracted from the prompt by splitting on whitespace (no LLM).
# We reuse the same tokenize() function used for memory scoring.


def compile_skills_recall(
    storage: SQLiteStorage,
    prompt: str,
    *,
    terse: bool | None = None,
    max_skills: int = _MAX_SKILLS,
) -> tuple[str, list[str]]:
    """Return a compact "Relevant skills" block and list of surfaced skill ids.

    Args:
        storage: Initialised SQLiteStorage instance.
        prompt: Raw user prompt used to extract context tags and files.
        terse: When None, uses ONMC_VERBOSE/ONMC_TERSE env with hook default
            (terse=True).  Pass True/False to override.
        max_skills: Maximum number of skills to surface.

    Returns:
        ``(text, skill_ids)`` where *text* is the formatted block (may be "")
        and *skill_ids* are the ids of surfaced skills (for use_count bumping).
        Returns ``("", [])`` when no relevant auto_inject skills exist.

    Always safe to call — any exception returns empty result.
    """
    try:
        if terse is None:
            from oh_no_my_claudecode.serialize.terse import is_terse

            terse = is_terse(default=True)

        all_skills = storage.list_skills()
        eligible = [sk for sk in all_skills if sk.auto_inject]
        if not eligible:
            return "", []

        # Build context from the prompt: tags are the tokenized words, files
        # are extracted from simple path-like tokens (contain "/" or ".").
        prompt_tokens = list(tokenize(prompt))
        context_tags = prompt_tokens
        context_files = [t for t in prompt_tokens if "/" in t or "." in t]

        from oh_no_my_claudecode.skill.promoter import rank_skills

        ranked = rank_skills(eligible, tags=context_tags, files=context_files)
        top = ranked[:max_skills]

        # Only surface skills with a minimum relevance signal.
        # rank_skills returns all skills sorted; filter those with any tag
        # overlap or high intrinsic confidence.
        relevant = [
            sk
            for sk in top
            if (
                any(t.lower() in {tt.lower() for tt in (sk.tags or [])} for t in context_tags)
                or sk.confidence >= 0.7
            )
        ]

        if not relevant:
            return "", []

        if terse:
            from oh_no_my_claudecode.serialize.skill_renderer import render_skills_terse

            text = render_skills_terse(relevant, max_items=max_skills)
        else:
            from oh_no_my_claudecode.serialize.skill_renderer import render_skills_verbose

            text = render_skills_verbose(relevant, max_items=max_skills)

        if not text:
            return "", []

        surfaced_ids = [sk.id for sk in relevant]
        return text, surfaced_ids

    except Exception:  # noqa: BLE001
        return "", []


def _bump_skill_use_counts(storage: SQLiteStorage, skill_ids: list[str]) -> None:
    """Fire-and-forget: increment use_count for each surfaced skill.

    Errors are silently swallowed — bumping metrics must never break recall.
    """
    for skill_id in skill_ids:
        with contextlib.suppress(Exception):
            storage.record_skill_use(skill_id, success=True)


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
    """compile_prompt_recall + skills injection wrapped with a wall-clock timeout.

    When the compile exceeds *timeout_ms* (default: ONMC_HOOK_TIMEOUT_MS env
    var, else 800 ms) the function returns ("", 0) so the hook exits 0
    without blocking the host agent.

    Any exception is also swallowed — hooks must never crash the session.

    Skills injection:
      After the memory recall block, a compact "Relevant skills" section is
      appended when auto_inject skills are relevant to the prompt.  Surfaced
      skills have their use_count bumped (fire-and-forget).
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
            memory_text, memory_tokens = compile_prompt_recall(
                storage,
                prompt,
                limit=limit,
                budget_tokens=budget_tokens,
                terse=terse,
            )
            # Skills block — always suppressed so a skill error never breaks
            # the memory recall output.
            skills_text = ""
            skill_ids: list[str] = []
            with contextlib.suppress(Exception):
                skills_text, skill_ids = compile_skills_recall(
                    storage, prompt, terse=terse
                )

            # Combine: memory block first, then skills (separated by newline).
            combined_parts = [p for p in [memory_text, skills_text] if p]
            combined = "\n".join(combined_parts)
            combined_tokens = memory_tokens + _count_tokens(skills_text)
            result[0] = (combined, combined_tokens)

            # Bump use counts after building the result (fire-and-forget).
            if skill_ids:
                with contextlib.suppress(Exception):
                    _bump_skill_use_counts(storage, skill_ids)

        except Exception as exc:  # noqa: BLE001
            exc_box.append(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout_ms / 1000.0)

    if thread.is_alive() or exc_box:
        # Timeout or error — return empty; hook exits 0.
        return "", 0

    return result[0]
