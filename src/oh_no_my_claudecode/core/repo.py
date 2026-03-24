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
