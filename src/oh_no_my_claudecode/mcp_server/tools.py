from __future__ import annotations

import json
import os
from typing import Any

from mcp.types import TextContent, Tool

from oh_no_my_claudecode.api import OnmcRepo
from oh_no_my_claudecode.embeddings.rerank import rerank_with_embeddings
from oh_no_my_claudecode.models import AttemptKind, AttemptStatus, MemoryEntry, MemoryKind
from oh_no_my_claudecode.serialize import to_toon
from oh_no_my_claudecode.utils.text import tokenize

# When set to "json", MCP tool responses are emitted as indented JSON instead
# of the default TOON compact format.
_ENV_FORMAT = "ONMC_MCP_FORMAT"

# Minimum query length below which FTS candidate pre-retrieval is skipped.
_MIN_QUERY_FOR_FTS = 3

MEMORY_KIND_VALUES = sorted(kind.value for kind in MemoryKind)
ATTEMPT_KIND_VALUES = sorted(kind.value for kind in AttemptKind)
ATTEMPT_STATUS_VALUES = sorted(status.value for status in AttemptStatus)

_PRIORITY_MEMORY_KINDS = {
    MemoryKind.DECISION,
    MemoryKind.INVARIANT,
    MemoryKind.VALIDATION_RULE,
}

_DEFAULT_SEARCH_LIMIT = 10


