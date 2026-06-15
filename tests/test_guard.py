"""Tests for the guard module — failure-aware dead-end surfacing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode import init
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.guard.compiler import GuardResult, compile_guard
from oh_no_my_claudecode.mcp_server.tools import call_onmc_tool
from oh_no_my_claudecode.models import MemoryArtifactType, MemoryKind, SourceType
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_failed_approach(storage: SQLiteStorage, title: str, summary: str, details: str) -> str:
    """Insert a FAILED_APPROACH memory and return its id."""
    from oh_no_my_claudecode.models.memory import MemoryEntry

    now = utc_now()
    entry = MemoryEntry(
        id=stable_id(MemoryKind.FAILED_APPROACH.value, title, summary, "test:seed", prefix="test"),
        kind=MemoryKind.FAILED_APPROACH,
        title=title,
        summary=summary,
        details=details,
        source_type=SourceType.MANUAL,
        source_ref="test:seed",
        tags=[MemoryKind.FAILED_APPROACH.value],
        confidence=0.85,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return entry.id


def _seed_did_not_work_artifact(
    storage: SQLiteStorage,
    memory_id: str,
    task_id: str,
    title: str,
    evidence: str,
    related_files: list[str] | None = None,
) -> None:
    """Insert a did_not_work artifact linked to a memory."""
    from oh_no_my_claudecode.models.memory_artifact import MemoryArtifactRecord

    artifact = MemoryArtifactRecord(
        memory_id=memory_id,
        task_id=task_id,
        type=MemoryArtifactType.DID_NOT_WORK,
        title=title,
        summary=f"Tried: {title}",
        why_it_matters="Avoid repeating this approach.",
        apply_when=None,
        avoid_when="When working on cache invalidation.",
        evidence=evidence,
        related_files=related_files or [],
        related_modules=[],
        confidence=0.8,
        created_at=utc_now(),
    )
    storage.create_memory_artifact(artifact)


# ---------------------------------------------------------------------------
# Unit tests: compile_guard
# ---------------------------------------------------------------------------


def test_compile_guard_surfaces_matching_failed_approach(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A seeded FAILED_APPROACH memory relevant to the task is returned."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    _, _, storage = repo._service._load_context()

    mid = _seed_failed_approach(
        storage,
        title="Direct cache bypass via Redis keys",
        summary="Tried to bypass the cache boundary by writing directly to Redis keys.",
        details="Bypassing the cache module breaks invalidation consistency.",
    )

    result = compile_guard(storage, "cache invalidation bypass redis keys")

    assert result.has_dead_ends
    assert any(entry.memory_id == mid for entry in result.entries)
    match = next(e for e in result.entries if e.memory_id == mid)
    assert "bypass" in match.what_was_tried.lower()


def test_compile_guard_enriches_with_did_not_work_artifact(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """did_not_work artifact evidence is surfaced as why_it_failed."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    _, _, storage = repo._service._load_context()

    # First need a task to attach the artifact to.
    task = repo._service.start_task(
        title="Cache work",
        description="Working on cache invalidation.",
        labels=[],
    )

    mid = _seed_failed_approach(
        storage,
        title="Monkey-patch cache module at test time",
        summary="Tried monkey-patching the cache module during test runs.",
        details="Monkey-patching broke parallel test isolation.",
    )
    _seed_did_not_work_artifact(
        storage,
        memory_id=mid,
        task_id=task.task_id,
        title="Monkey-patch cache during tests",
        evidence="Tests pass individually but fail in parallel runs due to shared state.",
        related_files=["tests/test_cache.py", "src/cache.py"],
    )

    result = compile_guard(storage, "monkey patch cache test isolation")

    assert result.has_dead_ends
    match = next((e for e in result.entries if e.memory_id == mid), None)
    assert match is not None
    assert "parallel" in match.why_it_failed.lower()
    assert "tests/test_cache.py" in match.related_files


