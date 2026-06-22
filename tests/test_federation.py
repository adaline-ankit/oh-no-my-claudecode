"""Tests for the cross-repo federation pull feature.

Covers:
- pull imports memories from another repo's .agent-memory/ export
- federated memories are tagged with federated:<repo-label>
- re-pull is idempotent (duplicate memories are skipped, not re-inserted)
- missing source path raises FileNotFoundError with a clear message
- git URL detection (is_git_url)
- repo_label_from_url derivation
- clone_and_pull happy path with injected clone function (offline)
- temp-dir cleanup on success and on clone failure
- --ref is passed through to the clone function
- --label overrides the derived label for git URLs
- CLI: onmc pull <git-url> succeeds (mocked clone)
- CLI: onmc pull <git-url> --ref <branch> (mocked clone)
- CLI: clone failure exits code 1 with error message
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
from oh_no_my_claudecode.federation.remote import (
    clone_and_pull,
    is_git_url,
    repo_label_from_url,
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
# Git URL detection tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/org/repo",
        "http://github.com/org/repo",
        "git@github.com:org/repo.git",
        "ssh://git@github.com/org/repo.git",
        "https://gitlab.com/org/repo.git",
        "some-repo.git",
    ],
)
def test_is_git_url_returns_true_for_git_urls(url: str) -> None:
    assert is_git_url(url) is True


@pytest.mark.parametrize(
    "path",
    [
        "/home/user/my-repo",
        "../sibling-repo",
        ".",
        "relative/path",
        "/absolute/path/.agent-memory",
    ],
)
def test_is_git_url_returns_false_for_local_paths(path: str) -> None:
    assert is_git_url(path) is False


# ---------------------------------------------------------------------------
# repo_label_from_url tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/org/my-repo", "my-repo"),
        ("https://github.com/org/repo.git", "repo"),
        ("git@github.com:org/my-repo.git", "my-repo"),
        ("ssh://git@github.com/org/my-repo", "my-repo"),
        ("https://github.com/org/repo/", "repo"),
    ],
)
def test_repo_label_from_url_extracts_last_segment(url: str, expected: str) -> None:
    assert repo_label_from_url(url) == expected


# ---------------------------------------------------------------------------
# clone_and_pull — offline tests with injected clone function
# ---------------------------------------------------------------------------


def _make_fake_clone(source_agent_memory_dir: Path) -> object:
    """Return a clone function that copies *source_agent_memory_dir* into dest."""

    def _fake_clone(git_url: str, dest: Path, ref: str | None) -> None:  # noqa: ARG001
        # Simulate a shallow clone: copy the .agent-memory/ dir into the dest.
        agent_mem_dest = dest / ".agent-memory"
        import shutil

        shutil.copytree(str(source_agent_memory_dir), str(agent_mem_dest))

    return _fake_clone


def test_clone_and_pull_happy_path(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """clone_and_pull imports memories via the injected clone function (offline)."""
    monkeypatch.chdir(sample_repo)
    svc_source = OnmcService(sample_repo)
    svc_source.init_project()
    svc_source.ingest()
    svc_source.sync_commit()
    source_agent_memory = sample_repo / ".agent-memory"
    expected_count = len(svc_source.list_memories())

    local_repo = tmp_path / "local"
    local_repo.mkdir()
    _git_init(local_repo)
    svc_local = OnmcService(local_repo)
    svc_local.init_project()
    _, _, storage = svc_local._load_context()  # noqa: SLF001

    fake_clone = _make_fake_clone(source_agent_memory)
    result = clone_and_pull(
        storage,
        "https://github.com/org/repo",
        repo_label="injected-label",
        _clone_fn=fake_clone,  # type: ignore[arg-type]
    )

    assert isinstance(result, PullResult)
    assert result.repo_label == "injected-label"
    assert result.imported == expected_count
    assert result.skipped == 0


def test_clone_and_pull_derives_label_from_url(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """When no repo_label given, label is derived from the URL."""
    monkeypatch.chdir(sample_repo)
    svc_source = OnmcService(sample_repo)
    svc_source.init_project()
    svc_source.ingest()
    svc_source.sync_commit()
    source_agent_memory = sample_repo / ".agent-memory"

    local_repo = tmp_path / "local"
    local_repo.mkdir()
    _git_init(local_repo)
    svc_local = OnmcService(local_repo)
    svc_local.init_project()
    _, _, storage = svc_local._load_context()  # noqa: SLF001

    fake_clone = _make_fake_clone(source_agent_memory)
    result = clone_and_pull(
        storage,
        "https://github.com/org/my-cool-repo",
        _clone_fn=fake_clone,  # type: ignore[arg-type]
    )

    assert result.repo_label == "my-cool-repo"


def test_clone_and_pull_passes_ref_to_clone_fn(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """The ref argument is forwarded to the clone function."""
    monkeypatch.chdir(sample_repo)
    svc_source = OnmcService(sample_repo)
    svc_source.init_project()
    svc_source.ingest()
    svc_source.sync_commit()
    source_agent_memory = sample_repo / ".agent-memory"

    local_repo = tmp_path / "local"
    local_repo.mkdir()
    _git_init(local_repo)
    svc_local = OnmcService(local_repo)
    svc_local.init_project()
    _, _, storage = svc_local._load_context()  # noqa: SLF001

    received_refs: list[str | None] = []

    def tracking_clone(git_url: str, dest: Path, ref: str | None) -> None:  # noqa: ARG001
        received_refs.append(ref)
        import shutil

        shutil.copytree(str(source_agent_memory), str(dest / ".agent-memory"))

    clone_and_pull(
        storage,
        "https://github.com/org/repo",
        ref="my-branch",
        _clone_fn=tracking_clone,
    )

    assert received_refs == ["my-branch"]


def test_clone_and_pull_cleans_up_temp_dir_on_success(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """Temp clone dir is removed after a successful pull."""
    import tempfile

    monkeypatch.chdir(sample_repo)
    svc_source = OnmcService(sample_repo)
    svc_source.init_project()
    svc_source.ingest()
    svc_source.sync_commit()
    source_agent_memory = sample_repo / ".agent-memory"

    local_repo = tmp_path / "local"
    local_repo.mkdir()
    _git_init(local_repo)
    svc_local = OnmcService(local_repo)
    svc_local.init_project()
    _, _, storage = svc_local._load_context()  # noqa: SLF001

    created_dirs: list[Path] = []
    real_mkdtemp = tempfile.mkdtemp

    def tracking_mkdtemp(**kwargs: object) -> str:
        path = real_mkdtemp(**kwargs)
        created_dirs.append(Path(path))
        return path

    import oh_no_my_claudecode.federation.remote as remote_mod

    monkeypatch.setattr(remote_mod.tempfile, "mkdtemp", tracking_mkdtemp)

    fake_clone = _make_fake_clone(source_agent_memory)
    clone_and_pull(
        storage,
        "https://github.com/org/repo",
        _clone_fn=fake_clone,  # type: ignore[arg-type]
    )

    assert created_dirs, "mkdtemp must have been called"
    for d in created_dirs:
        assert not d.exists(), f"Temp dir {d} was not cleaned up"


def test_clone_and_pull_cleans_up_temp_dir_on_clone_failure(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """Temp clone dir is removed even when the clone step raises."""
    import tempfile

    monkeypatch.chdir(sample_repo)
    local_repo = tmp_path / "local"
    local_repo.mkdir()
    _git_init(local_repo)
    svc_local = OnmcService(local_repo)
    svc_local.init_project()
    _, _, storage = svc_local._load_context()  # noqa: SLF001

    created_dirs: list[Path] = []
    real_mkdtemp = tempfile.mkdtemp

    def tracking_mkdtemp(**kwargs: object) -> str:
        path = real_mkdtemp(**kwargs)
        created_dirs.append(Path(path))
        return path

    import oh_no_my_claudecode.federation.remote as remote_mod

    monkeypatch.setattr(remote_mod.tempfile, "mkdtemp", tracking_mkdtemp)

    def failing_clone(git_url: str, dest: Path, ref: str | None) -> None:  # noqa: ARG001
        raise RuntimeError("git clone failed: network error")

    with pytest.raises(RuntimeError, match="git clone failed"):
        clone_and_pull(
            storage,
            "https://github.com/org/repo",
            _clone_fn=failing_clone,
        )

    assert created_dirs, "mkdtemp must have been called"
    for d in created_dirs:
        assert not d.exists(), f"Temp dir {d} was not cleaned up after failure"


def test_clone_and_pull_no_agent_memory_raises_file_not_found(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """When the cloned repo has no .agent-memory/, FileNotFoundError is raised."""
    monkeypatch.chdir(sample_repo)
    local_repo = tmp_path / "local"
    local_repo.mkdir()
    _git_init(local_repo)
    svc_local = OnmcService(local_repo)
    svc_local.init_project()
    _, _, storage = svc_local._load_context()  # noqa: SLF001

    def empty_clone(git_url: str, dest: Path, ref: str | None) -> None:  # noqa: ARG001
        # Clone succeeds but leaves no .agent-memory/ in dest
        pass

    with pytest.raises(FileNotFoundError, match=".agent-memory"):
        clone_and_pull(
            storage,
            "https://github.com/org/repo",
            _clone_fn=empty_clone,
        )


# ---------------------------------------------------------------------------
# CLI git URL tests (offline — clone step is monkeypatched)
# ---------------------------------------------------------------------------


def test_cli_pull_git_url_success(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """``onmc pull <git-url>`` should succeed when clone is mocked."""
    monkeypatch.chdir(sample_repo)
    svc_source = OnmcService(sample_repo)
    svc_source.init_project()
    svc_source.ingest()
    svc_source.sync_commit()
    source_agent_memory = sample_repo / ".agent-memory"

    local_repo = tmp_path / "local"
    local_repo.mkdir()
    _git_init(local_repo)
    monkeypatch.chdir(local_repo)
    OnmcService(local_repo).init_project()

    import oh_no_my_claudecode.federation.remote as remote_mod

    monkeypatch.setattr(remote_mod, "_default_clone", _make_fake_clone(source_agent_memory))

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["pull", "https://github.com/org/my-repo"],
        prog_name="onmc",
    )

    assert result.exit_code == 0, result.output
    assert "Pulled from" in result.output


def test_cli_pull_git_url_with_ref(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """``onmc pull <git-url> --ref <branch>`` should pass ref through."""
    monkeypatch.chdir(sample_repo)
    svc_source = OnmcService(sample_repo)
    svc_source.init_project()
    svc_source.ingest()
    svc_source.sync_commit()
    source_agent_memory = sample_repo / ".agent-memory"

    local_repo = tmp_path / "local"
    local_repo.mkdir()
    _git_init(local_repo)
    monkeypatch.chdir(local_repo)
    OnmcService(local_repo).init_project()

    received_refs: list[str | None] = []

    def tracking_clone(git_url: str, dest: Path, ref: str | None) -> None:  # noqa: ARG001
        received_refs.append(ref)
        import shutil

        shutil.copytree(str(source_agent_memory), str(dest / ".agent-memory"))

    import oh_no_my_claudecode.federation.remote as remote_mod

    monkeypatch.setattr(remote_mod, "_default_clone", tracking_clone)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["pull", "https://github.com/org/repo", "--ref", "develop"],
        prog_name="onmc",
    )

    assert result.exit_code == 0, result.output
    assert received_refs == ["develop"]


def test_cli_pull_git_url_clone_failure_exits_code_one(
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """A clone error should cause the CLI to exit with code 1."""
    monkeypatch.chdir(sample_repo)
    local_repo = tmp_path / "local"
    local_repo.mkdir()
    _git_init(local_repo)
    monkeypatch.chdir(local_repo)
    OnmcService(local_repo).init_project()

    def failing_clone(git_url: str, dest: Path, ref: str | None) -> None:  # noqa: ARG001
        raise RuntimeError("git clone failed: connection refused")

    import oh_no_my_claudecode.federation.remote as remote_mod

    monkeypatch.setattr(remote_mod, "_default_clone", failing_clone)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["pull", "https://github.com/org/repo"],
        prog_name="onmc",
    )

    assert result.exit_code == 1


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
