"""Tests for git-diff-aware, ownership, and convention/provider signals."""

from __future__ import annotations

import subprocess
from pathlib import Path

from oh_no_my_claudecode.context_engine import RetrievalMode
from oh_no_my_claudecode.harness_run.context import RepositoryCandidateProvider
from oh_no_my_claudecode.harness_run.repo_signals import (
    CodeOwners,
    changed_paths,
    detect_conventions,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")


# --------------------------------------------------------------------------- #
# git-diff awareness
# --------------------------------------------------------------------------- #
def test_changed_paths_detects_modified_and_untracked(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-qm", "init")

    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")  # modified
    (tmp_path / "b.py").write_text("y = 1\n", encoding="utf-8")  # untracked

    changed = changed_paths(tmp_path)
    assert "a.py" in changed
    assert "b.py" in changed


def test_changed_paths_empty_outside_git(tmp_path: Path) -> None:
    assert changed_paths(tmp_path) == frozenset()


# --------------------------------------------------------------------------- #
# CODEOWNERS
# --------------------------------------------------------------------------- #
def test_codeowners_last_match_wins(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CODEOWNERS").write_text(
        "# comment\n"
        "*           @default-team\n"
        "src/        @src-team\n"
        "src/auth/*  @auth-team @security\n",
        encoding="utf-8",
    )
    owners = CodeOwners.load(tmp_path)
    assert owners.owners_for("README.md") == ("@default-team",)
    assert owners.owners_for("src/util.py") == ("@src-team",)
    assert owners.owners_for("src/auth/login.py") == ("@auth-team", "@security")


def test_codeowners_absent_is_empty(tmp_path: Path) -> None:
    assert CodeOwners.load(tmp_path).owners_for("anything.py") == ()


# --------------------------------------------------------------------------- #
# convention / provider detection
# --------------------------------------------------------------------------- #
def test_detect_conventions_python_stack(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n[tool.ruff]\n[tool.mypy]\n", encoding="utf-8"
    )
    conv = dict(detect_conventions(tmp_path))
    assert conv["language"] == "python"
    assert conv["test_framework"] == "pytest"
    assert conv["linter"] == "ruff"
    assert conv["type_checker"] == "mypy"


def test_detect_conventions_empty_repo(tmp_path: Path) -> None:
    assert detect_conventions(tmp_path) == ()


# --------------------------------------------------------------------------- #
# provider integration
# --------------------------------------------------------------------------- #
def test_provider_tags_changed_files_and_owners(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "cache.py").write_text(
        "def cache_get(key):\n    return None\n", encoding="utf-8"
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "init")
    # Now modify so it is git-diff-changed.
    (tmp_path / "src" / "cache.py").write_text(
        "def cache_get(key):\n    return _store.get(key)\n", encoding="utf-8"
    )
    (tmp_path / "CODEOWNERS").write_text("src/ @cache-team\n", encoding="utf-8")

    provider = RepositoryCandidateProvider(tmp_path)
    cands = {c.path: c for c in provider.candidates("cache", RetrievalMode.LOCAL)}
    assert "src/cache.py" in cands
    meta = dict(cands["src/cache.py"].metadata)
    assert meta.get("changed") == "true"
    assert meta.get("owners") == "@cache-team"
