from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse

from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import Resource, ResourceTemplate
from pydantic import AnyUrl

from oh_no_my_claudecode import init
from oh_no_my_claudecode.api import OnmcRepo
from oh_no_my_claudecode.models import TaskStatus
from oh_no_my_claudecode.serialize import to_toon

# When set to "json", MCP resource responses are emitted as indented JSON
# instead of the default TOON compact format.
_ENV_FORMAT = "ONMC_MCP_FORMAT"


def list_onmc_resources() -> list[Resource]:
    """List the static ONMC MCP resources."""
    return [
        Resource(
            name="brief",
            title="Current ONMC brief",
            uri=cast(AnyUrl, "onmc://brief"),
            description="Compile the current brief as markdown.",
            mimeType="text/markdown",
        ),
        Resource(
            name="memory-list",
            title="All ONMC memory",
            uri=cast(AnyUrl, "onmc://memory/list"),
            description="Return all repo memories and task-derived artifacts as JSON.",
            mimeType="application/json",
        ),
        Resource(
            name="tasks",
            title="All ONMC tasks",
            uri=cast(AnyUrl, "onmc://tasks"),
            description="Return all stored task records as JSON.",
            mimeType="application/json",
        ),
        Resource(
            name="snapshot-latest",
            title="Latest compaction snapshot",
            uri=cast(AnyUrl, "onmc://snapshot/latest"),
            description="Return the most recent compaction snapshot as JSON.",
            mimeType="application/json",
        ),
        Resource(
            name="status",
            title="ONMC status",
            uri=cast(AnyUrl, "onmc://status"),
            description="Return repo root, ingest state, and memory counts as JSON.",
            mimeType="application/json",
        ),
    ]


def list_onmc_resource_templates() -> list[ResourceTemplate]:
    """List the parameterized ONMC MCP resource templates."""
    return [
        ResourceTemplate(
            name="memory-kind",
            title="ONMC memory by kind",
            uriTemplate="onmc://memory/{kind}",
            description="Return repo memories filtered by kind as JSON.",
            mimeType="application/json",
        ),
        ResourceTemplate(
            name="memory-search",
            title="ONMC memory search",
            uriTemplate="onmc://memory/search?files={files}",
            description="Return relevance-ranked memories for a comma-separated file list.",
            mimeType="application/json",
        ),
        ResourceTemplate(
            name="task-detail",
            title="ONMC task detail",
            uriTemplate="onmc://task/{id}",
            description="Return a single task with attempts, artifacts, and outputs as JSON.",
            mimeType="application/json",
        ),
    ]


