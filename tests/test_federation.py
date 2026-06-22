"""Tests for the cross-repo federation pull feature.

Covers:
- pull imports memories from another repo's .agent-memory/ export
- federated memories are tagged with federated:<repo-label>
- re-pull is idempotent (duplicate memories are skipped, not re-inserted)
- missing source path raises FileNotFoundError with a clear message
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.federation.pull import (
    PullResult,
    _federation_tag,
    _repo_label_from_path,
    _resolve_agent_memory_dir,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_source_repo(repo: Path) -> None:
    """Initialise source repo, ingest, and export .agent-memory/."""
    svc = OnmcService(repo)
    svc.init_project()
    svc.ingest()
    svc.sync_commit()


def _setup_local_repo(repo: Path) -> OnmcService:
    """Initialise local repo without any ingest."""
    svc = OnmcService(repo)
    svc.init_project()
    return svc


# ---------------------------------------------------------------------------
# Unit tests for pure helpers
# ---------------------------------------------------------------------------


def test_federation_tag_format() -> None:
    assert _federation_tag("my-repo") == "federated:my-repo"


def test_repo_label_from_path_returns_parent_name(tmp_path: Path) -> None:
    agent_mem = tmp_path / "some-project" / ".agent-memory"
    agent_mem.mkdir(parents=True)
    assert _repo_label_from_path(agent_mem) == "some-project"


def test_resolve_agent_memory_dir_direct(tmp_path: Path) -> None:
    """Pointing at the .agent-memory dir directly should resolve correctly."""
    agent_mem = tmp_path / ".agent-memory"
    agent_mem.mkdir()
    (agent_mem / "manifest.json").write_text("{}", encoding="utf-8")
    resolved = _resolve_agent_memory_dir(agent_mem)
    assert resolved == agent_mem


def test_resolve_agent_memory_dir_repo_root(tmp_path: Path) -> None:
    """Pointing at the repo root should resolve to the .agent-memory subdir."""
    agent_mem = tmp_path / ".agent-memory"
    agent_mem.mkdir()
    (agent_mem / "manifest.json").write_text("{}", encoding="utf-8")
    resolved = _resolve_agent_memory_dir(tmp_path)
    assert resolved == agent_mem


def test_resolve_agent_memory_dir_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=".agent-memory/manifest.json"):
        _resolve_agent_memory_dir(tmp_path)


# ---------------------------------------------------------------------------
# Integration tests via OnmcService
# ---------------------------------------------------------------------------


def test_pull_imports_memories_from_source_repo(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """Pull should import all memories from a foreign repo's export."""
    monkeypatch.chdir(sample_repo)
    _setup_source_repo(sample_repo)
    source_memory_count_before = len(OnmcService(sample_repo).list_memories())

    local_repo = tmp_path / "local-brain"
    local_repo.mkdir()
    _git_init(local_repo)
    svc = _setup_local_repo(local_repo)
    monkeypatch.chdir(local_repo)

    _, result = svc.pull(sample_repo)

    assert isinstance(result, PullResult)
    assert result.imported == source_memory_count_before
    assert result.skipped == 0
    local_memories = svc.list_memories()
    assert len(local_memories) == source_memory_count_before


def test_pull_federated_memories_are_tagged(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """Every imported memory must carry a federated:<repo-name> tag."""
    monkeypatch.chdir(sample_repo)
    _setup_source_repo(sample_repo)

    local_repo = tmp_path / "local-brain"
    local_repo.mkdir()
    _git_init(local_repo)
    svc = _setup_local_repo(local_repo)
    monkeypatch.chdir(local_repo)

    _, result = svc.pull(sample_repo)

    expected_tag = _federation_tag(result.repo_label)
    local_memories = svc.list_memories()
    assert all(expected_tag in m.tags for m in local_memories), (
        f"All imported memories should have tag '{expected_tag}'"
    )


def test_pull_with_explicit_label_uses_that_label(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """When --label is given, the federation tag must use that label."""
    monkeypatch.chdir(sample_repo)
    _setup_source_repo(sample_repo)

    local_repo = tmp_path / "local-brain"
    local_repo.mkdir()
    _git_init(local_repo)
    svc = _setup_local_repo(local_repo)
    monkeypatch.chdir(local_repo)

    _, result = svc.pull(sample_repo, repo_label="custom-label")

    assert result.repo_label == "custom-label"
    expected_tag = "federated:custom-label"
    local_memories = svc.list_memories()
    assert all(expected_tag in m.tags for m in local_memories)


def test_pull_is_idempotent(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """Re-pulling the same source should import 0 new memories on the second run."""
    monkeypatch.chdir(sample_repo)
    _setup_source_repo(sample_repo)

    local_repo = tmp_path / "local-brain"
    local_repo.mkdir()
    _git_init(local_repo)
    svc = _setup_local_repo(local_repo)
    monkeypatch.chdir(local_repo)

    _, first = svc.pull(sample_repo)
    _, second = svc.pull(sample_repo)

    assert second.imported == 0
    assert second.skipped == first.imported
    # Total memories unchanged after second pull.
    assert len(svc.list_memories()) == first.imported


def test_pull_missing_source_raises_file_not_found(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """Pointing pull at a path with no export should raise FileNotFoundError."""
    local_repo = tmp_path / "local-brain"
    local_repo.mkdir()
    _git_init(local_repo)
    svc = _setup_local_repo(local_repo)
    monkeypatch.chdir(local_repo)

    with pytest.raises(FileNotFoundError, match=".agent-memory"):
        svc.pull(tmp_path / "nonexistent-source")


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


def test_cli_pull_command_success(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """CLI ``onmc pull <source>`` should exit 0 and print a success summary."""
    monkeypatch.chdir(sample_repo)
    _setup_source_repo(sample_repo)

    local_repo = tmp_path / "local-brain"
    local_repo.mkdir()
    _git_init(local_repo)
    monkeypatch.chdir(local_repo)
    OnmcService(local_repo).init_project()

    runner = CliRunner()
    result = runner.invoke(app, ["pull", str(sample_repo)], prog_name="onmc")

    assert result.exit_code == 0, result.stdout
    assert "Pulled from" in result.stdout


def test_cli_pull_command_json_flag(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """``onmc pull --json`` should emit valid JSON with expected keys."""
    monkeypatch.chdir(sample_repo)
    _setup_source_repo(sample_repo)

    local_repo = tmp_path / "local-brain"
    local_repo.mkdir()
    _git_init(local_repo)
    monkeypatch.chdir(local_repo)
    OnmcService(local_repo).init_project()

    runner = CliRunner()
    result = runner.invoke(
        app, ["pull", str(sample_repo), "--json"], prog_name="onmc"
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert "imported" in payload
    assert "skipped" in payload
    assert "repo_label" in payload
    assert "source" in payload


def test_cli_pull_missing_source_exits_code_one(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """CLI pull of a non-existent source should exit 1 with an error message."""
    local_repo = tmp_path / "local-brain"
    local_repo.mkdir()
    _git_init(local_repo)
    monkeypatch.chdir(local_repo)
    OnmcService(local_repo).init_project()

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["pull", str(tmp_path / "ghost-repo")],
        prog_name="onmc",
    )

    assert result.exit_code == 1
    assert ".agent-memory" in result.stdout


# ---------------------------------------------------------------------------
# Local helper
# ---------------------------------------------------------------------------


def _git_init(repo: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
