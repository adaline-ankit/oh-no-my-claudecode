from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=merged_env,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(repo: Path, message: str, timestamp: str) -> None:
    env = {
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_DATE": timestamp,
    }
    _git(repo, "add", ".", env=env)
    _git(repo, "commit", "-m", message, env=env)


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")

    _write(
        repo / "README.md",
        """# Sample Repo

This service handles cache invalidation for worker jobs.

## Development

Always run tests before merging.

## Architecture

We use a small cache module to centralize invalidation rules.
""",
    )
    _write(
        repo / "docs" / "architecture.md",
        """# Architecture

## Decision

We use a shared cache boundary so worker code does not duplicate invalidation logic.

## Invariants

Do not bypass the cache boundary from workers.
""",
    )
    _write(
        repo / "pyproject.toml",
        """[project]
name = "sample-repo"
version = "0.1.0"

[tool.pytest.ini_options]
addopts = "-q"

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.11"
""",
    )
    _write(
        repo / "src" / "cache.py",
        """def invalidate_cache(key: str) -> str:
    return f"invalidate:{key}"
""",
    )
    _write(
        repo / "src" / "worker.py",
        """from src.cache import invalidate_cache


def refresh_worker(key: str) -> str:
    return invalidate_cache(key)
""",
    )
    _write(
        repo / "tests" / "test_cache.py",
        """from src.cache import invalidate_cache


def test_invalidate_cache() -> None:
    assert invalidate_cache("a") == "invalidate:a"
""",
    )
    _write(
        repo / ".github" / "workflows" / "ci.yml",
        """name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
""",
    )
    _commit(repo, "Initial cache module", "2026-03-01T10:00:00+00:00")

    _write(
        repo / "src" / "cache.py",
        """def invalidate_cache(key: str) -> str:
    return f"invalidate:{key}:v2"
""",
    )
    _commit(repo, "Adjust cache invalidation", "2026-03-10T10:00:00+00:00")

    _write(
        repo / "src" / "cache.py",
        """def invalidate_cache(key: str) -> str:
    return f"invalidate:{key}:stable"
""",
    )
    _write(
        repo / "tests" / "test_cache.py",
        """from src.cache import invalidate_cache


def test_invalidate_cache() -> None:
    assert invalidate_cache("a") == "invalidate:a:stable"
""",
    )
    _commit(repo, "Fix flaky cache test", "2026-03-18T10:00:00+00:00")
    return repo
