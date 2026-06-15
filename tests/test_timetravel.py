"""Tests for time-travel features: `onmc why --at` and `onmc memory-diff`."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.timetravel.git_at import fetch_git_history_at
from oh_no_my_claudecode.timetravel.memory_diff import (
    diff_memory_at_commits,
    memory_diff_to_markdown,
)
from oh_no_my_claudecode.why.compiler import compile_why

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """Run a git command in *repo* and return stdout."""
    import os

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=merged_env,
    )
    return result.stdout.strip()


def _commit_at(repo: Path, message: str, timestamp: str, env: dict[str, str] | None = None) -> str:
    """Stage all, commit with *message* + *timestamp*, return short hash."""
    ts_env = {
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_DATE": timestamp,
    }
    if env:
        ts_env.update(env)
    _git(repo, "add", ".", env=ts_env)
    _git(repo, "commit", "-m", message, env=ts_env)
    return _git(repo, "rev-parse", "--short", "HEAD")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo under tmp_path and return its path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    return repo


# ---------------------------------------------------------------------------
# Feature A: `onmc why --at <commit>` — git history bounded to that commit
# ---------------------------------------------------------------------------


@pytest.fixture
def time_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    """Three-commit repo: c1, c2 (adds extra.py), c3 (adds more to extra.py).

    Returns (repo, hash_c1, hash_c2, hash_c3).
    """
    repo = _init_repo(tmp_path)
    _write(repo / "README.md", "# Hello\n")
    _write(repo / "main.py", "x = 1\n")
    h1 = _commit_at(repo, "init", "2026-01-01T10:00:00+00:00")

    _write(repo / "extra.py", "extra = 1\n")
    h2 = _commit_at(repo, "add extra", "2026-02-01T10:00:00+00:00")

    _write(repo / "extra.py", "extra = 2\n")
    h3 = _commit_at(repo, "bump extra", "2026-03-01T10:00:00+00:00")

    return repo, h1, h2, h3


def test_fetch_git_history_at_bounds_to_commit(
    time_repo: tuple[Path, str, str, str],
) -> None:
    """History at c1 must NOT include the commit that added extra.py (c2)."""
    repo, h1, h2, h3 = time_repo

    hist_at_c1 = fetch_git_history_at(repo, "extra.py", h1)
    # extra.py doesn't exist at c1 — 0 commits
    assert hist_at_c1 is not None
    assert hist_at_c1.commit_count == 0

    hist_at_c2 = fetch_git_history_at(repo, "extra.py", h2)
    assert hist_at_c2 is not None
    assert hist_at_c2.commit_count == 1, "only the 'add extra' commit visible at c2"

    hist_at_c3 = fetch_git_history_at(repo, "extra.py", h3)
    assert hist_at_c3 is not None
    assert hist_at_c3.commit_count == 2, "both extra commits visible at c3 (HEAD)"


def test_fetch_git_history_at_returns_short_and_date(
    time_repo: tuple[Path, str, str, str],
) -> None:
    repo, _h1, h2, _h3 = time_repo
    hist = fetch_git_history_at(repo, "extra.py", h2)
    assert hist is not None
    assert hist.at_short, "short hash must be populated"
    assert "2026" in hist.at_date, "date must be populated"


def test_compile_why_at_commit_uses_bounded_history(
    time_repo: tuple[Path, str, str, str],
    tmp_path: Path,
) -> None:
    """compile_why with at_commit must show bounded git history."""
    repo, h1, h2, h3 = time_repo

    # init + ingest (no LLM)
    svc = OnmcService(repo)
    svc.init_project()
    svc.ingest(no_llm=True)
    _, _, storage = svc._load_context()

    # At h1, extra.py has 0 commits
    report_at_c1 = compile_why(repo, storage, "extra.py", at_commit=h1)
    assert report_at_c1.at_commit == h1
    assert report_at_c1.at_label != "", "at_label must be set"
    assert report_at_c1.git_history_at is not None
    assert report_at_c1.git_history_at.commit_count == 0

    # At h3 (HEAD), extra.py has 2 commits
    report_at_c3 = compile_why(repo, storage, "extra.py", at_commit=h3)
    assert report_at_c3.git_history_at is not None
    assert report_at_c3.git_history_at.commit_count == 2


def test_compile_why_no_at_uses_full_history(
    time_repo: tuple[Path, str, str, str],
) -> None:
    repo, _h1, _h2, _h3 = time_repo
    svc = OnmcService(repo)
    svc.init_project()
    svc.ingest(no_llm=True)
    _, _, storage = svc._load_context()

    report = compile_why(repo, storage, "extra.py")
    assert report.at_commit == ""
    assert report.at_label == ""
    assert report.git_history_at is None
    # Full history shows 2 commits
    assert report.git_history is not None
    assert report.git_history.commit_count == 2


def test_why_at_commit_markdown_labels(
    time_repo: tuple[Path, str, str, str],
) -> None:
    from oh_no_my_claudecode.why.compiler import why_report_to_markdown

    repo, h1, h2, _h3 = time_repo
    svc = OnmcService(repo)
    svc.init_project()
    svc.ingest(no_llm=True)
    _, _, storage = svc._load_context()

    report = compile_why(repo, storage, "extra.py", at_commit=h2)
    md = why_report_to_markdown(report)
    assert "As of" in md
    assert "git history is bounded" in md.lower() or "note" in md.lower()
    assert h2[:4] in md  # at least the first 4 chars of the short hash appear


def test_why_service_with_at_commit(time_repo: tuple[Path, str, str, str]) -> None:
    repo, h1, _h2, _h3 = time_repo
    svc = OnmcService(repo)
    svc.init_project()
    svc.ingest(no_llm=True)

    _, report = svc.why("extra.py", no_llm=True, at_commit=h1)
    assert report.at_label != ""
    assert report.git_history_at is not None
    assert report.git_history_at.commit_count == 0
    # Artifact must be written
    assert report.output_path
    assert Path(report.output_path).is_file()


def test_why_cli_at_flag(
    time_repo: tuple[Path, str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, h1, _h2, _h3 = time_repo
    monkeypatch.chdir(repo)
    svc = OnmcService(repo)
    svc.init_project()
    svc.ingest(no_llm=True)

    result = runner.invoke(app, ["why", "extra.py", "--no-llm", "--at", h1])
    assert result.exit_code == 0, result.output
    assert "onmc why" in result.output
    assert "Wrote why report" in result.output


# ---------------------------------------------------------------------------
# Feature B: `onmc memory-diff <A> <B>` — diff committed .agent-memory/ snapshots
# ---------------------------------------------------------------------------


def _write_memory_snapshot(
    repo: Path,
    memories: list[dict[str, str]],
) -> None:
    """Write .agent-memory/memories/ JSON files to *repo*."""
    for mem in memories:
        kind = mem["kind"]
        mem_id = mem["id"]
        path = repo / ".agent-memory" / "memories" / kind / f"{mem_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "memory": {
                "id": mem_id,
                "kind": kind,
                "title": mem["title"],
                "summary": mem["summary"],
                "confidence": 0.75,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "details": mem["summary"],
                "feedback_score": 0.0,
                "last_verified_at": None,
                "source_ref": "test",
                "source_type": "doc",
                "staleness": None,
                "tags": [],
            }
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@pytest.fixture
def memory_diff_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """Repo with two commits carrying different .agent-memory/ snapshots.

    commit_a has: mem-A (doc_fact), mem-B (decision)
    commit_b has: mem-B (decision, changed summary), mem-C (invariant) — mem-A removed
    """
    repo = _init_repo(tmp_path)
    _write(repo / "README.md", "# Repo\n")

    _write_memory_snapshot(
        repo,
        [
            {"id": "mem-A", "kind": "doc_fact", "title": "Fact A", "summary": "Summary A"},
            {"id": "mem-B", "kind": "decision", "title": "Decision B", "summary": "Old summary B"},
        ],
    )
    h1 = _commit_at(repo, "snapshot v1", "2026-01-01T10:00:00+00:00")

    # Remove mem-A, change mem-B, add mem-C
    import shutil

    mem_a_path = repo / ".agent-memory" / "memories" / "doc_fact" / "mem-A.json"
    if mem_a_path.exists():
        mem_a_path.unlink()
    shutil.rmtree(repo / ".agent-memory" / "memories" / "doc_fact", ignore_errors=True)

    _write_memory_snapshot(
        repo,
        [
            {
                "id": "mem-B",
                "kind": "decision",
                "title": "Decision B",
                "summary": "New summary B (updated)",
            },
            {"id": "mem-C", "kind": "invariant", "title": "Invariant C", "summary": "Summary C"},
        ],
    )
    h2 = _commit_at(repo, "snapshot v2", "2026-02-01T10:00:00+00:00")

    return repo, h1, h2


def test_memory_diff_added_removed_changed(
    memory_diff_repo: tuple[Path, str, str],
) -> None:
    repo, h1, h2 = memory_diff_repo
    result = diff_memory_at_commits(repo, h1, h2)

    assert not result.fallback_mode, "snapshot is committed at both commits"
    assert result.short_a, "short_a must be resolved"
    assert result.short_b, "short_b must be resolved"

    added_ids = {e.id for e in result.added}
    removed_ids = {e.id for e in result.removed}
    changed_ids = {c.memory_id for c in result.changed}

    assert "mem-C" in added_ids, "mem-C added in commit_b"
    assert "mem-A" in removed_ids, "mem-A removed in commit_b"
    assert "mem-B" in changed_ids, "mem-B summary changed"

    b_change = next(c for c in result.changed if c.memory_id == "mem-B")
    assert "Old summary B" in b_change.old_summary
    assert "New summary B" in b_change.new_summary


def test_memory_diff_fallback_when_no_snapshot(
    tmp_path: Path,
) -> None:
    """When .agent-memory/ is absent at both commits, fallback mode activates."""
    repo = _init_repo(tmp_path)
    _write(repo / "README.md", "# A\n")
    h1 = _commit_at(repo, "first", "2026-01-01T10:00:00+00:00")
    _write(repo / "README.md", "# B\n")
    h2 = _commit_at(repo, "second", "2026-02-01T10:00:00+00:00")

    result = diff_memory_at_commits(repo, h1, h2)
    assert result.fallback_mode
    assert result.fallback_reason != ""
    assert "README.md" in result.files_changed


def test_memory_diff_markdown_sections(memory_diff_repo: tuple[Path, str, str]) -> None:
    repo, h1, h2 = memory_diff_repo
    result = diff_memory_at_commits(repo, h1, h2)
    md = memory_diff_to_markdown(result)
    assert "# Memory diff" in md
    assert "Added knowledge" in md
    assert "Removed" in md
    assert "Changed knowledge" in md


def test_memory_diff_markdown_fallback(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write(repo / "a.txt", "x\n")
    h1 = _commit_at(repo, "one", "2026-01-01T10:00:00+00:00")
    _write(repo / "a.txt", "y\n")
    h2 = _commit_at(repo, "two", "2026-02-01T10:00:00+00:00")

    result = diff_memory_at_commits(repo, h1, h2)
    md = memory_diff_to_markdown(result)
    assert "Fallback mode" in md
    assert ".agent-memory/" in md


def test_memory_diff_service_writes_artifact(
    memory_diff_repo: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, h1, h2 = memory_diff_repo
    monkeypatch.chdir(repo)
    svc = OnmcService(repo)
    svc.init_project()
    svc.ingest(no_llm=True)

    _, result = svc.memory_diff(h1, h2)
    assert not result.fallback_mode
    assert result.added or result.removed or result.changed


def test_memory_diff_cli_exits_zero(
    memory_diff_repo: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, h1, h2 = memory_diff_repo
    monkeypatch.chdir(repo)
    svc = OnmcService(repo)
    svc.init_project()
    svc.ingest(no_llm=True)

    result = runner.invoke(app, ["memory-diff", h1, h2])
    assert result.exit_code == 0, result.output
    # Should show summary
    assert "added" in result.output.lower() or "removed" in result.output.lower()


def test_memory_diff_cli_fallback_exits_zero(tmp_path: Path) -> None:
    """Even in fallback mode, the CLI must exit 0."""
    repo = _init_repo(tmp_path)
    _write(repo / "x.py", "pass\n")
    h1 = _commit_at(repo, "base", "2026-01-01T10:00:00+00:00")
    _write(repo / "x.py", "pass  # v2\n")
    h2 = _commit_at(repo, "update", "2026-02-01T10:00:00+00:00")

    # init onmc in the repo
    svc = OnmcService(repo)
    svc.init_project()
    svc.ingest(no_llm=True)

    import os

    runner2 = CliRunner()
    orig = os.getcwd()
    try:
        os.chdir(repo)
        result = runner2.invoke(app, ["memory-diff", h1, h2])
    finally:
        os.chdir(orig)
    assert result.exit_code == 0, result.output
    assert "fallback" in result.output.lower()
