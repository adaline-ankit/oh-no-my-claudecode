from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from oh_no_my_claudecode import init
from oh_no_my_claudecode.mcp_server.resources import read_onmc_resource
from oh_no_my_claudecode.mcp_server.server import build_mcp_server, run_mcp_server


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
