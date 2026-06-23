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
from oh_no_my_claudecode.mcp_server.server import STARTUP_SNIPPET, build_mcp_server, run_mcp_server
from oh_no_my_claudecode.mcp_server.tools import call_onmc_tool, list_onmc_tools

EXPECTED_TOOL_NAMES = {
    "search_memory",
    "get_brief",
    "record_attempt",
    "record_memory",
    "list_tasks",
    "guard_task",
    "recall",
    "get_coverage",
    "get_digest",
    "get_skills",
    "get_profile",
    "ask",
}


@pytest.fixture()
def json_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force MCP output to JSON for tests that need to parse structured data."""
    monkeypatch.setenv("ONMC_MCP_FORMAT", "json")


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


def test_status_resource_returns_valid_json(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch, json_format: None
) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    payload = json.loads(_resource_text(sample_repo, "onmc://status"))

    assert payload["repo_root"] == sample_repo.as_posix()


def test_memory_list_resource_returns_valid_json(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch, json_format: None
) -> None:
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


def test_mcp_startup_snippet_mentions_project_scoped_config() -> None:
    assert "claude mcp add onmc -- onmc serve --mcp" in STARTUP_SNIPPET
    assert ".mcp.json" in STARTUP_SNIPPET
    assert "settings.json" not in STARTUP_SNIPPET


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
    # New tools
    assert by_name["get_coverage"].inputSchema["properties"] == {}
    assert by_name["get_coverage"].inputSchema.get("required", []) == []
    assert by_name["get_digest"].inputSchema["required"] == ["since"]
    assert "since" in by_name["get_digest"].inputSchema["properties"]
    assert "limit" in by_name["get_digest"].inputSchema["properties"]
    # get_skills — no required args
    assert by_name["get_skills"].inputSchema.get("required", []) == []
    assert "query" in by_name["get_skills"].inputSchema["properties"]
    assert "tags" in by_name["get_skills"].inputSchema["properties"]
    assert "limit" in by_name["get_skills"].inputSchema["properties"]
    assert by_name["get_skills"].inputSchema["properties"]["tags"]["type"] == "array"
    # get_profile — no required args, optional max_items
    assert by_name["get_profile"].inputSchema.get("required", []) == []
    assert "max_items" in by_name["get_profile"].inputSchema["properties"]
    assert by_name["get_profile"].inputSchema["properties"]["max_items"]["type"] == "integer"
    # ask — question required, limit optional
    assert by_name["ask"].inputSchema["required"] == ["question"]
    assert "question" in by_name["ask"].inputSchema["properties"]
    assert by_name["ask"].inputSchema["properties"]["question"]["type"] == "string"
    assert "limit" in by_name["ask"].inputSchema["properties"]
    assert by_name["ask"].inputSchema["properties"]["limit"]["type"] == "integer"


def test_search_memory_ranks_seeded_store(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch, json_format: None
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
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
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
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
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
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
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
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
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


# ---------------------------------------------------------------------------
# TOON default + JSON opt-in tests
# ---------------------------------------------------------------------------


def test_tools_return_toon_by_default(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """search_memory and list_tasks return TOON (not JSON) without ONMC_MCP_FORMAT=json."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.delenv("ONMC_MCP_FORMAT", raising=False)
    repo = init(sample_repo)
    repo.ingest()
    repo.memory.add(
        type="gotcha",
        title="Cache invalidation gotcha",
        summary="Workers must always go through the cache boundary for invalidation.",
    )

    search_text = _tool_text(repo, "search_memory", {"query": "cache invalidation boundary"})
    # TOON tabular output contains KEYS/ROW markers, not JSON punctuation.
    assert "KEYS" in search_text or search_text.strip().startswith("[")
    # Should NOT be valid top-level JSON array/object
    try:
        json.loads(search_text)
        is_json = True
    except json.JSONDecodeError:
        is_json = False
    assert not is_json, "Default output should be TOON, not JSON"

    task = repo.task.start(title="Test task")
    tasks_text = _tool_text(repo, "list_tasks", {})
    assert "KEYS" in tasks_text or "ROW" in tasks_text or task.task_id in tasks_text
    # Confirm it's not JSON
    try:
        json.loads(tasks_text)
        is_json_tasks = True
    except json.JSONDecodeError:
        is_json_tasks = False
    assert not is_json_tasks, "list_tasks default output should be TOON, not JSON"