def list_onmc_tools() -> list[Tool]:
    """List the ONMC MCP tools with their JSON-schema inputs."""
    return [
        Tool(
            name="recall",
            title="Recall past incidents matching an error",
            description=(
                "Search memory for past failures and fixes that match an error message or "
                "stacktrace. Call this when you hit an error to find out if we have seen it "
                "before and what fixed it. Returns ranked prior incidents with resolutions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Error text, exception message, or stacktrace to match against "
                            "recorded incidents."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": _DEFAULT_SEARCH_LIMIT,
                        "description": "Maximum number of incident matches to return.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="search_memory",
            title="Search ONMC memory",
            description=(
                "Search stored repo memories with deterministic token-overlap ranking. "
                "Returns a JSON array of matches with relevance scores."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Free-text query describing what to recall.",
                    },
                    "kind": {
                        "type": "string",
                        "enum": MEMORY_KIND_VALUES,
                        "description": "Optional memory kind filter.",
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional file paths to boost related memories.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": _DEFAULT_SEARCH_LIMIT,
                        "description": "Maximum number of results to return.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="get_brief",
            title="Compile ONMC brief",
            description="Compile the task-focused repo brief and return it as markdown.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The engineering task to compile the brief for.",
                    },
                },
                "required": ["task"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="record_attempt",
            title="Record ONMC attempt",
            description=(
                "Record a task-scoped attempt (what was tried and how it went). "
                "Returns the created attempt id as JSON."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task this attempt belongs to.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Short summary of the attempt.",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ATTEMPT_KIND_VALUES,
                        "default": AttemptKind.OTHER.value,
                        "description": "Attempt kind.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ATTEMPT_STATUS_VALUES,
                        "default": AttemptStatus.TRIED.value,
                        "description": "Attempt status.",
                    },
                    "reasoning_summary": {
                        "type": "string",
                        "description": "Why this attempt seemed worth trying.",
                    },
                    "files_touched": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "File paths touched during the attempt.",
                    },
                },
                "required": ["task_id", "summary"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="record_memory",
            title="Record ONMC memory",
            description=(
                "Write a durable manual memory entry that ingest never overwrites. "
                "The entry is recorded for human review, NOT activated: it is not "
                "auto-injected into future prompts until a human promotes it, and the "
                "response reports that in 'activated'. Content is scanned and refused "
                "if it embeds injection payloads or credentials. "
                "Returns the created memory id as JSON."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": MEMORY_KIND_VALUES,
                        "description": "Memory kind.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Short memory title.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "What future agents should remember.",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Optional task to link this memory to.",
                    },
                },
                "required": ["kind", "title", "summary"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="list_tasks",
            title="List ONMC tasks",
            description="List all stored tasks as a JSON array of id, title, status, and branch.",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        Tool(
            name="guard_task",
            title="Guard task against known dead-ends",
            description=(
                "Surface recorded dead-ends (failed_approach memories and did_not_work "
                "artifacts) for a task. Call this before acting to avoid repeating known "
                "failures. Returns a ranked list of what was tried and why it failed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The task description to check for known dead-ends.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 8,
                        "description": "Maximum number of dead-end entries to return.",
                    },
                },
                "required": ["task"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="get_coverage",
            title="Knowledge-gap dashboard",
            description=(
                "Return a compact knowledge-coverage dashboard: overall coverage %, "
                "the worst-covered subsystems, and the top uncovered hotspot files. "
                "Use this to find blind spots — high-churn files with no memory coverage. "
                "No arguments required."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        Tool(
            name="get_digest",
            title="Knowledge changelog since a git ref",
            description=(
                "Return a compact knowledge changelog of everything learned since a given "
                "git ref (tag, branch, or commit SHA). Useful for 'what did this repo "
                "learn recently?' queries. Returns entries grouped by memory kind."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "since": {
                        "type": "string",
                        "description": (
                            "Git ref (tag, branch, or commit SHA) marking the starting point "
                            "of the changelog. Example: 'main', 'v1.2.0', or a short SHA."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "default": 50,
                        "description": "Maximum number of digest entries to return in total.",
                    },
                },
                "required": ["since"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="get_skills",
            title="Discover relevant how-to skills",
            description=(
                "Return portable skills stored in the repo brain, optionally ranked against "
                "a free-text query and/or tags. Use this to pull a relevant how-to skill "
                "mid-task without shelling out. No query → returns all auto_inject skills "
                "ordered by confidence. With a query, relevant skills are ranked first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Optional free-text query (e.g. 'testing cache invalidation'). "
                            "When supplied, skills are ranked by relevance to the query."
                        ),
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional tag list to boost skills that share these tags."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 10,
                        "description": "Maximum number of skills to return.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="get_profile",
            title="Evolving user profile",
            description=(
                "Return the evolving user profile derived from cross-repo user memories "
                "(~/.onmc/user.db). Provides preferences, coding patterns, frequent mistakes "
                "to avoid, and tooling signals. Call this at session start to prime context "
                "with the user's known habits and anti-patterns. No required arguments."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "max_items": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 5,
                        "description": (
                            "Maximum entries per bucket (preferences, patterns, "
                            "frequent_mistakes, tooling). Defaults to 5."
                        ),
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="ask",
            title="Ask the repo brain a natural-language question",
            description=(
                "Query the repo memory brain with a natural-language question and get ranked, "
                "cited memory entries back. Offline-safe: no LLM synthesis is performed — "
                "results are deterministically ranked by token overlap and confidence. "
                "Use this to ask factual questions about past decisions, known gotchas, "
                "invariants, or any stored knowledge about the codebase."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": (
                            "Natural-language question to ask the repo brain, "
                            "e.g. 'Why do we use X instead of Y?' or "
                            "'What are the known gotchas with the cache module?'"
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 8,
                        "description": "Maximum number of ranked memory entries to return.",
                    },
                },
                "required": ["question"],
                "additionalProperties": False,
            },
        ),
    ]


def call_onmc_tool(
    repo: OnmcRepo,
    name: str,
    arguments: dict[str, Any] | None,
) -> list[TextContent]:
    """Dispatch an ONMC MCP tool call and return its text payload."""
    args: dict[str, Any] = arguments or {}
    if name == "recall":
        text = _recall(repo, args)
    elif name == "search_memory":
        text = _search_memory(repo, args)
    elif name == "get_brief":
        text = _get_brief(repo, args)
    elif name == "record_attempt":
        text = _record_attempt(repo, args)
    elif name == "record_memory":
        text = _record_memory(repo, args)
    elif name == "list_tasks":
        text = _list_tasks(repo)
    elif name == "guard_task":
        text = _guard_task(repo, args)
    elif name == "get_coverage":
        text = _get_coverage(repo)
    elif name == "get_digest":
        text = _get_digest(repo, args)
    elif name == "get_skills":
        text = _get_skills(repo, args)
    elif name == "get_profile":
        text = _get_profile(repo, args)
    elif name == "ask":
        text = _ask(repo, args)
    else:
        msg = f"Unknown ONMC tool: {name}"
        raise ValueError(msg)
    return [TextContent(type="text", text=text)]


def score_memory(query: str, files: list[str], memory: MemoryEntry) -> float:
    """Score one memory against a query with deterministic token overlap."""
    query_tokens = set(tokenize(query))
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
    score = float(len(overlap) * 5)
    if overlap and memory.kind in _PRIORITY_MEMORY_KINDS:
        score += 2.5
    if memory.kind == MemoryKind.HOTSPOT:
        score += 1.0
    if any(token in memory.source_ref.lower() for token in query_tokens):
        score += 2.0
    if files:
        file_tokens = set(tokenize(" ".join(files)))
        score += float(len(file_tokens & haystack_tokens) * 4)
        if any(path in memory.source_ref or memory.source_ref in path for path in files):
            score += 4.0
    score += memory.confidence + (memory.feedback_score * 0.2)
    return score


def _recall(repo: OnmcRepo, args: dict[str, Any]) -> str:
    from oh_no_my_claudecode.recall.compiler import compile_recall

    query = _require_str(args, "query")
    limit = _optional_int(args, "limit", default=_DEFAULT_SEARCH_LIMIT)
    if limit < 1:
        msg = "Argument 'limit' must be a positive integer."
        raise ValueError(msg)

    _, _, storage = repo._service._load_context()
    result = compile_recall(storage, query, limit=limit)

    payload = {
        "query": result.query,
        "has_matches": result.has_matches,
        "no_data_hint": result.no_data_hint if not result.has_matches else "",
        "entries": [
            _recall_entry_dict(entry)
            for entry in result.entries
        ],
    }
    return _json_text(payload)


def _recall_entry_dict(entry: object) -> dict[str, object]:
    """Serialize one RecallEntry to a dict, including provenance + score summary."""
    # Import lazily to avoid circular import at module load time.
    from oh_no_my_claudecode.recall.compiler import RecallEntry  # noqa: PLC0415

    if not isinstance(entry, RecallEntry):
        msg = f"Expected RecallEntry, got {type(entry).__name__}"
        raise TypeError(msg)
    row: dict[str, object] = {
        "memory_id": entry.memory_id,
        "title": entry.title,
        "what_happened": entry.what_happened,
        "resolution": entry.resolution,
        "source_ref": entry.source_ref,
        "confidence": entry.confidence,
        "relevance": round(entry.relevance, 3),
        "kind": entry.kind,
    }
    # Provenance citation — omit when empty.
    if entry.citation:
        row["provenance"] = entry.citation
    # Compact score summary — omit when breakdown is absent.
    bd = entry.score_breakdown
    if bd is not None:
        row["why"] = {
            "final": round(bd.final_score, 3),
            "overlap": round(bd.overlap_ratio, 3),
            "boost": round(bd.kind_boost, 2),
        }
    return row


def _search_memory(repo: OnmcRepo, args: dict[str, Any]) -> str:
    query = _require_str(args, "query")
    kind = _optional_str(args, "kind")
    if kind is not None and kind not in MEMORY_KIND_VALUES:
        msg = f"Argument 'kind' must be one of: {', '.join(MEMORY_KIND_VALUES)}."
        raise ValueError(msg)
    files = _optional_str_list(args, "files")
    limit = _optional_int(args, "limit", default=_DEFAULT_SEARCH_LIMIT)
    if limit < 1:
        msg = "Argument 'limit' must be a positive integer."
        raise ValueError(msg)

    from oh_no_my_claudecode.models import MemoryKind as _MemoryKind

    records = repo.memory.list(kind=kind) if kind else repo.memory.list()
    memories = [record for record in records if isinstance(record, MemoryEntry)]

    # Hybrid candidate retrieval: use FTS5-backed search_memories to surface
    # additional candidates beyond the full list, then rerank with score_memory.
    fts_ids: set[str] = set()
    if len(query) >= _MIN_QUERY_FOR_FTS:
        try:
            _, _, storage = repo._service._load_context()
            kind_filter = _MemoryKind(kind) if kind else None
            fts_hits = storage.search_memories(query=query, kind=kind_filter, limit=limit * 4)
            known_ids = {m.id for m in memories}
            for hit in fts_hits:
                fts_ids.add(hit.id)
                if hit.id not in known_ids:
                    memories.append(hit)
                    known_ids.add(hit.id)
        except Exception:  # noqa: BLE001, S110
            # FTS failure must never break MCP responses.
            pass

    ranked: list[tuple[float, MemoryEntry]] = []
    for memory in memories:
        if memory.feedback_score <= -0.5 or memory.confidence <= 0.0:
            continue
        base_score = score_memory(query, files, memory)
        # Small bonus for FTS-surfaced memories to reflect the relevance signal.
        adjusted = base_score + (1.0 if memory.id in fts_ids else 0.0)
        ranked.append((adjusted, memory))
    ranked.sort(key=lambda item: (-item[0], item[1].title))

    # Apply semantic reranking when embeddings are enabled.  The reranker
    # selects the most relevant memories from the candidate pool; we then
    # re-sort by raw lexical score so the "relevance" field in the JSON output
    # remains a monotone descending sequence (preserving the existing API
    # contract for callers who rely on sorted relevance scores).
    positive = [(score, memory) for score, memory in ranked if score > 0]
    # Build a score lookup from the pre-rerank lexical scores (used to emit a
    # monotone-descending "relevance" field in the JSON output regardless of
    # the order introduced by semantic reranking).
    score_by_id: dict[str, float] = {m.id: s for s, m in positive}
    if positive:
        pos_memories = [m for _, m in positive]
        pos_scores = [s for s, _ in positive]
        try:
            _, _, storage = repo._service._load_context()
            pos_memories = rerank_with_embeddings(pos_memories, query, pos_scores, storage)
        except Exception:  # noqa: BLE001, S110
            pass  # rerank failure must never break MCP responses
        # Re-sort the reranked selection by raw lexical score so that the
        # "relevance" field stays monotone-descending in the JSON output.
        top_memories = sorted(
            pos_memories[:limit],
            key=lambda m: (-score_by_id.get(m.id, 0.0), m.title),
        )
    else:
        top_memories = []

    results = [
        {
            "id": memory.id,
            "kind": memory.kind.value,
            "title": memory.title,
            "summary": memory.summary,
            "source_ref": memory.source_ref,
            "confidence": memory.confidence,
            "feedback_score": memory.feedback_score,
            "relevance": round(score_by_id.get(memory.id, score_memory(query, files, memory)), 3),
        }
        for memory in top_memories
    ]
    return _json_text(results)


def _get_brief(repo: OnmcRepo, args: dict[str, Any]) -> str:
    task = _require_str(args, "task")
    return repo.brief(task).markdown


def _record_attempt(repo: OnmcRepo, args: dict[str, Any]) -> str:
    task_id = _require_str(args, "task_id")
    summary = _require_str(args, "summary")
    kind = _optional_str(args, "kind") or AttemptKind.OTHER.value
    if kind not in ATTEMPT_KIND_VALUES:
        msg = f"Argument 'kind' must be one of: {', '.join(ATTEMPT_KIND_VALUES)}."
        raise ValueError(msg)
    status = _optional_str(args, "status") or AttemptStatus.TRIED.value
    if status not in ATTEMPT_STATUS_VALUES:
        msg = f"Argument 'status' must be one of: {', '.join(ATTEMPT_STATUS_VALUES)}."
        raise ValueError(msg)
    attempt = repo.task.add_attempt(
        task_id,
        summary=summary,
        kind=kind,
        status=status,
        reasoning_summary=_optional_str(args, "reasoning_summary"),
        files_touched=_optional_str_list(args, "files_touched"),
    )
    return _json_text(
        {
            "attempt_id": attempt.attempt_id,
            "task_id": attempt.task_id,
            "status": attempt.status.value,
        }
    )


def _scan_model_text(*parts: str) -> tuple[str, ...]:
    """Scan model-authored *parts* and return tripped sanitizer rule ids.

    Fails closed: if the sanitizer cannot run, the content counts as dirty, so a
    hostile payload can never be persisted through a broken scanner.  Only rule
    ids and titles are returned — never the matched text, which may itself be a
    credential.
    """
    try:
        from oh_no_my_claudecode.learning import sanitize

        content = "\n".join(parts)
        return tuple(f"{f.rule_id} ({f.title})" for f in sanitize.scan(content))
    except Exception as exc:  # noqa: BLE001
        return (f"sanitizer-unavailable: {type(exc).__name__}: {exc}",)


def _record_memory(repo: OnmcRepo, args: dict[str, Any]) -> str:
    """Record a memory entry authored by the *model*.

    This is the one ONMC write path where the content, the kind, the title and
    the summary are all chosen by the model itself, so all of it is untrusted
    input and none of it carries a promotion record.  Three gates apply:

    1. **Kill switch.** ``ONMC_LEARNING=0`` refuses the write outright, loudly
       (the tool returns an error rather than pretending to have saved).  The
       check fails closed.
    2. **Untrusted text.** Title and summary are scanned with the learning
       sanitizer; prompt-injection payloads, chat-template markers and
       credentials are refused.  Without this, a model (or anything feeding it,
       such as a poisoned file or web page) could park an instruction payload in
       durable repo memory for a later agent to read as trusted context.
    3. **No activation without promotion.** The entry is persisted with the
       :data:`~oh_no_my_claudecode.hooks.prompt_recall.UNPROMOTED_SOURCE_PREFIX`
       ``source_ref``, so prompt-recall will not auto-inject it.  It stays fully
       readable through the deliberate, human-driven surfaces (``onmc memory
       list``/``show``, ``recall``, ``get_brief``) — recording is allowed,
       self-activation is not.  The response reports this honestly via
       ``activated`` / ``activation_reasons`` so the model is not misled into
       believing it just taught the repo something.
    """
    kind = _require_str(args, "kind")
    if kind not in MEMORY_KIND_VALUES:
        msg = f"Argument 'kind' must be one of: {', '.join(MEMORY_KIND_VALUES)}."
        raise ValueError(msg)
    title = _require_str(args, "title")
    summary = _require_str(args, "summary")
    task_id = _optional_str(args, "task_id")

    from oh_no_my_claudecode.hooks.prompt_recall import (
        learning_enabled,
        unpromoted_source_ref,
    )

    if not learning_enabled():
        msg = (
            "record_memory refused: learning is disabled (ONMC_LEARNING). "
            "No memory was written."
        )
        raise ValueError(msg)

    findings = _scan_model_text(title, summary)
    if findings:
        msg = (
            "record_memory refused: model-supplied content tripped the learning "
            f"sanitizer ({'; '.join(findings)}). No memory was written."
        )
        raise ValueError(msg)

    source_ref = unpromoted_source_ref(
        f"mcp:record_memory:{task_id}" if task_id else "mcp:record_memory"
    )
    record = repo._service.add_manual_memory(
        kind=MemoryKind(kind),
        title=title,
        summary=summary,
        task_id=task_id,
        source_ref=source_ref,
    )
    if not isinstance(record, MemoryEntry):
        msg = f"Expected a manual memory entry for kind: {kind}"
        raise ValueError(msg)
    return _json_text(
        {
            "memory_id": record.id,
            "kind": record.kind.value,
            "source_type": record.source_type.value,
            "activated": False,
            "activation_reasons": (
                "not-promoted: model-authored memory is recorded for review and is "
                "not auto-injected into future prompts until a human promotes it"
            ),
        }
    )


def _list_tasks(repo: OnmcRepo) -> str:
    tasks = [
        {
            "id": task.task_id,
            "title": task.title,
            "status": task.status.value,
            "branch": task.branch,
        }
        for task in repo.task.list()
    ]
    return _json_text(tasks)


def _guard_task(repo: OnmcRepo, args: dict[str, Any]) -> str:
    from oh_no_my_claudecode.guard.compiler import compile_guard

    task = _require_str(args, "task")
    limit = _optional_int(args, "limit", default=8)
    if limit < 1:
        msg = "Argument 'limit' must be a positive integer."
        raise ValueError(msg)

    _, _, storage = repo._service._load_context()
    result = compile_guard(storage, task, limit=limit)

    payload = {
        "task": result.task,
        "has_dead_ends": result.has_dead_ends,
        "entries": [
            {
                "memory_id": entry.memory_id,
                "title": entry.title,
                "what_was_tried": entry.what_was_tried,
                "why_it_failed": entry.why_it_failed,
                "related_files": entry.related_files,
                "source_ref": entry.source_ref,
                "confidence": entry.confidence,
            }
            for entry in result.entries
        ],
    }
    return _json_text(payload)


def _get_coverage(repo: OnmcRepo) -> str:
    from oh_no_my_claudecode.coverage.compiler import compile_coverage

    repo_root, _, storage = repo._service._load_context()
    report = compile_coverage(storage, repo_root)

    # Compact view: overall %, worst subsystems (up to 5), top uncovered hotspots (up to 5).
    worst_subsystems = [
        {
            "subsystem": row.subsystem,
            "coverage_pct": row.coverage_pct,
            "covered_files": row.covered_files,
            "total_files": row.total_files,
            "total_churn": row.total_churn,
        }
        for row in report.subsystem_rows[:5]
    ]
    top_gaps = [
        {
            "path": gap.path,
            "subsystem": gap.subsystem,
            "churn": gap.churn,
            "recent_churn": gap.recent_churn,
        }
        for gap in report.top_gaps[:5]
    ]
    payload = {
        "overall_coverage_pct": report.overall_coverage_pct,
        "covered_files": report.covered_files,
        "uncovered_files": report.uncovered_files,
        "total_files": report.total_files,
        "memory_count": report.memory_count,
        "worst_subsystems": worst_subsystems,
        "top_uncovered_hotspots": top_gaps,
    }
    return _json_text(payload)


def _get_digest(repo: OnmcRepo, args: dict[str, Any]) -> str:
    from oh_no_my_claudecode.digest.compiler import _KIND_LABELS, _SECTION_ORDER, compile_digest

    since = _require_str(args, "since")
    limit = _optional_int(args, "limit", default=50)
    if limit < 1:
        msg = "Argument 'limit' must be a positive integer."
        raise ValueError(msg)

    repo_root, _, storage = repo._service._load_context()
    try:
        result = compile_digest(repo_root, storage, since)
    except ValueError as exc:
        return _json_text({"error": str(exc), "since": since})

    # Compact serialization: meta + grouped entries (truncated to limit).
    sections: list[dict[str, object]] = []
    remaining = limit
    for kind in _SECTION_ORDER:
        bucket = result.by_kind.get(kind)
        if not bucket or remaining <= 0:
            continue
        truncated_bucket = bucket[:remaining]
        remaining -= len(truncated_bucket)
        sections.append(
            {
                "kind": kind.value,
                "label": _KIND_LABELS.get(kind, kind.value),
                "entries": [
                    {
                        "id": entry.id,
                        "title": entry.title,
                        "summary": entry.summary,
                        "change_type": entry.change_type,
                    }
                    for entry in truncated_bucket
                ],
            }
        )

    payload: dict[str, object] = {
        "since_ref": result.since_ref,
        "since_short": result.since_short,
        "since_date": result.since_date,
        "head_short": result.head_short,
        "head_date": result.head_date,
        "source": result.source,
        "total": result.total,
        "sections": sections,
    }
    if result.fallback_reason:
        payload["fallback_reason"] = result.fallback_reason
    return _json_text(payload)


def _get_skills(repo: OnmcRepo, args: dict[str, Any]) -> str:
    from oh_no_my_claudecode.skill.promoter import rank_skills

    query = _optional_str(args, "query")
    tags = _optional_str_list(args, "tags")
    limit = _optional_int(args, "limit", default=10)
    if limit < 1:
        msg = "Argument 'limit' must be a positive integer."
        raise ValueError(msg)

    _, _, storage = repo._service._load_context()
    all_skills = storage.list_skills()

    if query:
        # Tokenize query into tags for rank_skills tag-overlap scoring.
        query_tags = list(tokenize(query)) + tags
        ranked = rank_skills(all_skills, tags=query_tags, files=[])
    elif tags:
        ranked = rank_skills(all_skills, tags=tags, files=[])
    else:
        # No query: return only auto_inject skills ordered by confidence (storage default).
        ranked = [sk for sk in all_skills if sk.auto_inject]

    results = [
        {
            "id": sk.id,
            "name": sk.name,
            "trigger": sk.trigger,
            "body": sk.body[:500] if len(sk.body) > 500 else sk.body,
            "tags": sk.tags,
            "confidence": sk.confidence,
            "success_rate": round(sk.success_rate, 3),
            "auto_inject": sk.auto_inject,
        }
        for sk in ranked[:limit]
    ]
    return _json_text(results)


def _get_profile(repo: OnmcRepo, args: dict[str, Any]) -> str:
    from oh_no_my_claudecode.profile.compiler import compile_user_profile

    max_items = _optional_int(args, "max_items", default=5)
    if max_items < 1:
        msg = "Argument 'max_items' must be a positive integer."
        raise ValueError(msg)

    try:
        memories = repo._service._load_user_memories()
    except Exception:  # noqa: BLE001
        memories = []

    profile = compile_user_profile(memories, max_items=max_items)

    payload: dict[str, object] = {
        "preferences": [{"title": t, "summary": s} for t, s in profile.preferences],
        "patterns": [{"title": t, "summary": s} for t, s in profile.patterns],
        "frequent_mistakes": [{"title": t, "summary": s} for t, s in profile.frequent_mistakes],
        "tooling": [{"title": t, "summary": s} for t, s in profile.tooling],
        "derived_from": profile.derived_from,
        "salient_memory_ids": profile.salient_memory_ids,
    }
    return _json_text(payload)


def _ask(repo: OnmcRepo, args: dict[str, Any]) -> str:
    from oh_no_my_claudecode.ask.compiler import compile_ask

    question = _require_str(args, "question")
    limit = _optional_int(args, "limit", default=8)
    if limit < 1:
        msg = "Argument 'limit' must be a positive integer."
        raise ValueError(msg)

    repo_root, _, storage = repo._service._load_context()
    result = compile_ask(storage, repo_root, question, limit=limit, provider=None)

    entries: list[dict[str, object]] = []
    for entry in result.entries:
        row: dict[str, object] = {
            "memory_id": entry.memory_id,
            "title": entry.title,
            "kind": entry.kind,
            "relevance": round(entry.relevance, 3),
        }
        if entry.citation:
            row["provenance"] = entry.citation
        entries.append(row)

    payload: dict[str, object] = {
        "question": result.question,
        "entries": entries,
    }
    if result.no_data_hint:
        payload["no_data_hint"] = result.no_data_hint
    if result.answer is not None:
        payload["answer"] = result.answer
    return _json_text(payload)


def _is_json_format() -> bool:
    """Return True when the caller has opted into JSON output via env var."""
    return os.environ.get(_ENV_FORMAT, "").strip().lower() == "json"


def _serialize(payload: object) -> str:
    """Serialize *payload* to TOON (default) or JSON (opt-in)."""
    if _is_json_format():
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return to_toon(payload)


def _json_text(payload: object) -> str:
    return _serialize(payload)


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"Argument '{key}' must be a non-empty string."
        raise ValueError(msg)
    return value


def _optional_str(args: dict[str, Any], key: str) -> str | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"Argument '{key}' must be a string."
        raise ValueError(msg)
    return value


def _optional_str_list(args: dict[str, Any], key: str) -> list[str]:
    value = args.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        msg = f"Argument '{key}' must be an array of strings."
        raise ValueError(msg)
    return [str(item) for item in value]


def _optional_int(args: dict[str, Any], key: str, *, default: int) -> int:
    value = args.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"Argument '{key}' must be an integer."
        raise ValueError(msg)
    return int(value)
