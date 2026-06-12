from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from oh_no_my_claudecode import init
from oh_no_my_claudecode.api import OnmcRepo
from oh_no_my_claudecode.mcp_server.resources import read_onmc_resource
from oh_no_my_claudecode.mcp_server.server import build_mcp_server, run_mcp_server
from oh_no_my_claudecode.mcp_server.tools import call_onmc_tool, list_onmc_tools

EXPECTED_TOOL_NAMES = {
    "search_memory",
    "get_brief",
    "record_attempt",
    "record_memory",
    "list_tasks",
}


def _resource_text(repo_path: Path, uri: str) -> str:
    repo = init(repo_path)
    contents = read_onmc_resource(repo, uri)
    return contents[0].content


def test_mcp_server_initializes_without_error(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    server = build_mcp_server(sample_repo)

    assert server is not None


def test_status_resource_returns_valid_json(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    payload = json.loads(_resource_text(sample_repo, "onmc://status"))

    assert payload["repo_root"] == sample_repo.as_posix()


def test_memory_list_resource_returns_valid_json(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    payload = json.loads(_resource_text(sample_repo, "onmc://memory/list"))

    assert payload["memories"]


def test_brief_resource_returns_non_empty_markdown(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    text = _resource_text(sample_repo, "onmc://brief")

    assert "# ONMC Task Brief" in text


def test_run_mcp_server_prints_startup_message_to_stderr_only(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    def fake_run(coro: asyncio.Future[object]) -> None:
        coro.close()

    stdout = SimpleNamespace(buffer="")
    stderr = SimpleNamespace(buffer="")

    def write_stdout(text: str) -> int:
        stdout.buffer += text
        return len(text)

    def write_stderr(text: str) -> int:
        stderr.buffer += text
        return len(text)

    monkeypatch.setattr(sys, "stdout", SimpleNamespace(write=write_stdout, flush=lambda: None))
    monkeypatch.setattr(sys, "stderr", SimpleNamespace(write=write_stderr, flush=lambda: None))
    monkeypatch.setattr("oh_no_my_claudecode.mcp_server.server.asyncio.run", fake_run)

    run_mcp_server(sample_repo)

    assert "ONMC MCP server running." in stderr.buffer
    assert '"command": "onmc"' in stderr.buffer
    assert stdout.buffer == ""


def _tool_text(repo: OnmcRepo, name: str, arguments: dict[str, object]) -> str:
    contents = call_onmc_tool(repo, name, arguments)
    assert len(contents) == 1
    assert contents[0].type == "text"
    return contents[0].text


def test_list_tools_exposes_expected_names_and_schemas() -> None:
    tools = list_onmc_tools()
    by_name = {tool.name: tool for tool in tools}

    assert set(by_name) == EXPECTED_TOOL_NAMES
    assert by_name["search_memory"].inputSchema["required"] == ["query"]
    assert "decision" in by_name["search_memory"].inputSchema["properties"]["kind"]["enum"]
    assert by_name["get_brief"].inputSchema["required"] == ["task"]
    assert by_name["record_attempt"].inputSchema["required"] == ["task_id", "summary"]
    assert "tried" in by_name["record_attempt"].inputSchema["properties"]["status"]["enum"]
    assert by_name["record_memory"].inputSchema["required"] == ["kind", "title", "summary"]
    assert by_name["list_tasks"].inputSchema["properties"] == {}


def test_search_memory_ranks_seeded_store(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    repo.memory.add(
        type="gotcha",
        title="Cache invalidation gotcha",
        summary="Workers must always go through the cache boundary for invalidation.",
    )

    results = json.loads(
        _tool_text(repo, "search_memory", {"query": "cache invalidation boundary"})
    )

    assert results
    assert any(item["title"] == "Cache invalidation gotcha" for item in results)
    relevances = [item["relevance"] for item in results]
    assert relevances == sorted(relevances, reverse=True)
    for field in ("id", "kind", "title", "summary", "source_ref", "confidence", "feedback_score"):
        assert field in results[0]


def test_search_memory_respects_kind_filter_and_limit(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    repo.memory.add(
        type="gotcha",
        title="Cache invalidation gotcha",
        summary="Workers must always go through the cache boundary for invalidation.",
    )

    results = json.loads(
        _tool_text(
            repo,
            "search_memory",
            {"query": "cache invalidation", "kind": "gotcha", "limit": 1},
        )
    )

    assert len(results) == 1
    assert results[0]["kind"] == "gotcha"


def test_get_brief_returns_markdown(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    text = _tool_text(repo, "get_brief", {"task": "fix cache invalidation"})

    assert "# ONMC Task Brief" in text


def test_record_attempt_round_trips_through_storage(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    task = repo.task.start(title="Fix cache invalidation")

    payload = json.loads(
        _tool_text(
            repo,
            "record_attempt",
            {
                "task_id": task.task_id,
                "summary": "Tried routing workers through the cache boundary.",
                "kind": "fix_attempt",
                "status": "tried",
                "files_touched": ["src/cache.py"],
            },
        )
    )

    assert payload["task_id"] == task.task_id
    detail = json.loads(_resource_text(sample_repo, f"onmc://task/{task.task_id}"))
    stored = {attempt["attempt_id"]: attempt for attempt in detail["attempts"]}
    assert payload["attempt_id"] in stored
    assert stored[payload["attempt_id"]]["files_touched"] == ["src/cache.py"]


def test_record_memory_round_trips_as_protected_manual_entry(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)

    payload = json.loads(
        _tool_text(
            repo,
            "record_memory",
            {
                "kind": "decision",
                "title": "Keep the cache boundary",
                "summary": "Workers must never bypass the shared cache module.",
            },
        )
    )

    assert payload["source_type"] == "manual"
    stored = repo.memory.show(payload["memory_id"])
    assert stored is not None
    assert stored.title == "Keep the cache boundary"


def test_list_tasks_returns_id_title_status_branch(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    task = repo.task.start(title="Fix cache invalidation")

    payload = json.loads(_tool_text(repo, "list_tasks", {}))

    listed = {item["id"]: item for item in payload}
    assert task.task_id in listed
    assert listed[task.task_id]["title"] == "Fix cache invalidation"
    assert listed[task.task_id]["status"] == "active"
    assert "branch" in listed[task.task_id]


def test_unknown_tool_raises_clean_error(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)

    with pytest.raises(ValueError, match="Unknown ONMC tool: nope"):
        call_onmc_tool(repo, "nope", {})


def test_invalid_tool_arguments_raise_clean_errors(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)

    with pytest.raises(ValueError, match="Argument 'query' must be a non-empty string."):
        call_onmc_tool(repo, "search_memory", {})
    with pytest.raises(ValueError, match="Argument 'kind' must be one of"):
        call_onmc_tool(repo, "search_memory", {"query": "cache", "kind": "not-a-kind"})
    with pytest.raises(ValueError, match="Argument 'status' must be one of"):
        call_onmc_tool(
            repo,
            "record_attempt",
            {"task_id": "task-1", "summary": "x", "status": "not-a-status"},
        )
    with pytest.raises(ValueError, match="Argument 'files' must be an array of strings."):
        call_onmc_tool(repo, "search_memory", {"query": "cache", "files": "src/cache.py"})
