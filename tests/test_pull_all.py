"""Tests for ``onmc pull --all`` federation-from-config feature.

Covers:
- config.yaml parses ``federation.sources`` with bare-string entries
- config.yaml parses ``federation.sources`` with object entries (path_or_url, label, ref)
- missing ``federation`` key in config → empty sources list (backward-compatible)
- pull_all iterates all sources and aggregates results
- one failing source does not abort the rest — error is captured per source
- dry_run=True returns results without writing any memories
- CLI ``onmc pull --all`` renders combined summary (exit 0 on no errors)
- CLI ``onmc pull --all --dry-run`` lists sources, writes nothing
- CLI ``onmc pull --all --json`` emits JSON
- CLI ``onmc pull --all`` with no sources configured → clean message, exit 0
- CLI ``onmc pull --all`` with a failing source → exit 1
- CLI ``onmc pull <source> --dry-run`` → error (dry-run only valid with --all)
- CLI ``onmc pull --all <source>`` → error (mutually exclusive)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.federation.pull import PullResult
from oh_no_my_claudecode.models.config import FederationSource, ProjectConfig

# ---------------------------------------------------------------------------
# Local helpers (mirrors pattern from test_federation.py)
# ---------------------------------------------------------------------------


def _git_init(repo: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _setup_source_repo(repo: Path) -> OnmcService:
    svc = OnmcService(repo)
    svc.init_project()
    svc.ingest()
    svc.sync_commit()
    return svc


def _setup_local_repo(repo: Path) -> OnmcService:
    svc = OnmcService(repo)
    svc.init_project()
    return svc


def _write_federation_config(repo: Path, sources: list[Any]) -> None:
    """Write a config.yaml with the given federation.sources list."""
    config_path = repo / ".onmc" / "config.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    data["federation"] = {"sources": sources}
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Config parsing — FederationSource / FederationSettings
# ---------------------------------------------------------------------------


def test_federation_settings_default_is_empty_list() -> None:
    """Missing federation key → empty sources (backward compatible)."""
    config = ProjectConfig.model_validate({"repo_root": "/tmp/test"})  # noqa: S108
    assert config.federation.sources == []


def test_federation_settings_parses_bare_strings() -> None:
    """Bare strings in the sources list are coerced to FederationSource."""
    raw = {
        "repo_root": "/tmp/test",  # noqa: S108
        "federation": {
            "sources": [
                "../sibling-repo",
                "https://github.com/org/brain",
            ]
        },
    }
    config = ProjectConfig.model_validate(raw)
    assert len(config.federation.sources) == 2
    assert config.federation.sources[0].path_or_url == "../sibling-repo"
    assert config.federation.sources[0].label is None
    assert config.federation.sources[0].ref is None
    assert config.federation.sources[1].path_or_url == "https://github.com/org/brain"


def test_federation_settings_parses_object_form() -> None:
    """Object entries (path_or_url, label, ref) are parsed correctly."""
    raw = {
        "repo_root": "/tmp/test",  # noqa: S108
        "federation": {
            "sources": [
                {"path_or_url": "../sibling", "label": "sib", "ref": "main"},
                {"path_or_url": "https://github.com/org/repo"},
            ]
        },
    }
    config = ProjectConfig.model_validate(raw)
    assert len(config.federation.sources) == 2
    s0 = config.federation.sources[0]
    assert s0.path_or_url == "../sibling"
    assert s0.label == "sib"
    assert s0.ref == "main"
    s1 = config.federation.sources[1]
    assert s1.path_or_url == "https://github.com/org/repo"
    assert s1.label is None
    assert s1.ref is None


def test_federation_settings_mixed_forms() -> None:
    """Mixed bare string and object entries both parse correctly."""
    raw = {
        "repo_root": "/tmp/test",  # noqa: S108
        "federation": {
            "sources": [
                "../local-repo",
                {"path_or_url": "https://github.com/org/repo", "label": "shared"},
            ]
        },
    }
    config = ProjectConfig.model_validate(raw)
    assert len(config.federation.sources) == 2
    assert config.federation.sources[0].path_or_url == "../local-repo"
    assert config.federation.sources[1].label == "shared"


def test_federation_source_dataclass() -> None:
    """FederationSource fields are accessible."""
    src = FederationSource(path_or_url="https://github.com/org/repo", label="org-repo", ref="dev")
    assert src.path_or_url == "https://github.com/org/repo"
    assert src.label == "org-repo"
    assert src.ref == "dev"


# ---------------------------------------------------------------------------
# 2. Service.pull_all — offline unit tests using mock injection
# ---------------------------------------------------------------------------


def _make_successful_pull_fn(imported: int = 3) -> Any:
    """Return a mock pull_memories that always succeeds."""

    def _pull(storage: Any, source_dir: Path, *, repo_label: str | None = None) -> PullResult:
        return PullResult(
            source=str(source_dir),
            repo_label=repo_label or source_dir.name,
            imported=imported,
            skipped=0,
        )

    return _pull


def _make_failing_pull_fn() -> Any:
    """Return a mock pull_memories that always raises FileNotFoundError."""

    def _pull(storage: Any, source_dir: Path, *, repo_label: str | None = None) -> PullResult:
        raise FileNotFoundError(f"No .agent-memory found at {source_dir}")

    return _pull


@pytest.fixture
def local_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialised local onmc repo for service tests."""
    repo = tmp_path / "local"
    repo.mkdir()
    _git_init(repo)
    monkeypatch.chdir(repo)
    _setup_local_repo(repo)
    return repo