def test_compile_guard_excludes_non_failure_memories(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-FAILED_APPROACH memories are never returned."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    _, _, storage = repo._service._load_context()

    # Seed an unrelated DECISION memory — should not appear in guard result.
    from oh_no_my_claudecode.models.memory import MemoryEntry

    now = utc_now()
    decision = MemoryEntry(
        id=stable_id("decision", "Use shared cache", "use shared cache", "test:d", prefix="test"),
        kind=MemoryKind.DECISION,
        title="Use shared cache boundary",
        summary="Always route invalidation through the shared cache module.",
        details="Keeps invalidation logic centralized.",
        source_type=SourceType.MANUAL,
        source_ref="test:d",
        tags=[],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([decision])

    result = compile_guard(storage, "cache invalidation boundary shared module")

    for entry in result.entries:
        # Guard must only surface FAILED_APPROACH entries.
        mem = storage.get_memory(entry.memory_id)
        assert mem is not None
        assert mem.kind == MemoryKind.FAILED_APPROACH


def test_compile_guard_empty_when_no_dead_ends(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returns an empty result when no FAILED_APPROACH memories exist."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    _, _, storage = repo._service._load_context()

    result = compile_guard(storage, "completely unrelated task about networking")

    assert not result.has_dead_ends
    assert result.entries == []


def test_compile_guard_empty_task_string(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty task string returns an empty result without error."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    _, _, storage = repo._service._load_context()

    result = compile_guard(storage, "")

    assert not result.has_dead_ends


def test_guard_result_markdown_no_dead_ends() -> None:
    """to_markdown() produces a clean message when there are no entries."""
    result = GuardResult(task="fix the bug")
    md = result.to_markdown()
    assert "no recorded dead-ends" in md
    assert "fix the bug" in md


def test_guard_result_markdown_with_entries(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """to_markdown() includes title, what_was_tried and why_it_failed."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    _, _, storage = repo._service._load_context()

    _seed_failed_approach(
        storage,
        title="Skip cache boundary",
        summary="Tried skipping the cache boundary in worker code.",
        details="Caused data inconsistency across workers.",
    )

    result = compile_guard(storage, "cache worker boundary skip")
    md = result.to_markdown()

    assert "DO NOT retry" in md
    assert "Skip cache boundary" in md
    assert "Tried skipping" in md


# ---------------------------------------------------------------------------
# CLI tests: onmc guard
# ---------------------------------------------------------------------------


def test_cli_guard_exits_zero_and_writes_artifact(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``onmc guard --task ...`` exits 0 and writes a .onmc/compiled/*-guard.md file."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()

    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    result = runner.invoke(app, ["guard", "--task", "fix the cache invalidation bug"])

    assert result.exit_code == 0

    compiled_dir = sample_repo / ".onmc" / "compiled"
    guard_artifacts = list(compiled_dir.glob("*-guard.md"))
    assert guard_artifacts, f"Expected a guard artifact in {compiled_dir}"


def test_cli_guard_with_dead_ends_prints_panel(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When dead-ends exist, the CLI output mentions them."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()

    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    # Seed a failed approach directly via the service.
    svc = init(sample_repo)
    _, _, storage = svc._service._load_context()
    _seed_failed_approach(
        storage,
        title="Direct Redis key writes",
        summary="Tried writing directly to Redis keys to bypass cache module.",
        details="Broke invalidation consistency for concurrent workers.",
    )

    result = runner.invoke(
        app,
        ["guard", "--task", "cache invalidation redis keys bypass"],
    )

    assert result.exit_code == 0
    assert "Dead" in result.stdout or "dead" in result.stdout or "DO NOT" in result.stdout


def test_cli_guard_no_dead_ends_prints_clean_message(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no dead-ends exist, CLI prints a clean green message."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()

    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    result = runner.invoke(app, ["guard", "--task", "completely unrelated networking task xyz"])

    assert result.exit_code == 0
    assert "no recorded dead-ends" in result.stdout.lower()


# ---------------------------------------------------------------------------
# MCP tool tests: guard_task
# ---------------------------------------------------------------------------


@pytest.fixture()
def json_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force MCP output to JSON for structured parsing."""
    monkeypatch.setenv("ONMC_MCP_FORMAT", "json")


def _tool_text(repo: object, name: str, arguments: dict[str, object]) -> str:
    contents = call_onmc_tool(repo, name, arguments)  # type: ignore[arg-type]
    assert len(contents) == 1
    assert contents[0].type == "text"
    return contents[0].text


def test_mcp_guard_task_tool_listed() -> None:
    """guard_task appears in list_onmc_tools."""
    from oh_no_my_claudecode.mcp_server.tools import list_onmc_tools

    tools = list_onmc_tools()
    names = {t.name for t in tools}
    assert "guard_task" in names


def test_mcp_guard_task_schema() -> None:
    """guard_task tool has the expected schema."""
    from oh_no_my_claudecode.mcp_server.tools import list_onmc_tools

    tools = {t.name: t for t in list_onmc_tools()}
    schema = tools["guard_task"].inputSchema
    assert schema["required"] == ["task"]
    assert "task" in schema["properties"]
    assert "limit" in schema["properties"]


def test_mcp_guard_task_returns_dead_ends(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """guard_task tool returns relevant dead-ends as a JSON payload."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    _, _, storage = repo._service._load_context()
    _seed_failed_approach(
        storage,
        title="Worker direct cache write",
        summary="Tried writing cache entries directly from worker processes.",
        details="Bypassing cache module caused inconsistent invalidation.",
    )

    text = _tool_text(repo, "guard_task", {"task": "cache worker direct write bypass"})
    payload = json.loads(text)

    assert payload["has_dead_ends"] is True
    assert len(payload["entries"]) > 0
    entry = payload["entries"][0]
    expected_fields = (
        "memory_id", "title", "what_was_tried", "why_it_failed", "source_ref", "confidence"
    )
    for field in expected_fields:
        assert field in entry, f"Missing field: {field}"


def test_mcp_guard_task_empty_when_no_dead_ends(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """guard_task returns has_dead_ends=false when nothing matches."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    text = _tool_text(repo, "guard_task", {"task": "unrelated networking xyz topic"})
    payload = json.loads(text)

    assert payload["has_dead_ends"] is False
    assert payload["entries"] == []
