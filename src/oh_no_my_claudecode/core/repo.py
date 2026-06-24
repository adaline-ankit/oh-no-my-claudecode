from __future__ import annotations

import subprocess
from pathlib import Path


class RepoDiscoveryError(RuntimeError):
    """Raised when no git repository can be found."""


def discover_repo_root(start_path: Path | None = None) -> Path:
    candidate = (start_path or Path.cwd()).resolve()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=candidate,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        current = candidate
        for path in (current, *current.parents):
            if (path / ".git").exists():
                return path
        msg = f"No git repository found from {candidate}"
        raise RepoDiscoveryError(msg) from None
    return Path(result.stdout.strip()).resolve()


def resolve_hooks_dir(repo_root: Path) -> Path:
    """Return the correct git hooks directory for *repo_root*.

    Works for both standard repositories (where `.git` is a directory) and
    linked worktrees (where `.git` is a file pointing elsewhere).  Falls back
    to the conventional ``.git/hooks`` path if the ``git`` binary cannot be
    found or the command fails for any reason.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-path", "hooks"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        hooks_path = Path(result.stdout.strip())
        if not hooks_path.is_absolute():
            hooks_path = repo_root / hooks_path
        return hooks_path.resolve()
    except (OSError, subprocess.CalledProcessError):
        return repo_root / ".git" / "hooks"


def current_branch(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def relative_path(repo_root: Path, path: Path) -> str:
    return path.resolve().relative_to(repo_root).as_posix()


def is_test_path(path: str) -> bool:
    lowered = path.lower()
    filename = Path(path).name.lower()
    return (
        "/tests/" in lowered
        or lowered.startswith("tests/")
        or filename.startswith("test_")
        or filename.endswith("_test.py")
        or filename.endswith(".spec.ts")
        or filename.endswith(".test.ts")
        or filename.endswith(".spec.tsx")
        or filename.endswith(".test.tsx")
        or filename.endswith(".spec.js")
        or filename.endswith(".test.js")
    )


def path_bucket(path: str, *, depth: int = 2) -> str:
    parts = [part for part in Path(path).parent.as_posix().split("/") if part and part != "."]
    if not parts:
        return "."
    return "/".join(parts[:depth])
