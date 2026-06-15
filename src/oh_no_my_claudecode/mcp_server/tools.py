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
    ]


def call_onmc_tool(
    repo: OnmcRepo,
    name: str,
    arguments: dict[str, Any] | None,
) -> list[TextContent]:
    """Dispatch an ONMC MCP tool call and return its text payload."""
    args: dict[str, Any] = arguments or {}
    if name == "search_memory":
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


def _record_memory(repo: OnmcRepo, args: dict[str, Any]) -> str:
    kind = _require_str(args, "kind")
    if kind not in MEMORY_KIND_VALUES:
        msg = f"Argument 'kind' must be one of: {', '.join(MEMORY_KIND_VALUES)}."
        raise ValueError(msg)
    title = _require_str(args, "title")
    summary = _require_str(args, "summary")
    record = repo.memory.add(
        type=kind,
        title=title,
        summary=summary,
        task_id=_optional_str(args, "task_id"),
    )
    if not isinstance(record, MemoryEntry):
        msg = f"Expected a manual memory entry for kind: {kind}"
        raise ValueError(msg)
    return _json_text(
        {
            "memory_id": record.id,
            "kind": record.kind.value,
            "source_type": record.source_type.value,
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
