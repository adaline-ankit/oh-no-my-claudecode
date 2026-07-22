"""Deterministic environment and Git metadata capture."""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

from oh_no_my_claudecode.durable_runtime.models import (
    EnvironmentSnapshot,
    GitSnapshot,
    RetryClass,
)


def capture_environment(cwd: Path | None = None) -> EnvironmentSnapshot:
    """Capture a small, non-secret execution envelope."""
    working_directory = (cwd or Path.cwd()).resolve()
    return EnvironmentSnapshot(
        python_version=platform.python_version(),
        platform=platform.platform(),
        executable=sys.executable,
        cwd=str(working_directory),
    )


def capture_git(repo: Path | None = None) -> GitSnapshot:
    """Capture repository identity without modifying the working tree."""
    cwd = (repo or Path.cwd()).resolve()

    def git(*args: str) -> str | None:
        result = subprocess.run(
            ["git", *args], cwd=cwd, check=False, capture_output=True, text=True
        )
        return result.stdout.strip() if result.returncode == 0 else None

    root = git("rev-parse", "--show-toplevel")
    if root is None:
        return GitSnapshot(root=None, head=None, branch=None, dirty=None)
    head = git("rev-parse", "HEAD")
    branch = git("symbolic-ref", "--quiet", "--short", "HEAD")
    status = git("status", "--porcelain")
    return GitSnapshot(root=root, head=head, branch=branch, dirty=status != "")


def classify_retry(error: BaseException | str) -> RetryClass:
    """Classify a failure with deterministic, dependency-free rules."""
    if isinstance(error, (TimeoutError, ConnectionError)):
        return RetryClass.TRANSIENT
    message = str(error).lower()
    if any(marker in message for marker in ("429", "rate limit", "too many requests")):
        return RetryClass.RATE_LIMIT
    if any(marker in message for marker in ("out of memory", "no space left", "resource busy")):
        return RetryClass.RESOURCE
    if any(marker in message for marker in ("invalid", "unauthorized", "forbidden", "not found")):
        return RetryClass.PERMANENT
    if isinstance(error, OSError) or any(
        marker in message for marker in ("timeout", "temporarily unavailable", "connection reset")
    ):
        return RetryClass.TRANSIENT
    return RetryClass.UNKNOWN
