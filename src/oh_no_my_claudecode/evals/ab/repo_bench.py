"""Compile a repository's own git history into a private agent benchmark.

The product question every team answers with vibes — "which agent/model/config
actually works on OUR code?" — becomes measurable: every historical fix commit
that touched both source and tests is replayed as a task. The compiler reverts
only the source half of the fix (re-planting the bug), keeps the commit's own
tests as the objective gate, and emits :class:`ABTask` entries that drop
straight into the existing A/B suite runner.

This is the external-corpus method (revert-fix + real-test gate) turned inward:
a per-repo, continuously refreshable, private SWE-bench.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from oh_no_my_claudecode.evals.ab.models import ABTask

#: Commit subjects that smell like a behavior fix (not docs/chore/release).
_FIX_RE = re.compile(r"^(fix|bug|revert|patch|correct|repair)", re.IGNORECASE)

_TEST_HINTS = ("test_", "_test.", "/tests/", "tests/")

#: Skip fixes whose source diff is huge — replay tasks should be focused.
_MAX_PATCH_LINES = 400


def _git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return completed.stdout if completed.returncode == 0 else ""


def _is_test_path(path: str) -> bool:
    return any(hint in path for hint in _TEST_HINTS)


@dataclass(frozen=True, slots=True)
class MinedFix:
    """One historical fix commit eligible for benchmark replay."""

    sha: str
    subject: str
    source_paths: tuple[str, ...]
    test_paths: tuple[str, ...]


def mine_fix_commits(repo_root: Path, *, limit: int = 20, scan: int = 500) -> list[MinedFix]:
    """Return up to *limit* fix commits that touched both source and tests."""
    log = _git(repo_root, "log", f"-{scan}", "--no-merges", "--format=%H%x00%s")
    mined: list[MinedFix] = []
    for line in log.splitlines():
        if "\x00" not in line:
            continue
        sha, subject = line.split("\x00", 1)
        if not _FIX_RE.match(subject.strip()):
            continue
        files = _git(repo_root, "show", "--name-only", "--format=", sha).split()
        sources = tuple(f for f in files if f.endswith(".py") and not _is_test_path(f))
        tests = tuple(f for f in files if f.endswith(".py") and _is_test_path(f))
        if sources and tests:
            mined.append(MinedFix(sha, subject.strip(), sources, tests))
        if len(mined) >= limit:
            break
    return mined


def compile_task(repo_root: Path, fix: MinedFix, *, repo_url: str | None = None) -> ABTask | None:
    """Turn one mined fix into a replayable task, or ``None`` when unusable.

    The setup patch is the *reverse* source diff (``git diff <sha> <sha>^``),
    so applying it at the fix commit re-introduces the bug while the commit's
    own tests stay in place as the hidden-in-plain-sight objective gate.
    """
    reverse_patch = _git(repo_root, "diff", fix.sha, f"{fix.sha}^", "--", *fix.source_paths)
    if not reverse_patch.strip():
        return None
    if len(reverse_patch.splitlines()) > _MAX_PATCH_LINES:
        return None
    return ABTask(
        id=f"repobench_{fix.sha[:12]}",
        description=(
            f"A regression was reintroduced in this repository: {fix.subject}. "
            "Investigate the failing tests and fix the underlying bug in the "
            "source code. Do not modify the tests."
        ),
        setup_script="",
        gate_command=f"python -m pytest {' '.join(fix.test_paths)} -x -q",
        onmc_hint="",
        note=(
            f"repo-bench replay of {fix.sha} ({fix.subject!r}). Leakage risk: the "
            "agent's model may have seen this commit if the repo is public."
        ),
        repo_url=repo_url,
        repo_commit=fix.sha,
        setup_patch=reverse_patch,
        setup_commands=(("python", "-m", "pip", "install", "-q", "-e", "."),),
        pass_to_pass_commands=(),
        protected_paths=fix.test_paths,
    )


def compile_repo_bench(
    repo_root: Path,
    *,
    limit: int = 20,
    repo_url: str | None = None,
) -> list[ABTask]:
    """Mine + compile the repo's history into benchmark tasks."""
    tasks: list[ABTask] = []
    for fix in mine_fix_commits(repo_root, limit=limit * 3):
        task = compile_task(repo_root, fix, repo_url=repo_url)
        if task is not None:
            tasks.append(task)
        if len(tasks) >= limit:
            break
    return tasks


def export_repo_bench(repo_root: Path, out_path: Path, *, limit: int = 20) -> int:
    """Compile and write the benchmark as JSON; returns the task count."""
    tasks = compile_repo_bench(repo_root, limit=limit)
    payload = [
        {
            "id": t.id,
            "description": t.description,
            "gate_command": t.gate_command,
            "repo_commit": t.repo_commit,
            "setup_patch": t.setup_patch,
            "protected_paths": list(t.protected_paths),
            "note": t.note,
        }
        for t in tasks
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return len(tasks)


__all__ = [
    "MinedFix",
    "compile_repo_bench",
    "compile_task",
    "export_repo_bench",
    "mine_fix_commits",
]