def test_pull_all_iterates_all_sources(
    local_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pull_all returns one result per configured source."""
    # Write two local-path sources to config (paths don't need to exist —
    # we mock the pull function).
    _write_federation_config(
        local_repo,
        ["../source-a", "../source-b"],
    )

    svc = OnmcService(local_repo)
    with patch(
        "oh_no_my_claudecode.federation.pull.pull_memories",
        side_effect=_make_successful_pull_fn(imported=2),
    ):
        _, results = svc.pull_all()

    assert len(results) == 2
    src_ids = [src for src, _ in results]
    assert "../source-a" in src_ids
    assert "../source-b" in src_ids
    for _, outcome in results:
        assert isinstance(outcome, PullResult)
        assert outcome.imported == 2


def test_pull_all_captures_per_source_error(
    local_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing source's error is captured; remaining sources still run."""
    _write_federation_config(
        local_repo,
        ["../ok-source", "../bad-source", "../ok-source-2"],
    )

    call_count = 0

    def _selective_pull(
        storage: Any, source_dir: Path, *, repo_label: str | None = None
    ) -> PullResult:
        nonlocal call_count
        call_count += 1
        if "bad" in str(source_dir):
            raise FileNotFoundError(f"No .agent-memory at {source_dir}")
        return PullResult(
            source=str(source_dir),
            repo_label=repo_label or source_dir.name,
            imported=1,
            skipped=0,
        )

    svc = OnmcService(local_repo)
    with patch("oh_no_my_claudecode.federation.pull.pull_memories", side_effect=_selective_pull):
        _, results = svc.pull_all()

    assert call_count == 3, "all three sources must be attempted"
    assert len(results) == 3
    # The bad source is captured as an exception, not re-raised.
    bad_outcomes = [(src, r) for src, r in results if isinstance(r, Exception)]
    assert len(bad_outcomes) == 1
    assert "bad-source" in bad_outcomes[0][0]
    # Other sources still succeeded.
    ok_outcomes = [r for _, r in results if isinstance(r, PullResult)]
    assert len(ok_outcomes) == 2
    assert all(r.imported == 1 for r in ok_outcomes)


def test_pull_all_dry_run_writes_nothing(
    local_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dry_run=True returns results without ever calling pull_memories."""
    _write_federation_config(local_repo, ["../source-a", "../source-b"])

    svc = OnmcService(local_repo)

    write_called = False

    def _pull_should_not_be_called(*args: Any, **kwargs: Any) -> PullResult:
        nonlocal write_called
        write_called = True
        raise AssertionError("pull_memories must not be called in dry_run mode")

    with patch(
        "oh_no_my_claudecode.federation.pull.pull_memories",
        side_effect=_pull_should_not_be_called,
    ):
        _, results = svc.pull_all(dry_run=True)

    assert not write_called
    assert len(results) == 2


def test_pull_all_empty_sources_returns_empty_list(
    local_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No configured sources → results is an empty list."""
    svc = OnmcService(local_repo)
    _, results = svc.pull_all()
    assert results == []


# ---------------------------------------------------------------------------
# 3. CLI tests — offline (mock the per-source pull)
# ---------------------------------------------------------------------------


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


@pytest.fixture
def local_repo_for_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialised local onmc repo for CLI invocations."""
    repo = tmp_path / "local"
    repo.mkdir()
    _git_init(repo)
    monkeypatch.chdir(repo)
    _setup_local_repo(repo)
    return repo


def test_cli_pull_all_no_sources_prints_hint(
    local_repo_for_cli: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``onmc pull --all`` with no configured sources → clean message + exit 0."""
    runner = _cli_runner()
    result = runner.invoke(app, ["pull", "--all"], prog_name="onmc")
    assert result.exit_code == 0, result.output
    assert "federation.sources" in result.output


def test_cli_pull_all_success(
    local_repo_for_cli: Path,
    tmp_path: Path,
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``onmc pull --all`` with real sources (mocked) → exit 0 + summary."""
    _write_federation_config(local_repo_for_cli, ["../source-a"])

    fake_result = PullResult(
        source="/abs/source-a",
        repo_label="source-a",
        imported=5,
        skipped=2,
    )

    runner = _cli_runner()
    with patch("oh_no_my_claudecode.federation.pull.pull_memories", return_value=fake_result):
        result = runner.invoke(app, ["pull", "--all"], prog_name="onmc")

    assert result.exit_code == 0, result.output
    # Summary table should be rendered.
    assert "Total" in result.output or "ok" in result.output


def test_cli_pull_all_dry_run(
    local_repo_for_cli: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``onmc pull --all --dry-run`` exits 0 without calling pull_memories."""
    _write_federation_config(local_repo_for_cli, ["../source-a", "../source-b"])

    runner = _cli_runner()
    write_called = False

    def _no_write(*args: Any, **kwargs: Any) -> PullResult:
        nonlocal write_called
        write_called = True
        raise AssertionError("pull must not be called in dry_run")

    with patch("oh_no_my_claudecode.federation.pull.pull_memories", side_effect=_no_write):
        result = runner.invoke(app, ["pull", "--all", "--dry-run"], prog_name="onmc")

    assert result.exit_code == 0, result.output
    assert not write_called
    assert "dry" in result.output.lower() or "dry-run" in result.output.lower()


def test_cli_pull_all_json(
    local_repo_for_cli: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``onmc pull --all --json`` emits valid JSON list."""
    _write_federation_config(local_repo_for_cli, ["../source-a"])

    fake_result = PullResult(
        source="/abs/source-a",
        repo_label="source-a",
        imported=3,
        skipped=1,
    )

    runner = _cli_runner()
    with patch("oh_no_my_claudecode.federation.pull.pull_memories", return_value=fake_result):
        result = runner.invoke(app, ["pull", "--all", "--json"], prog_name="onmc")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["imported"] == 3
    assert payload[0]["skipped"] == 1
    assert payload[0]["repo_label"] == "source-a"


def test_cli_pull_all_failing_source_exits_one(
    local_repo_for_cli: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``onmc pull --all`` with a failing source → exit 1."""
    _write_federation_config(local_repo_for_cli, ["../bad-source"])

    runner = _cli_runner()
    with patch(
        "oh_no_my_claudecode.federation.pull.pull_memories",
        side_effect=FileNotFoundError("no .agent-memory found"),
    ):
        result = runner.invoke(app, ["pull", "--all"], prog_name="onmc")

    assert result.exit_code == 1


def test_cli_pull_source_and_all_mutually_exclusive(
    local_repo_for_cli: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``onmc pull <source> --all`` → error: mutually exclusive."""
    runner = _cli_runner()
    result = runner.invoke(app, ["pull", "../some-repo", "--all"], prog_name="onmc")
    assert result.exit_code == 1
    assert "SOURCE" in result.output or "both" in result.output.lower()


def test_cli_pull_dry_run_without_all_is_error(
    local_repo_for_cli: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``onmc pull <source> --dry-run`` → error: --dry-run is only for --all."""
    runner = _cli_runner()
    result = runner.invoke(app, ["pull", "../some-repo", "--dry-run"], prog_name="onmc")
    assert result.exit_code == 1
    assert "dry-run" in result.output.lower() or "--all" in result.output


def test_cli_pull_no_args_is_error(
    local_repo_for_cli: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``onmc pull`` with no SOURCE and no --all → friendly error."""
    runner = _cli_runner()
    result = runner.invoke(app, ["pull"], prog_name="onmc")
    assert result.exit_code == 1
    assert "SOURCE" in result.output or "--all" in result.output
