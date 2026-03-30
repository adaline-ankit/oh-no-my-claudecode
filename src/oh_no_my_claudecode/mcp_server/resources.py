from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse

from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import Resource, ResourceTemplate
from pydantic import AnyUrl

from oh_no_my_claudecode import init
from oh_no_my_claudecode.api import OnmcRepo
from oh_no_my_claudecode.models import TaskStatus


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

    text: str
    if uri == "onmc://brief":
        text = _current_brief_markdown(repo)
    elif uri == "onmc://memory/list":
        text = _json_text(
            {
                "memories": [_model_dump(record) for record in repo.memory.list()],
            }
        )
    elif parsed.netloc == "memory" and parsed.path == "/search":
        files = _query_list(parsed.query, "files")
        text = _json_text(
            {
                "results": [
                    _model_dump(record) for record in repo.memory.search(files)
                ],
            }
        )
    elif parsed.netloc == "memory" and parsed.path.startswith("/"):
        kind = parsed.path.lstrip("/")
        text = _json_text(
            {
                "memories": [
                    _model_dump(record) for record in repo.memory.list(kind=kind)
                ],
            }
        )
    elif uri == "onmc://tasks":
        text = _json_text({"tasks": [_model_dump(task) for task in repo.task.list()]})
    elif parsed.netloc == "task" and parsed.path.startswith("/"):
        task_id = parsed.path.lstrip("/")
        task = repo.task.show(task_id)
        if task is None:
            msg = f"Task not found: {task_id}"
            raise LookupError(msg)
        text = _json_text(
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
            }
        )
    elif uri == "onmc://snapshot/latest":
        text = _json_text(
            {
                "snapshot": _model_dump(repo._service.latest_compaction_snapshot()),
            }
        )
    elif uri == "onmc://status":
        text = _json_text(repo._service.status())
    else:
        msg = f"Unsupported ONMC resource URI: {uri}"
        raise ValueError(msg)

    mime_type = "text/markdown" if uri == "onmc://brief" else "application/json"
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


def _json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


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