def test_tools_return_json_when_env_set(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch, json_format: None
) -> None:
    """Tools return valid JSON when ONMC_MCP_FORMAT=json is set."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    repo.memory.add(
        type="gotcha",
        title="Cache gotcha",
        summary="A gotcha about caching.",
    )

    search_text = _tool_text(repo, "search_memory", {"query": "cache gotcha"})
    parsed = json.loads(search_text)
    assert isinstance(parsed, list)

    task = repo.task.start(title="JSON task")
    tasks_text = _tool_text(repo, "list_tasks", {})
    tasks_parsed = json.loads(tasks_text)
    assert isinstance(tasks_parsed, list)
    assert any(t["id"] == task.task_id for t in tasks_parsed)


def test_resources_return_toon_by_default(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Memory-list and tasks resources return TOON, not JSON, by default."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.delenv("ONMC_MCP_FORMAT", raising=False)
    repo = init(sample_repo)
    repo.ingest()

    memory_text = _resource_text(sample_repo, "onmc://memory/list")
    # Should not be valid JSON at top level
    try:
        json.loads(memory_text)
        is_json = True
    except json.JSONDecodeError:
        is_json = False
    assert not is_json, "memory/list default should be TOON, not JSON"

    # Check mime type is text/plain for TOON
    repo2 = init(sample_repo)
    contents = read_onmc_resource(repo2, "onmc://memory/list")
    assert contents[0].mime_type == "text/plain"


def test_resources_return_json_with_format_query_param(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resources return valid JSON when ?format=json is appended to the URI."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.delenv("ONMC_MCP_FORMAT", raising=False)
    repo = init(sample_repo)
    repo.ingest()

    # Use ?format=json query param
    contents = read_onmc_resource(repo, "onmc://memory/list?format=json")
    text = contents[0].content
    payload = json.loads(text)
    assert "memories" in payload
    assert contents[0].mime_type == "application/json"

    # Tasks resource
    task = repo.task.start(title="Format param task")
    contents2 = read_onmc_resource(repo, "onmc://tasks?format=json")
    tasks_payload = json.loads(contents2[0].content)
    assert "tasks" in tasks_payload
    assert any(t["task_id"] == task.task_id for t in tasks_payload["tasks"])


def test_resources_return_json_with_env_var(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch, json_format: None
) -> None:
    """Resources return JSON when ONMC_MCP_FORMAT=json env var is set."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    contents = read_onmc_resource(repo, "onmc://status")
    payload = json.loads(contents[0].content)
    assert "repo_root" in payload
    assert contents[0].mime_type == "application/json"


