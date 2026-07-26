"""Deterministic repository and runtime environment snapshot for harness runs."""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = "1"
_GIT_TIMEOUT_S = 10


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    """Stable, non-secret facts needed to reproduce a harness plan."""

    repo_root: str
    git_available: bool
    git_head: str | None
    git_branch: str | None
    git_tree_sha: str | None
    git_dirty: bool | None
    git_status_digest: str | None
    python_version: str
    platform: str
    onmc_version: str
    schema_version: str = _SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "repo_root": self.repo_root,
            "git_available": self.git_available,
            "git_head": self.git_head,
            "git_branch": self.git_branch,
            "git_tree_sha": self.git_tree_sha,
            "git_dirty": self.git_dirty,
            "git_status_digest": self.git_status_digest,
            "python_version": self.python_version,
            "platform": self.platform,
            "onmc_version": self.onmc_version,
        }


def environment_snapshot(repo_root: Path) -> EnvironmentSnapshot:
    """Return deterministic local reproducibility facts for *repo_root*."""

    root = Path(repo_root).resolve()
    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current") if head is not None else None
    tree_sha = _git(root, "rev-parse", "HEAD^{tree}") if head is not None else None
    status = _git(root, "status", "--porcelain=v1") if head is not None else None
    status_digest = (
        hashlib.sha256(status.encode("utf-8")).hexdigest()
        if status is not None
        else None
    )
    return EnvironmentSnapshot(
        repo_root=str(root),
        git_available=head is not None,
        git_head=head,
        git_branch=branch or None,
        git_tree_sha=tree_sha,
        git_dirty=(bool(status) if status is not None else None),
        git_status_digest=status_digest,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        platform=platform.platform(),
        onmc_version=_onmc_version(),
    )


def _git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _onmc_version() -> str:
    try:
        return version("oh-no-my-claudecode")
    except PackageNotFoundError:
        return "0+unknown"


__all__ = ["EnvironmentSnapshot", "environment_snapshot"]