def read_onmc_resource(repo: OnmcRepo, uri: str) -> list[ReadResourceContents]:
    """Read an ONMC MCP resource and return text payloads."""
    parsed = urlparse(uri)
    if parsed.scheme != "onmc":
        msg = f"Unsupported ONMC resource URI: {uri}"
        raise ValueError(msg)

    # Honour explicit ?format=json query param, or fall back to env var.
    fmt_param = _query_str(parsed.query, "format")
    use_json = (fmt_param == "json") or _is_json_env()
    # Reconstruct URI without the format query param for routing.
    routing_uri = _strip_format_param(uri)

    text: str
    if routing_uri == "onmc://brief":
        text = _current_brief_markdown(repo)
    elif routing_uri == "onmc://memory/list":
        text = _structured_text(
            {
                "memories": [_model_dump(record) for record in repo.memory.list()],
            },
            use_json=use_json,
        )
    elif parsed.netloc == "memory" and parsed.path == "/search":
        files = _query_list(parsed.query, "files")
        text = _structured_text(
            {
                "results": [
                    _model_dump(record) for record in repo.memory.search(files)
                ],
            },
            use_json=use_json,
        )
    elif parsed.netloc == "memory" and parsed.path.startswith("/"):
        kind = parsed.path.lstrip("/")
        text = _structured_text(
            {
                "memories": [
                    _model_dump(record) for record in repo.memory.list(kind=kind)
                ],
            },
            use_json=use_json,
        )
    elif routing_uri == "onmc://tasks":
        text = _structured_text(
            {"tasks": [_model_dump(task) for task in repo.task.list()]},
            use_json=use_json,
        )
    elif parsed.netloc == "task" and parsed.path.startswith("/"):
        task_id = parsed.path.lstrip("/")
        task = repo.task.show(task_id)
        if task is None:
            msg = f"Task not found: {task_id}"
            raise LookupError(msg)
        text = _structured_text(
            {
                "task": _model_dump(task),
                "attempts": [
                    _model_dump(item)
                    for item in repo._service.list_attempts_for_task(task_id)
                ],
                "artifacts": [
                    _model_dump(item)
                    for item in repo._service.list_memory_artifacts_for_task(task_id)
                ],
                "outputs": [
                    _model_dump(item) for item in repo._service.list_task_outputs_for_task(task_id)
                ],
            },
            use_json=use_json,
        )
    elif routing_uri == "onmc://snapshot/latest":
        text = _structured_text(
            {
                "snapshot": _model_dump(repo._service.latest_compaction_snapshot()),
            },
            use_json=use_json,
        )
    elif routing_uri == "onmc://status":
        text = _structured_text(repo._service.status(), use_json=use_json)
    else:
        msg = f"Unsupported ONMC resource URI: {uri}"
        raise ValueError(msg)

    if routing_uri == "onmc://brief":
        mime_type = "text/markdown"
    elif use_json:
        mime_type = "application/json"
    else:
        mime_type = "text/plain"
    return [ReadResourceContents(content=text, mime_type=mime_type)]


def default_repo(path: Path | str = ".") -> OnmcRepo:
    """Return an initialized ONMC repo handle for MCP requests."""
    return init(path)


def _current_brief_markdown(repo: OnmcRepo) -> str:
    tasks = repo.task.list()
    active_tasks = [task for task in tasks if task.status == TaskStatus.ACTIVE]
    if active_tasks:
        task = sorted(
            active_tasks,
            key=lambda item: ((item.started_at or item.created_at).isoformat(), item.task_id),
            reverse=True,
        )[0]
        task_text = f"{task.title}. {task.description}".strip()
    else:
        task_text = "Current repository context"
    return repo.brief(task_text).markdown


def _is_json_env() -> bool:
    """Return True when the caller has opted into JSON output via env var."""
    return os.environ.get(_ENV_FORMAT, "").strip().lower() == "json"


def _structured_text(payload: object, *, use_json: bool) -> str:
    """Serialize *payload* to TOON (default) or JSON (opt-in)."""
    if use_json:
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return to_toon(payload)


def _json_text(payload: object) -> str:
    return _structured_text(payload, use_json=_is_json_env())


def _model_dump(record: object) -> object:
    if record is None:
        return None
    if hasattr(record, "model_dump"):
        return record.model_dump(mode="json")
    return record


def _query_list(query: str, key: str) -> list[str]:
    values = parse_qs(query).get(key, [])
    if not values:
        return []
    return [item for item in values[0].split(",") if item]


def _query_str(query: str, key: str) -> str | None:
    values = parse_qs(query).get(key, [])
    return values[0] if values else None


def _strip_format_param(uri: str) -> str:
    """Return *uri* with the ``?format=...`` query parameter removed."""
    parsed = urlparse(uri)
    qs = parse_qs(parsed.query)
    qs.pop("format", None)
    if not qs:
        new_query = ""
    else:
        # Rebuild query string without format, preserving other params.
        parts = []
        for k, vals in qs.items():
            for v in vals:
                parts.append(f"{k}={v}")
        new_query = "&".join(parts)
    # Reconstruct — use _replace to avoid modifying ParseResult directly.
    rebuilt = parsed._replace(query=new_query)
    result = rebuilt.geturl()
    # Strip trailing "?" when query is empty.
    if result.endswith("?"):
        result = result[:-1]
    return result