def test_brief_resource_always_returns_markdown(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_brief and the brief resource always return markdown regardless of format env."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.delenv("ONMC_MCP_FORMAT", raising=False)
    repo = init(sample_repo)
    repo.ingest()

    # Brief tool — always markdown
    brief_text = _tool_text(repo, "get_brief", {"task": "fix cache"})
    assert "# ONMC Task Brief" in brief_text

    # Brief resource — always markdown
    contents = read_onmc_resource(repo, "onmc://brief")
    assert "# ONMC Task Brief" in contents[0].content
    assert contents[0].mime_type == "text/markdown"


def test_record_attempt_toon_contains_ids(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """record_attempt returns a TOON dict containing the attempt and task IDs."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.delenv("ONMC_MCP_FORMAT", raising=False)
    repo = init(sample_repo)
    task = repo.task.start(title="TOON task")

    text = _tool_text(
        repo,
        "record_attempt",
        {"task_id": task.task_id, "summary": "Testing TOON output."},
    )
    # TOON dict output has "key: value" lines
    assert task.task_id in text
    assert "attempt_id" in text or "attempt" in text


def test_record_memory_toon_contains_id(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """record_memory returns TOON dict containing the memory_id field."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.delenv("ONMC_MCP_FORMAT", raising=False)
    repo = init(sample_repo)

    text = _tool_text(
        repo,
        "record_memory",
        {"kind": "decision", "title": "TOON is better", "summary": "Saves tokens."},
    )
    assert "memory_id" in text
    assert "manual" in text  # source_type


# ---------------------------------------------------------------------------
# Recall tool: provenance citation + score breakdown in MCP output
# ---------------------------------------------------------------------------


def _seed_failed_approach_for_mcp(repo: OnmcRepo) -> str:
    """Seed a FAILED_APPROACH memory into *repo* and return its id."""
    from oh_no_my_claudecode.models import MemoryKind, SourceType
    from oh_no_my_claudecode.models.memory import MemoryEntry
    from oh_no_my_claudecode.utils.text import stable_id
    from oh_no_my_claudecode.utils.time import utc_now

    now = utc_now()
    entry = MemoryEntry(
        id=stable_id(
            MemoryKind.FAILED_APPROACH.value,
            "TypeError null access mcp",
            "TypeError accessing null in mcp test.",
            "test:mcp",
            prefix="mcp",
        ),
        kind=MemoryKind.FAILED_APPROACH,
        title="TypeError null access mcp",
        summary="TypeError accessing null property in mcp test code.",
        details="Guard with null check before access.",
        source_type=SourceType.MANUAL,
        source_ref="test:mcp",
        tags=["typeerror", "null", "mcp"],
        confidence=0.85,
        created_at=now,
        updated_at=now,
    )
    _, _, storage = repo._service._load_context()
    storage.upsert_memories([entry])
    return entry.id


def test_recall_tool_json_includes_provenance_and_why(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """MCP recall result entries include 'provenance' and 'why' fields in JSON mode."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    mem_id = _seed_failed_approach_for_mcp(repo)

    text = _tool_text(
        repo,
        "recall",
        {"query": "TypeError accessing null property mcp test", "limit": 5},
    )
    payload = json.loads(text)

    assert payload["has_matches"]
    entries = payload["entries"]
    match = next((e for e in entries if e["memory_id"] == mem_id), None)
    assert match is not None, f"Expected {mem_id!r} in entries: {entries}"

    # provenance must be present and non-empty (SourceType.MANUAL → "manual" in string)
    assert "provenance" in match, "Entry must include 'provenance' field"
    assert match["provenance"], "provenance must be non-empty"
    assert "manual" in match["provenance"]

    # why must be present with the three compact sub-fields
    assert "why" in match, "Entry must include 'why' field"
    why = match["why"]
    assert "final" in why
    assert "overlap" in why
    assert "boost" in why
    assert isinstance(why["final"], float)
    assert why["final"] > 0.0
    assert why["overlap"] > 0.0
    assert why["overlap"] <= 1.0
    assert why["boost"] >= 1.0


def test_recall_tool_toon_includes_provenance_and_why(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP recall result includes provenance and why in TOON (default) format."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.delenv("ONMC_MCP_FORMAT", raising=False)
    repo = init(sample_repo)
    repo.ingest()
    _seed_failed_approach_for_mcp(repo)

    text = _tool_text(
        repo,
        "recall",
        {"query": "TypeError accessing null property mcp test", "limit": 5},
    )

    # TOON output is not JSON-parseable at the top level, but the field names
    # and values must appear somewhere in the rendered output.
    assert "provenance" in text, "TOON output should contain 'provenance' field name"
    assert "manual" in text, "TOON output should contain the source type value"
    assert "why" in text, "TOON output should contain 'why' field name"
    assert "final" in text or "boost" in text, (
        "TOON output should contain score breakdown sub-fields"
    )


def test_recall_tool_json_empty_result_has_no_provenance(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """Empty recall result (no matches) contains no spurious provenance or why fields."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)

    text = _tool_text(repo, "recall", {"query": "xyzzyx frabbitz quux bizarre error"})
    payload = json.loads(text)

    assert not payload["has_matches"]
    assert payload["entries"] == []


def test_recall_tool_json_provenance_omitted_gracefully_when_citation_empty(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """When a RecallEntry has an empty citation, 'provenance' is omitted from JSON output."""
    from oh_no_my_claudecode.mcp_server.tools import _recall_entry_dict
    from oh_no_my_claudecode.recall.compiler import RecallEntry, ScoreBreakdown

    # Build an entry with empty citation
    entry_no_citation = RecallEntry(
        memory_id="mem-test",
        title="Test entry",
        what_happened="Something happened.",
        resolution="Fix it.",
        source_ref="test:ref",
        confidence=0.8,
        relevance=0.5,
        kind="failed_approach",
        citation="",  # explicitly empty
        score_breakdown=ScoreBreakdown(
            overlap_ratio=0.5,
            confidence=0.8,
            feedback_score=0.0,
            kind_boost=3.0,
            stale_penalty=1.0,
            final_score=1.2,
        ),
    )
    row = _recall_entry_dict(entry_no_citation)

    assert "provenance" not in row, "Empty citation must not produce 'provenance' key"
    assert "why" in row, "Non-None score_breakdown must always produce 'why' key"


def test_recall_tool_json_why_omitted_when_breakdown_absent(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """When score_breakdown is None, 'why' is omitted from JSON output."""
    from oh_no_my_claudecode.mcp_server.tools import _recall_entry_dict
    from oh_no_my_claudecode.recall.compiler import RecallEntry

    entry_no_breakdown = RecallEntry(
        memory_id="mem-no-bd",
        title="Test entry without breakdown",
        what_happened="Something happened.",
        resolution="Fix it.",
        source_ref="test:ref",
        confidence=0.8,
        relevance=0.5,
        kind="failed_approach",
        citation="(manual · test:ref)",
        score_breakdown=None,  # absent
    )
    row = _recall_entry_dict(entry_no_breakdown)

    assert "why" not in row, "Absent score_breakdown must not produce 'why' key"
    assert "provenance" in row, "Non-empty citation must produce 'provenance' key"


# ---------------------------------------------------------------------------
# get_coverage tool
# ---------------------------------------------------------------------------


def test_get_coverage_returns_coverage_info_json(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """get_coverage returns a JSON dict with overall_coverage_pct and gap fields."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    text = _tool_text(repo, "get_coverage", {})
    payload = json.loads(text)

    assert "overall_coverage_pct" in payload
    assert "covered_files" in payload
    assert "uncovered_files" in payload
    assert "total_files" in payload
    assert "memory_count" in payload
    assert "worst_subsystems" in payload
    assert "top_uncovered_hotspots" in payload
    assert isinstance(payload["overall_coverage_pct"], float)
    assert isinstance(payload["worst_subsystems"], list)
    assert isinstance(payload["top_uncovered_hotspots"], list)


def test_get_coverage_returns_toon_by_default(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_coverage returns TOON (not JSON) without ONMC_MCP_FORMAT=json."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.delenv("ONMC_MCP_FORMAT", raising=False)
    repo = init(sample_repo)
    repo.ingest()

    text = _tool_text(repo, "get_coverage", {})

    # TOON is not valid top-level JSON
    try:
        json.loads(text)
        is_json = True
    except json.JSONDecodeError:
        is_json = False
    assert not is_json, "Default output should be TOON, not JSON"
    # But must contain coverage info
    assert "overall_coverage_pct" in text or "coverage" in text.lower()


# ---------------------------------------------------------------------------
# get_digest tool
# ---------------------------------------------------------------------------


def _setup_digest_repo(tmp_path: Path) -> tuple[Path, str]:
    """Create a minimal git repo, init onmc, return (repo_path, since_sha)."""
    import os
    import subprocess

    repo = tmp_path / "digest-repo"
    repo.mkdir()

    def _git(*args: str, env: dict[str, str] | None = None) -> str:
        merged = os.environ.copy()
        if env:
            merged.update(env)
        r = subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=merged
        )
        return r.stdout.strip()

    _git("init")
    _git("config", "user.name", "Test")
    _git("config", "user.email", "t@test.com")

    (repo / "README.md").write_text("# Digest test repo\n", encoding="utf-8")
    ts_env = {"GIT_AUTHOR_DATE": "2026-01-01T10:00:00+00:00",
               "GIT_COMMITTER_DATE": "2026-01-01T10:00:00+00:00"}
    _git("add", ".", env=ts_env)
    _git("commit", "-m", "init", env=ts_env)
    since_sha = _git("rev-parse", "--short", "HEAD")

    # Add a second file so HEAD differs from since_sha
    (repo / "extra.md").write_text("extra\n", encoding="utf-8")
    ts_env2 = {"GIT_AUTHOR_DATE": "2026-01-02T10:00:00+00:00",
                "GIT_COMMITTER_DATE": "2026-01-02T10:00:00+00:00"}
    _git("add", ".", env=ts_env2)
    _git("commit", "-m", "add extra", env=ts_env2)

    return repo, since_sha


def test_get_digest_returns_changelog_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """get_digest returns a JSON dict with ref metadata and sections."""
    repo, since_sha = _setup_digest_repo(tmp_path)
    monkeypatch.chdir(repo)
    onmc_repo = init(repo)

    # Seed a memory so there's something to find via created_at fallback.
    onmc_repo.memory.add(
        type="decision",
        title="Use shared cache",
        summary="Workers must always use the shared cache module.",
    )

    text = _tool_text(onmc_repo, "get_digest", {"since": since_sha})
    payload = json.loads(text)

    assert "since_ref" in payload
    assert "since_short" in payload
    assert "since_date" in payload
    assert "head_short" in payload
    assert "head_date" in payload
    assert "source" in payload
    assert "total" in payload
    assert "sections" in payload
    assert isinstance(payload["sections"], list)
    assert payload["since_short"] == since_sha


def test_get_digest_returns_toon_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_digest returns TOON by default without ONMC_MCP_FORMAT=json."""
    repo, since_sha = _setup_digest_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.delenv("ONMC_MCP_FORMAT", raising=False)
    onmc_repo = init(repo)

    text = _tool_text(onmc_repo, "get_digest", {"since": since_sha})

    try:
        json.loads(text)
        is_json = True
    except json.JSONDecodeError:
        is_json = False
    assert not is_json, "Default output should be TOON, not JSON"
    assert "since_ref" in text or since_sha in text


def test_get_digest_bad_ref_errors_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """get_digest returns a clean error payload (not an exception) for an invalid ref."""
    repo, _ = _setup_digest_repo(tmp_path)
    monkeypatch.chdir(repo)
    onmc_repo = init(repo)

    # Use call_onmc_tool directly — it should NOT raise.
    contents = call_onmc_tool(onmc_repo, "get_digest", {"since": "not-a-real-ref-xyz"})
    assert len(contents) == 1
    text = contents[0].text
    payload = json.loads(text)

    assert "error" in payload
    bad_ref = "not-a-real-ref-xyz"
    assert bad_ref in payload["error"] or bad_ref in payload.get("since", "")


def test_get_digest_respects_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """get_digest honours the limit argument and does not exceed it."""
    repo, since_sha = _setup_digest_repo(tmp_path)
    monkeypatch.chdir(repo)
    onmc_repo = init(repo)

    for i in range(10):
        onmc_repo.memory.add(
            type="decision",
            title=f"Decision {i}",
            summary=f"Summary {i}",
        )

    text = _tool_text(onmc_repo, "get_digest", {"since": since_sha, "limit": 3})
    payload = json.loads(text)

    total_returned = sum(len(section["entries"]) for section in payload["sections"])
    assert total_returned <= 3


# ---------------------------------------------------------------------------
# get_skills tool
# ---------------------------------------------------------------------------


def _seed_skill(repo: OnmcRepo, *, name: str, trigger: str, tags: list[str]) -> None:
    """Seed a Skill directly into the repo storage."""
    from oh_no_my_claudecode.models import Skill
    from oh_no_my_claudecode.utils.time import utc_now

    now = utc_now()
    from oh_no_my_claudecode.utils.text import stable_id

    skill = Skill(
        id=stable_id("skill", name, prefix="sk"),
        name=name,
        body=f"How-to body for {name}.",
        trigger=trigger,
        tags=tags,
        files=[],
        source_memory_ids=[],
        use_count=3,
        success_count=3,
        confidence=0.9,
        auto_inject=True,
        created_at=now,
        updated_at=now,
        last_used_at=None,
    )
    _, _, storage = repo._service._load_context()
    storage.add_skill(skill)


def test_get_skills_appears_in_tool_list_with_correct_schema() -> None:
    """get_skills is present in list_onmc_tools with the expected schema."""
    tools = list_onmc_tools()
    by_name = {tool.name: tool for tool in tools}

    assert "get_skills" in by_name
    schema = by_name["get_skills"].inputSchema
    assert schema.get("required", []) == []
    assert "query" in schema["properties"]
    assert "tags" in schema["properties"]
    assert "limit" in schema["properties"]
    assert schema["properties"]["tags"]["type"] == "array"


def test_get_skills_returns_skills_json(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """get_skills returns a JSON array of skills with the expected compact fields."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    _seed_skill(repo, name="Cache Busting", trigger="When cache is stale.", tags=["cache"])

    text = _tool_text(repo, "get_skills", {})
    payload = json.loads(text)

    assert isinstance(payload, list)
    assert len(payload) >= 1
    skill = next((s for s in payload if s["name"] == "Cache Busting"), None)
    assert skill is not None
    for field in ("id", "name", "trigger", "body", "tags", "confidence", "success_rate",
                  "auto_inject"):
        assert field in skill, f"Missing field: {field}"
    assert isinstance(skill["confidence"], float)
    assert isinstance(skill["success_rate"], float)
    assert isinstance(skill["tags"], list)


def test_get_skills_with_query_ranks_relevant_skill_first(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """get_skills with a query ranks the most relevant skill first."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    _seed_skill(
        repo,
        name="Cache Invalidation",
        trigger="When cache must be cleared.",
        tags=["cache", "invalidation"],
    )
    _seed_skill(
        repo,
        name="Auth Token Refresh",
        trigger="When tokens expire.",
        tags=["auth", "token"],
    )

    text = _tool_text(repo, "get_skills", {"query": "cache invalidation boundary"})
    payload = json.loads(text)

    assert isinstance(payload, list)
    assert len(payload) >= 1
    # The cache skill must rank ahead of the auth skill.
    names = [s["name"] for s in payload]
    assert "Cache Invalidation" in names
    cache_idx = names.index("Cache Invalidation")
    if "Auth Token Refresh" in names:
        auth_idx = names.index("Auth Token Refresh")
        assert cache_idx < auth_idx, "Cache skill should rank above auth skill for cache query"


def test_get_skills_empty_brain_returns_empty_list(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """get_skills returns an empty list when the brain has no skills."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    # Do not seed any skills.

    text = _tool_text(repo, "get_skills", {})
    payload = json.loads(text)

    assert isinstance(payload, list)
    assert payload == []


def test_get_skills_respects_limit(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """get_skills honours the limit argument."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    for i in range(5):
        _seed_skill(repo, name=f"Skill {i}", trigger=f"When condition {i}.", tags=[f"tag{i}"])

    text = _tool_text(repo, "get_skills", {"limit": 2})
    payload = json.loads(text)

    assert isinstance(payload, list)
    assert len(payload) <= 2


def test_get_skills_returns_toon_by_default(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_skills returns TOON (not JSON) without ONMC_MCP_FORMAT=json."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.delenv("ONMC_MCP_FORMAT", raising=False)
    repo = init(sample_repo)
    _seed_skill(repo, name="TOON Skill", trigger="When TOON is needed.", tags=["toon"])

    text = _tool_text(repo, "get_skills", {})

    try:
        json.loads(text)
        is_json = True
    except json.JSONDecodeError:
        is_json = False
    assert not is_json, "Default output should be TOON, not JSON"
    assert "TOON Skill" in text or "name" in text


# ---------------------------------------------------------------------------
# get_profile tool
# ---------------------------------------------------------------------------


def _seed_user_memory_for_profile(
    svc: object,
    *,
    title: str,
    summary: str,
    home: Path,
    kind: str = "decision",
) -> None:
    """Seed a memory into the user-scope store at *home* via the service."""
    from oh_no_my_claudecode.core.service import OnmcService

    assert isinstance(svc, OnmcService)
    svc.add_user_memory(title=title, summary=summary, home=home)


def test_get_profile_appears_in_tool_list_with_schema() -> None:
    """get_profile is present in list_onmc_tools with the expected schema."""
    tools = list_onmc_tools()
    by_name = {tool.name: tool for tool in tools}

    assert "get_profile" in by_name
    schema = by_name["get_profile"].inputSchema
    assert schema.get("required", []) == []
    assert "max_items" in schema["properties"]
    assert schema["properties"]["max_items"]["type"] == "integer"
    assert schema["properties"]["max_items"]["minimum"] == 1


def test_get_profile_returns_bucket_fields_json(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
    tmp_path: Path,
) -> None:
    """get_profile returns a JSON dict with all bucket fields for a seeded user store."""
    from oh_no_my_claudecode.core.service import OnmcService
    from oh_no_my_claudecode.models import MemoryKind, SourceType
    from oh_no_my_claudecode.models.memory import MemoryEntry
    from oh_no_my_claudecode.utils.text import stable_id
    from oh_no_my_claudecode.utils.time import utc_now

    monkeypatch.chdir(sample_repo)
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = init(sample_repo)

    # Seed memories directly into the user store pointed at tmp_path.
    svc = OnmcService()
    now = utc_now()

    # Preference (DECISION kind)
    pref_mem = MemoryEntry(
        id=stable_id("decision", "Prefer pytest", prefix="um"),
        kind=MemoryKind.DECISION,
        title="Prefer pytest",
        summary="Always use pytest over unittest.",
        details="",
        source_type=SourceType.MANUAL,
        source_ref="user:manual",
        tags=["user-pref"],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    # Mistake (FAILED_APPROACH kind)
    mistake_mem = MemoryEntry(
        id=stable_id("failed_approach", "Never bare except", prefix="um"),
        kind=MemoryKind.FAILED_APPROACH,
        title="Never bare except",
        summary="Always name the exception in except clauses.",
        details="",
        source_type=SourceType.MANUAL,
        source_ref="user:manual",
        tags=[],
        confidence=0.85,
        created_at=now,
        updated_at=now,
    )

    user_storage = svc._user_storage(home=tmp_path)
    user_storage.upsert_memories([pref_mem, mistake_mem])

    text = _tool_text(repo, "get_profile", {})
    payload = json.loads(text)

    assert "preferences" in payload
    assert "patterns" in payload
    assert "frequent_mistakes" in payload
    assert "tooling" in payload
    assert "derived_from" in payload
    assert "salient_memory_ids" in payload

    assert isinstance(payload["preferences"], list)
    assert isinstance(payload["frequent_mistakes"], list)
    assert isinstance(payload["tooling"], list)
    assert isinstance(payload["patterns"], list)
    assert isinstance(payload["derived_from"], int)
    assert isinstance(payload["salient_memory_ids"], list)

    assert payload["derived_from"] >= 2

    # The preference should appear in preferences bucket.
    pref_titles = [e["title"] for e in payload["preferences"]]
    assert "Prefer pytest" in pref_titles

    # The mistake should appear in frequent_mistakes bucket.
    mistake_titles = [e["title"] for e in payload["frequent_mistakes"]]
    assert "Never bare except" in mistake_titles

    # Each bucket entry must have title + summary.
    for entry in payload["preferences"] + payload["frequent_mistakes"]:
        assert "title" in entry
        assert "summary" in entry


def test_get_profile_empty_user_store_returns_empty_profile_no_error(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
    tmp_path: Path,
) -> None:
    """get_profile with an empty (nonexistent) user store returns empty profile, no exception."""
    monkeypatch.chdir(sample_repo)
    # Point HOME at a directory with no .onmc/user.db.
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = init(sample_repo)

    text = _tool_text(repo, "get_profile", {})
    payload = json.loads(text)

    assert payload["preferences"] == []
    assert payload["frequent_mistakes"] == []
    assert payload["tooling"] == []
    assert payload["patterns"] == []
    assert payload["derived_from"] == 0
    assert payload["salient_memory_ids"] == []


def test_get_profile_respects_max_items(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
    tmp_path: Path,
) -> None:
    """get_profile honours the max_items argument."""
    from oh_no_my_claudecode.core.service import OnmcService
    from oh_no_my_claudecode.models import MemoryKind, SourceType
    from oh_no_my_claudecode.models.memory import MemoryEntry
    from oh_no_my_claudecode.utils.text import stable_id
    from oh_no_my_claudecode.utils.time import utc_now

    monkeypatch.chdir(sample_repo)
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = init(sample_repo)

    svc = OnmcService()
    now = utc_now()
    user_storage = svc._user_storage(home=tmp_path)

    # Seed 10 DECISION memories (all go to preferences bucket).
    memories = [
        MemoryEntry(
            id=stable_id("decision", f"Pref {i}", prefix="um"),
            kind=MemoryKind.DECISION,
            title=f"Pref {i}",
            summary=f"Prefer approach {i}.",
            details="",
            source_type=SourceType.MANUAL,
            source_ref="user:manual",
            tags=["user-pref"],
            confidence=0.9,
            created_at=now,
            updated_at=now,
        )
        for i in range(10)
    ]
    user_storage.upsert_memories(memories)

    text = _tool_text(repo, "get_profile", {"max_items": 2})
    payload = json.loads(text)

    assert len(payload["preferences"]) <= 2


def test_get_profile_returns_toon_by_default(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """get_profile returns TOON (not JSON) without ONMC_MCP_FORMAT=json."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.delenv("ONMC_MCP_FORMAT", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = init(sample_repo)

    text = _tool_text(repo, "get_profile", {})

    try:
        json.loads(text)
        is_json = True
    except json.JSONDecodeError:
        is_json = False
    assert not is_json, "Default output should be TOON, not JSON"
    assert "preferences" in text or "derived_from" in text


# ---------------------------------------------------------------------------
# ask tool
# ---------------------------------------------------------------------------


def _seed_ask_memory(repo: OnmcRepo, *, title: str, summary: str) -> str:
    """Seed a DECISION memory for ask tests and return its id."""
    from oh_no_my_claudecode.models import MemoryKind, SourceType
    from oh_no_my_claudecode.models.memory import MemoryEntry
    from oh_no_my_claudecode.utils.text import stable_id
    from oh_no_my_claudecode.utils.time import utc_now

    now = utc_now()
    entry = MemoryEntry(
        id=stable_id(MemoryKind.DECISION.value, title, summary, "test:ask", prefix="ask"),
        kind=MemoryKind.DECISION,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.MANUAL,
        source_ref="test:ask",
        tags=["decision", "ask"],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    _, _, storage = repo._service._load_context()
    storage.upsert_memories([entry])
    return entry.id


def test_ask_appears_in_tool_list_with_schema() -> None:
    """ask tool is present in list_onmc_tools with question required and limit optional."""
    tools = list_onmc_tools()
    by_name = {tool.name: tool for tool in tools}

    assert "ask" in by_name
    schema = by_name["ask"].inputSchema
    assert schema["required"] == ["question"]
    assert "question" in schema["properties"]
    assert schema["properties"]["question"]["type"] == "string"
    assert "limit" in schema["properties"]
    assert schema["properties"]["limit"]["type"] == "integer"
    assert schema["properties"]["limit"].get("default") == 8


def test_ask_returns_ranked_cited_entries_for_seeded_brain(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """ask returns a JSON payload with question + ranked cited entries for a seeded brain."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    mem_id = _seed_ask_memory(
        repo,
        title="Cache invalidation decision",
        summary="Always route cache invalidation through the shared cache module.",
    )

    text = _tool_text(repo, "ask", {"question": "cache invalidation module"})
    payload = json.loads(text)

    assert "question" in payload
    assert payload["question"] == "cache invalidation module"
    assert "entries" in payload
    assert isinstance(payload["entries"], list)
    assert len(payload["entries"]) >= 1

    match = next((e for e in payload["entries"] if e["memory_id"] == mem_id), None)
    assert match is not None, f"Expected seeded memory {mem_id!r} in entries"
    assert "memory_id" in match
    assert "title" in match
    assert "kind" in match
    assert "relevance" in match
    assert isinstance(match["relevance"], float)

    # Entries must be sorted by relevance descending.
    relevances = [e["relevance"] for e in payload["entries"]]
    assert relevances == sorted(relevances, reverse=True)


def test_ask_empty_brain_returns_clean_empty_result(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """ask with an empty brain returns a clean payload with empty entries, no exception."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    # Do NOT ingest or seed; brain is empty.

    text = _tool_text(repo, "ask", {"question": "xyzzy frabbitz quux bizarre question"})
    payload = json.loads(text)

    assert "question" in payload
    assert "entries" in payload
    assert isinstance(payload["entries"], list)
    assert payload["entries"] == []


def test_ask_respects_limit(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """ask honours the limit argument."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    # Seed 5 memories with the same keyword to ensure matches.
    for i in range(5):
        _seed_ask_memory(
            repo,
            title=f"Cache decision {i}",
            summary=f"Cache routing rule {i}: always route through the shared cache module.",
        )

    text = _tool_text(repo, "ask", {"question": "cache routing module", "limit": 2})
    payload = json.loads(text)

    assert isinstance(payload["entries"], list)
    assert len(payload["entries"]) <= 2


def test_ask_returns_toon_by_default(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ask returns TOON (not JSON) without ONMC_MCP_FORMAT=json."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.delenv("ONMC_MCP_FORMAT", raising=False)
    repo = init(sample_repo)
    repo.ingest()
    _seed_ask_memory(
        repo,
        title="Cache invalidation decision",
        summary="Always route cache invalidation through the shared cache module.",
    )

    text = _tool_text(repo, "ask", {"question": "cache invalidation"})

    try:
        json.loads(text)
        is_json = True
    except json.JSONDecodeError:
        is_json = False
    assert not is_json, "Default output should be TOON, not JSON"
    assert "question" in text or "cache" in text.lower()
