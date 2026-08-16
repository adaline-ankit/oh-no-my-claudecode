"""E8 — anti-reward-hack guards for repo-bench workspaces.

The 2026 literature measured frontier models reward-hacking in >30% of eval
runs; the attack classes that apply to replanted-bug benchmarks like ours:

1. **History exploit** (seen on SWE-bench): the fix is sitting in ``git log``
   — the agent reads it instead of solving. Defense: strip VCS history from
   the task workspace before the agent enters.
2. **Grader tampering**: the "pass" is achieved by editing the tests
   (``protected_paths``). Defense: digest protected files at setup, verify
   byte-identity before scoring; any drift voids the pass.

Contract: these run on *disposable task workspaces*, never on a working repo.
``strip_history`` therefore demands an explicit acknowledgement flag — an
irreversible delete should never be one careless call away.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path


def strip_history(workspace: Path, *, this_is_a_disposable_workspace: bool = False) -> bool:
    """Remove ``.git`` from a task workspace so the fix can't be read from the log.

    Returns True when history was present and removed, False when there was
    none. Refuses (raises) without the explicit acknowledgement flag.
    """
    if not this_is_a_disposable_workspace:
        raise ValueError(
            "strip_history deletes VCS history irreversibly; pass "
            "this_is_a_disposable_workspace=True only for benchmark task copies"
        )
    git_dir = Path(workspace) / ".git"
    if not git_dir.exists():
        return False
    shutil.rmtree(git_dir)
    return True


def protected_digests(workspace: Path, protected_paths: Sequence[str]) -> dict[str, str]:
    """sha256 per protected file at setup time — the grader's tamper baseline.

    A protected path missing at setup is recorded as "absent" so its later
    appearance is also detected (planting a trivial test is a hack too).
    """
    digests: dict[str, str] = {}
    for rel in protected_paths:
        file_path = Path(workspace) / rel
        if file_path.is_file():
            digests[rel] = hashlib.sha256(file_path.read_bytes()).hexdigest()
        else:
            digests[rel] = "absent"
    return digests


def verify_protected(workspace: Path, digests: Mapping[str, str]) -> tuple[str, ...]:
    """Paths whose bytes drifted since setup — non-empty means the pass is void.

    Fail-closed on every edge: modified, deleted, or newly-planted protected
    files all count as tampering.
    """
    tampered: list[str] = []
    for rel, expected in digests.items():
        file_path = Path(workspace) / rel
        if file_path.is_file():
            actual = hashlib.sha256(file_path.read_bytes()).hexdigest()
        else:
            actual = "absent"
        if actual != expected:
            tampered.append(rel)
    return tuple(tampered)


__all__ = ["protected_digests", "strip_history", "verify_protected"]
