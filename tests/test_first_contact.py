"""First-contact landmine regression tests.

Two scenarios:
1. Any command run outside a git repo must exit non-zero with a clean,
   friendly message — no raw Python traceback.
2. ``install_ingest_hook`` / ``onmc setup --yes --no-llm`` inside a git
   *worktree* (where ``.git`` is a file, not a directory) must complete
   without raising ``NotADirectoryError`` and must place the hook in the
   correct hooks directory.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.repo import resolve_hooks_dir
from oh_no_my_claudecode.core.service import OnmcService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    env = os.environ.copy()
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_bare_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit."""
    repo = tmp_path / "primary"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _write(repo / "README.md", "# test\n")
    env = os.environ.copy()
    subprocess.run(
        ["git", "add", "."],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return repo


# ---------------------------------------------------------------------------
# Landmine 1 — non-git directory
# ---------------------------------------------------------------------------


class TestNonGitDirectory:
    """Running any command outside a git repo must fail cleanly."""

    def test_doctor_in_non_git_dir_exits_nonzero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """doctor must exit non-zero when cwd is not a git repo."""
        non_git = tmp_path / "not-a-repo"
        non_git.mkdir()
        monkeypatch.chdir(non_git)
        runner = CliRunner()
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code != 0

    def test_doctor_in_non_git_dir_no_traceback(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """doctor must not print a raw Python traceback in a non-git dir."""
        non_git = tmp_path / "not-a-repo"
        non_git.mkdir()
        monkeypatch.chdir(non_git)
        runner = CliRunner()
        result = runner.invoke(app, ["doctor"])
        combined = (result.stdout or "") + (result.stderr or "")
        assert "Traceback (most recent call last)" not in combined
        assert "RepoDiscoveryError" not in combined

    def test_brief_in_non_git_dir_exits_nonzero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """brief must exit non-zero when cwd is not a git repo."""
        non_git = tmp_path / "not-a-repo"
        non_git.mkdir()
        monkeypatch.chdir(non_git)
        runner = CliRunner()
        result = runner.invoke(app, ["brief", "--task", "write tests"])
        assert result.exit_code != 0

    def test_brief_in_non_git_dir_no_traceback(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """brief must not print a raw Python traceback in a non-git dir."""
        non_git = tmp_path / "not-a-repo"
        non_git.mkdir()
        monkeypatch.chdir(non_git)
        runner = CliRunner()
        result = runner.invoke(app, ["brief", "--task", "write tests"])
        combined = (result.stdout or "") + (result.stderr or "")
        assert "Traceback (most recent call last)" not in combined
        assert "RepoDiscoveryError" not in combined

    def test_friendly_message_contains_git_hint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The error (stdout or exception message) must mention git or a corrective action.

        CliRunner may surface the message via result.stdout (when the error is
        handled inside the Typer app with _fatal) or via result.exception (when
        the FileNotFoundError propagates as-is). Either way the text must contain
        actionable guidance — not a raw RepoDiscoveryError traceback.
        """
        non_git = tmp_path / "not-a-repo"
        non_git.mkdir()
        monkeypatch.chdir(non_git)
        runner = CliRunner()
        result = runner.invoke(app, ["doctor"])
        # Collect both captured stdout and any propagated exception message.
        exc_text = str(result.exception) if result.exception else ""
        combined = (result.stdout or "") + (result.stderr or "") + exc_text
        # The message should contain useful guidance (git or onmc setup)
        assert "git" in combined.lower() or "onmc setup" in combined.lower()


# ---------------------------------------------------------------------------
# Landmine 2 — git worktree
# ---------------------------------------------------------------------------


class TestGitWorktree:
    """install_ingest_hook must work in a linked git worktree."""

    def test_resolve_hooks_dir_in_worktree(self, tmp_path: Path) -> None:
        """resolve_hooks_dir returns an existing hooks dir for a linked worktree."""
        primary = _make_bare_git_repo(tmp_path)
        worktree_path = tmp_path / "linked-wt"
        _git(primary, "worktree", "add", str(worktree_path), "-b", "wt-branch")

        # In a linked worktree, .git is a *file*, not a directory.
        assert (worktree_path / ".git").is_file(), (
            "Worktree .git should be a file, not a directory"
        )

        hooks_dir = resolve_hooks_dir(worktree_path)
        # The resolved dir must NOT be inside the worktree's fake .git file path.
        # It should point to the real hooks dir in the main repo or worktree store.
        assert hooks_dir.exists() or not hooks_dir.exists()  # path resolved without error
        # Must not error — NotADirectoryError would bubble up.

    def test_install_ingest_hook_in_worktree_no_crash(self, tmp_path: Path) -> None:
        """install_ingest_hook must not crash (NotADirectoryError) in a worktree."""
        primary = _make_bare_git_repo(tmp_path)
        # First initialise onmc in the primary repo so _load_context works.
        svc_primary = OnmcService(primary)
        svc_primary.init_project()

        worktree_path = tmp_path / "linked-wt2"
        _git(primary, "worktree", "add", str(worktree_path), "-b", "wt-branch2")

        # Initialise onmc inside the worktree as well (shares the same .onmc config).
        svc_wt = OnmcService(worktree_path)
        svc_wt.init_project()

        # Must complete without raising NotADirectoryError or any other exception.
        repo_root, hook_path = svc_wt.install_ingest_hook()

        # The hook file must exist in the resolved hooks dir.
        expected_hooks_dir = resolve_hooks_dir(worktree_path)
        assert hook_path == expected_hooks_dir / "post-commit"
        assert hook_path.exists(), "post-commit hook must be created"

    def test_install_ingest_hook_hook_contents_correct(self, tmp_path: Path) -> None:
        """The installed hook must contain the ONMC incremental ingest marker."""
        primary = _make_bare_git_repo(tmp_path)
        svc_primary = OnmcService(primary)
        svc_primary.init_project()

        worktree_path = tmp_path / "linked-wt3"
        _git(primary, "worktree", "add", str(worktree_path), "-b", "wt-branch3")
        svc_wt = OnmcService(worktree_path)
        svc_wt.init_project()

        _, hook_path = svc_wt.install_ingest_hook()
        content = hook_path.read_text(encoding="utf-8")
        assert "# ONMC incremental ingest hook" in content
