"""Per-prompt surgical memory recall for the UserPromptSubmit hook.

This module is pure and testable — it reads from storage and produces markdown;
it never touches stdin/stdout directly.

Terse mode (default for hooks):
  Set ONMC_VERBOSE=1 to get full markdown output.
  Set ONMC_TERSE=1 to force terse even when not a hook.

Skills injection:
  When auto_inject skills exist and are relevant to the prompt, a compact
  "Relevant skills" block is appended after the memory block.  The combined
  output is returned by compile_prompt_recall_safe.  Surfacing a skill records
  **no** usage or success signal — see :func:`record_skill_outcome`.

Activation gating:
  This module is the main *activation* path for learned artifacts: whatever it
  returns is injected into the agent's context.  Two gates apply:

  * the ``ONMC_LEARNING`` kill switch
    (:func:`oh_no_my_claudecode.learning.activation.is_learning_enabled`) —
    when it is off, nothing is injected.  The check fails **closed**.
  * unpromoted provenance — memory an agent wrote autonomously about its own
    run carries the :data:`UNPROMOTED_SOURCE_PREFIX` ``source_ref`` marker and
    is never auto-injected.  Such an entry stays fully readable through the
    explicit, human-driven surfaces (``onmc memory list``, ``onmc recall``);
    it just cannot silently become part of every future prompt.

Context firewall:
  When memories / skills are recalled, a ``recall_surfaced`` event is emitted
  to the side sink for observability.  The recalled content itself stays in
  context (it is high-value signal the model needs).  Set ``ONMC_FIREWALL=0``
  to disable the sink emit.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

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

# ---------------------------------------------------------------------------
# Relevance gate + budget cap
# ---------------------------------------------------------------------------

# Environment variable names for the two new controls.
_ENV_MIN_SCORE = "ONMC_RECALL_MIN_SCORE"
_ENV_MAX_CHARS = "ONMC_RECALL_MAX_CHARS"

# Default minimum score for the TOP retrieved entry.  If the best match
# doesn't reach this bar, nothing is injected.  1.5 requires either at least
# one token overlap (3 pts) + some confidence, or very-high-confidence memory
# with no overlap (rare). 0.0 disables the gate entirely.
_GATE_MIN_SCORE_DEFAULT: float = 1.5

# Default max injected characters.  This is a REAL default cap: injected memory
# context is bounded unless the user explicitly opts out.  ~4000 chars ≈ 800
# whitespace tokens, which comfortably fits the default 5-entry recall while
# still refusing to paste a pathological multi-kilobyte ``details`` field into
# every prompt.  Set ``ONMC_RECALL_MAX_CHARS=0`` to opt out of the cap entirely
# (unbounded injection is then the user's explicit choice).  Entries are kept
# highest-scored-first; the tail is dropped with a terse trailing note.
_GATE_MAX_CHARS_DEFAULT: int = 4000

# ---------------------------------------------------------------------------
# Activation gating: kill switch + unpromoted provenance
# ---------------------------------------------------------------------------

#: Reserved ``source_ref`` prefix marking a memory entry that an agent wrote
#: autonomously (autopilot LEARN, MCP ``record_memory``, ...) with **no**
#: promotion record behind it.  Entries carrying this prefix are recorded and
#: human-reviewable but are never auto-injected into a prompt: activation
#: requires a promotion, not merely a write.
UNPROMOTED_SOURCE_PREFIX = "unpromoted:"


def unpromoted_source_ref(origin: str) -> str:
    """Return the quarantined ``source_ref`` an autonomous writer must stamp.

    ``unpromoted_source_ref("autopilot:plan")`` → ``"unpromoted:autopilot:plan"``.
    Idempotent, so re-stamping an already-marked ref is safe.
    """
    cleaned = origin.strip() or "unknown"
    if cleaned.startswith(UNPROMOTED_SOURCE_PREFIX):
        return cleaned
    return f"{UNPROMOTED_SOURCE_PREFIX}{cleaned}"


def is_unpromoted_source(source_ref: str) -> bool:
    """Whether *source_ref* marks autonomously-written, unpromoted content."""
    return source_ref.startswith(UNPROMOTED_SOURCE_PREFIX)


def learning_enabled() -> bool:
    """Whether learned artifacts may be injected at all — fails **closed**.

    Delegates to the single kill switch
    (:func:`oh_no_my_claudecode.learning.activation.is_learning_enabled`,
    ``ONMC_LEARNING``).  Any failure resolving the switch is treated as OFF: a
    kill switch that fails open is advisory, not a switch.
    """
    try:
        from oh_no_my_claudecode.learning.activation import is_learning_enabled

        return is_learning_enabled()
    except Exception:  # noqa: BLE001
        return False


def _read_min_score(override: float | None) -> float:
    """Resolve the effective min-score threshold from param or env."""
    if override is not None:
        return override
    try:
        return float(os.environ.get(_ENV_MIN_SCORE, str(_GATE_MIN_SCORE_DEFAULT)))
    except (TypeError, ValueError):
        return _GATE_MIN_SCORE_DEFAULT


def _read_max_chars(override: int | None) -> int:
    """Resolve the effective max-chars budget from param or env (0 = off)."""
    if override is not None:
        return override
    try:
        return int(os.environ.get(_ENV_MAX_CHARS, str(_GATE_MAX_CHARS_DEFAULT)))
    except (TypeError, ValueError):
        return _GATE_MAX_CHARS_DEFAULT


def _apply_char_budget(
    candidates: list[MemoryEntry],
    max_chars: int,
) -> tuple[list[MemoryEntry], int]:
    """Trim *candidates* to fit within *max_chars* (highest-scored first).

    Returns ``(kept, dropped_count)``.  Always keeps at least one entry so
    callers never see a budget-gated empty when relevant content exists.
    The char estimate uses title + summary + details + 50-char formatting
    overhead per entry — conservative but avoids a full render-then-recount
    cycle.
    """
    if max_chars <= 0:
        return candidates, 0
    char_total = 0
    kept: list[MemoryEntry] = []
    for cand in candidates:
        cand_chars = len(cand.title) + len(cand.summary) + len(cand.details or "") + 50
        if not kept or char_total + cand_chars <= max_chars:
            kept.append(cand)
            char_total += cand_chars
        # else: drop silently (counted below)
    dropped = len(candidates) - len(kept)
    return kept, dropped


def _dropped_note(dropped: int) -> str:
    """Terse trailing note appended when budget cap drops entries."""
    word = "memory" if dropped == 1 else "memories"
    return f"[{dropped} {word} not shown — budget cap]"


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
    entirely by returning 0.  Zero-confidence memories are also excluded, as is
    anything carrying :data:`UNPROMOTED_SOURCE_PREFIX` provenance — an agent
    writing a memory about its own run does not thereby promote it.

    Stale/orphaned/unanchored memories have their raw score multiplied by
    _STALE_WEIGHT to push them below fresh memories without hiding them
    completely when no fresh alternatives exist.
    """
    if is_unpromoted_source(memory.source_ref):
        return 0.0
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
    min_score: float | None = None,
    max_chars: int | None = None,
) -> tuple[str, int]:
    """Return a tight "Relevant repo memory" block for *prompt*.

    Args:
        storage: Initialised SQLiteStorage instance.
        prompt: The raw user prompt text used as the search query.
        limit: Maximum number of memory entries to include.
        budget_tokens: Hard token cap for the returned markdown (full mode only).
        terse: When None, checks ONMC_VERBOSE/ONMC_TERSE env vars with
            hook default (terse=True).  Pass True/False to override.
        min_score: Relevance gate — if the top-scored entry's score is below
            this value, nothing is injected.  ``None`` reads
            ``ONMC_RECALL_MIN_SCORE`` env (default 1.5).  Set to ``0.0`` to
            disable the gate.
        max_chars: Char budget cap.  Entries are kept highest-scored-first;
            the tail is dropped with a terse trailing note.  ``None`` reads
            ``ONMC_RECALL_MAX_CHARS`` env (default 4000; set ``0`` to opt out
            of the cap and allow unbounded injection).

    Returns:
        ``(text, token_count)`` where *text* is the formatted block and
        *token_count* is the approximate whitespace-token count.  Returns
        ``("", 0)`` when the ``ONMC_LEARNING`` kill switch is off, when no
        relevant memories are found, or when the relevance gate rejects the
        best result.
    """
    if not prompt or not prompt.strip():
        return "", 0

    # Kill switch — fails closed.  With learning off, nothing is injected.
    if not learning_enabled():
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

    # Relevance gate — suppress injection when the best match doesn't clear the
    # threshold.  This avoids bloating context with unfocused, low-signal hints.
    effective_min_score = _read_min_score(min_score)
    if effective_min_score > 0.0 and scored[0][0] < effective_min_score:
        return "", 0

    # Step 2b — Optional embeddings rerank (applied to the top candidates
    # before token-budget truncation so the most semantically relevant entries
    # survive the budget cut).
    top_candidates = [m for _, m in scored[:limit]]
    top_scores = [s for s, _ in scored[:limit]]
    with contextlib.suppress(Exception):  # noqa: BLE001
        # Lazy import: embeddings are heavy — only load when rerank is available.
        from oh_no_my_claudecode.embeddings.rerank import rerank_with_embeddings

        top_candidates = rerank_with_embeddings(top_candidates, prompt, top_scores, storage)

    # Budget cap — trim candidates to fit within max_chars, keeping the
    # highest-scored entries.  A terse trailing note is appended for transparency.
    effective_max_chars = _read_max_chars(max_chars)
    top_candidates, dropped = _apply_char_budget(top_candidates, effective_max_chars)

    # Step 3 — Render output.
    if terse:
        from oh_no_my_claudecode.serialize.terse import render_recall_terse

        text = render_recall_terse(top_candidates, max_items=limit)
        if not text:
            return "", 0
        if dropped:
            text = text + "\n" + _dropped_note(dropped)
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
    if dropped:
        markdown = markdown + _dropped_note(dropped) + "\n"
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
        and *skill_ids* are the ids of surfaced skills (for observability only —
        surfacing records no usage or success signal).  Returns ``("", [])``
        when the ``ONMC_LEARNING`` kill switch is off or no relevant auto_inject
        skills exist.

    Always safe to call — any exception returns empty result.
    """
    try:
        # Kill switch — fails closed.  A skill is learned behaviour; with
        # learning off it must not reach the agent.
        if not learning_enabled():
            return "", []

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


def record_skill_outcome(
    storage: SQLiteStorage,
    skill_ids: list[str],
    *,
    success: bool,
) -> None:
    """Record an **observed** outcome for skills that were actually applied.

    ``storage.record_skill_use`` is the input to ``rank_skills`` and to
    ``skill_prune`` (which retires a skill once ``use_count >= 3`` and
    ``success_rate < 0.3``).  Feeding it a fabricated signal turns the skill
    machinery into a closed self-reinforcing loop, so this function exists only
    for callers holding real evidence of an outcome:

    * *success* must reflect an observed result — a verify pass, an explicit
      human thumbs-up — never the mere fact that a skill was retrieved.
    * There is deliberately **no** call to this function from the recall path.
      A skill being *shown* to the model is not a skill *working*, and it is not
      a skill *failing* either: recording either would invent evidence.  The
      surfacing event is reported through the notify sink instead (see
      :func:`compile_prompt_recall_safe`), where it stays observability rather
      than becoming training signal.

    *success* has no default on purpose — a caller that cannot say which
    outcome it observed has no business calling this.

    Errors are swallowed per-skill; recording metrics must never break a hook.
    """
    for skill_id in skill_ids:
        with contextlib.suppress(Exception):
            storage.record_skill_use(skill_id, success=success)


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
    repo_root: Path | None = None,
    min_score: float | None = None,
    max_chars: int | None = None,
) -> tuple[str, int]:
    """compile_prompt_recall + skills injection wrapped with a wall-clock timeout.

    When the compile exceeds *timeout_ms* (default: ONMC_HOOK_TIMEOUT_MS env
    var, else 800 ms) the function returns ("", 0) so the hook exits 0
    without blocking the host agent.

    Any exception is also swallowed — hooks must never crash the session.

    Skills injection:
      After the memory recall block, a compact "Relevant skills" section is
      appended when auto_inject skills are relevant to the prompt.  Surfacing a
      skill records **no** use or success signal — see
      :func:`record_skill_outcome`.

    Context firewall:
      When recall text is produced, a ``recall_surfaced`` event is emitted to
      the side sink, carrying the count of surfaced skills.  Pass *repo_root* to
      specify the sink target; defaults to ``Path.cwd()``.  Set
      ``ONMC_FIREWALL=0`` to disable sink emission.

    Args:
        min_score: Passed through to ``compile_prompt_recall``.  ``None`` reads
            the ``ONMC_RECALL_MIN_SCORE`` env var (default 1.5).
        max_chars: Passed through to ``compile_prompt_recall``.  ``None`` reads
            the ``ONMC_RECALL_MAX_CHARS`` env var (default 4000; ``0`` opts out
            of the cap).
    """
    import threading

    if timeout_ms is None:
        try:
            timeout_ms = int(os.environ.get("ONMC_HOOK_TIMEOUT_MS", "800"))
        except (TypeError, ValueError):
            timeout_ms = 800

    result: list[tuple[str, int]] = [("", 0)]
    exc_box: list[BaseException] = []
    surfaced_skills: list[int] = [0]

    def _run() -> None:
        try:
            memory_text, memory_tokens = compile_prompt_recall(
                storage,
                prompt,
                limit=limit,
                budget_tokens=budget_tokens,
                terse=terse,
                min_score=min_score,
                max_chars=max_chars,
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

            # Surfacing is reported, never recorded as a skill outcome: this
            # path has no evidence that a surfaced skill was used, let alone
            # that it worked.  See record_skill_outcome().
            surfaced_skills[0] = len(skill_ids)

        except Exception as exc:  # noqa: BLE001
            exc_box.append(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout_ms / 1000.0)

    if thread.is_alive() or exc_box:
        # Timeout or error — return empty; hook exits 0.
        return "", 0

    text, tokens = result[0]

    # Context firewall: emit observability event to side sink when recall
    # was produced.  The recalled content stays in context unchanged.
    if text:
        with contextlib.suppress(Exception):
            from oh_no_my_claudecode.hooks.firewall import firewall_emit
            from oh_no_my_claudecode.notify import EventKind, EventSeverity, NotifyEvent

            _root = repo_root if repo_root is not None else Path.cwd()
            firewall_emit(
                _root,
                NotifyEvent(
                    kind=EventKind.RECALL_SURFACED,
                    severity=EventSeverity.ROUTINE,
                    title="prompt-recall: memories injected into context",
                    detail=f"tokens≈{tokens} skills_surfaced={surfaced_skills[0]}",
                ),
            )

    return text, tokens
