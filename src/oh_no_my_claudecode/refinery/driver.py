"""Side-effecting merge-queue processor for ``onmc refinery``.

This module is the only place in the refinery feature that performs I/O
(shelling out to ``gh`` / ``git``). The ``Gh`` interface is injectable so
tests can pass a ``FakeGh`` that returns scripted states without touching a
real repo or GitHub API.

Design
------
``process`` iterates the queue head-by-head (up to *max_n*). For each head:

1. Ask ``gh`` for the PR's current CI state.
2. Call ``next_action`` (pure, from :mod:`~.queue`) to decide what to do.
3. Execute the action (rebase / merge / kick / wait).
4. Persist the updated queue after each step.

``process`` always returns a list of ``ProcessResult`` records — one per PR
that was *advanced* (not merely waited on). This lets the caller / tests
assert on outcomes without parsing terminal output.

CI gate
-------
Green requires **both**:
- The ``quality`` (or ``tests``) check matrix: all runs succeeded.
- CodeQL: the ``CodeQL`` check must NOT be in a ``failure`` / ``cancelled``
  conclusion. If CodeQL is absent (repo doesn't use it) the gate still passes.

This is stricter than the prior ``land`` convention (quality-only) and
matches the stated requirement.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from oh_no_my_claudecode.refinery.queue import (
    Action,
    CiStatus,
    PRState,
    Queue,
    head,
    load_queue,
    next_action,
    save_queue,
    set_state,
)

# ---------------------------------------------------------------------------
# GH interface (injectable)
# ---------------------------------------------------------------------------


class Gh(Protocol):
    """Minimal GitHub adapter interface.

    The ``process`` function depends only on this protocol — real code injects
    ``RealGh``, tests inject ``FakeGh``.
    """

    def pr_state(self, pr: int) -> CiStatus:
        """Return the current CI gate status for the given PR number."""
        ...

    def update_branch(self, pr: int) -> bool:
        """Rebase the PR branch onto the base branch (update-branch).

        Returns True on success, False on conflict.
        """
        ...

    def merge(self, pr: int) -> bool:
        """Merge the PR.

        Returns True on success, False on failure.
        """
        ...


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ProcessResult:
    """Result of processing a single queue entry."""

    pr: int
    action: Action
    success: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# Core process function
# ---------------------------------------------------------------------------


def process(
    queue: Queue,
    *,
    gh: Gh,
    queue_dir: Path,
    max_n: int = 1,
) -> list[ProcessResult]:
    """Process up to *max_n* queue entries.

    For each head entry the function:
    1. Queries CI state.
    2. Computes the required action.
    3. Executes the action.
    4. Saves the queue after each update.

    Returns a list of ``ProcessResult`` for every PR that was *acted on*
    (rebased, merged, or kicked). WAIT results are included so callers know a
    PR is still pending.
    """
    results: list[ProcessResult] = []
    # Re-read the queue from disk to ensure we work on the latest state,
    # then keep the in-memory queue in sync.
    current = load_queue(queue_dir)
    if not current.entries:
        current = queue

    processed = 0
    while processed < max_n:
        entry = head(current)
        if entry is None:
            break

        ci_status = gh.pr_state(entry.pr)
        action = next_action(ci_status)

        if action == Action.WAIT:
            # Mark as TESTING so status shows it's being monitored
            current = set_state(current, entry.pr, PRState.TESTING)
            save_queue(current, queue_dir)
            results.append(ProcessResult(pr=entry.pr, action=action, success=True))
            break  # Don't advance past a waiting PR

        elif action == Action.REBASE:
            ok = gh.update_branch(entry.pr)
            if ok:
                current = set_state(current, entry.pr, PRState.TESTING)
                save_queue(current, queue_dir)
                results.append(ProcessResult(pr=entry.pr, action=action, success=True))
                break  # Wait for CI after rebase
            else:
                reason = "rebase/update-branch failed (conflict)"
                current = set_state(current, entry.pr, PRState.KICKED, reason=reason)
                save_queue(current, queue_dir)
                results.append(
                    ProcessResult(pr=entry.pr, action=action, success=False, reason=reason)
                )

        elif action == Action.MERGE:
            ok = gh.merge(entry.pr)
            if ok:
                current = set_state(current, entry.pr, PRState.MERGED)
                save_queue(current, queue_dir)
                results.append(ProcessResult(pr=entry.pr, action=action, success=True))
            else:
                reason = "merge failed (possibly a race)"
                current = set_state(current, entry.pr, PRState.KICKED, reason=reason)
                save_queue(current, queue_dir)
                results.append(
                    ProcessResult(pr=entry.pr, action=action, success=False, reason=reason)
                )

        elif action == Action.KICK:
            reason = _kick_reason(ci_status)
            current = set_state(current, entry.pr, PRState.KICKED, reason=reason)
            save_queue(current, queue_dir)
            results.append(ProcessResult(pr=entry.pr, action=action, success=False, reason=reason))

        processed += 1

    return results


def _kick_reason(ci_status: CiStatus) -> str:
    """Return a human-readable kick reason for a failed CI status."""
    if ci_status == CiStatus.RED:
        return "CI checks failed (quality matrix or CodeQL)"
    if ci_status == CiStatus.BLOCKED:
        return "merge conflict — rebase failed"
    return f"unexpected CI status: {ci_status.value}"


# ---------------------------------------------------------------------------
# Real gh implementation (shells out)
# ---------------------------------------------------------------------------


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Run a subprocess command and return (returncode, stdout, stderr)."""
    result = subprocess.run(  # noqa: S603 - argv is a list, no shell
        argv,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


class RealGh:
    """Production gh adapter — shells out to ``gh`` and ``git``."""

    def pr_state(self, pr: int) -> CiStatus:  # noqa: PLR0911 - intentional multi-return
        """Determine the CI gate status by inspecting the PR's check runs.

        Logic:
        1. If the PR branch is behind the base (mergeable == "BEHIND") → BEHIND.
        2. If any check is still in progress → PENDING.
        3. If CodeQL conclusion is 'failure' or 'cancelled' → RED.
        4. If any required check concluded 'failure' → RED.
        5. All checks passed → GREEN.
        """
        import json as _json

        rc, out, _ = _run([
            "gh", "pr", "view", str(pr),
            "--json", "mergeable,statusCheckRollup",
        ])
        if rc != 0:
            return CiStatus.PENDING  # can't determine — treat as pending

        try:
            data = _json.loads(out)
        except Exception:  # noqa: BLE001
            return CiStatus.PENDING

        mergeable = data.get("mergeable", "")
        if mergeable == "CONFLICTING":
            return CiStatus.BLOCKED
        if mergeable == "BEHIND":
            return CiStatus.BEHIND

        checks = data.get("statusCheckRollup") or []
        if not checks:
            return CiStatus.PENDING  # no checks yet → treat as pending

        for check in checks:
            status = (check.get("status") or "").upper()
            conclusion = (check.get("conclusion") or "").lower()
            name = (check.get("name") or check.get("context") or "").lower()

            # CodeQL must not fail
            if "codeql" in name and conclusion in ("failure", "cancelled"):
                return CiStatus.RED

            if status in ("IN_PROGRESS", "QUEUED", "WAITING", "REQUESTED", "PENDING"):
                return CiStatus.PENDING

        # All checks done — scan for failures
        for check in checks:
            conclusion = (check.get("conclusion") or "").lower()
            if conclusion in ("failure", "cancelled", "timed_out", "action_required"):
                return CiStatus.RED

        return CiStatus.GREEN

    def update_branch(self, pr: int) -> bool:
        """Update the PR branch via ``gh pr update-branch``."""
        rc, _, _ = _run(["gh", "pr", "update-branch", str(pr), "--rebase"])
        return rc == 0

    def merge(self, pr: int) -> bool:
        """Merge the PR via ``gh pr merge --squash --auto``."""
        rc, _, _ = _run(["gh", "pr", "merge", str(pr), "--squash", "--auto"])
        return rc == 0


# ---------------------------------------------------------------------------
# Fake gh (for tests)
# ---------------------------------------------------------------------------


@dataclass
class FakeGh:
    """Test double for ``Gh``.

    ``states`` maps ``pr`` → list of ``CiStatus`` values popped left-to-right
    on each ``pr_state`` call.  Once exhausted, ``default`` is returned.
    ``update_branch_results`` maps ``pr`` → bool (default True).
    ``merge_results`` maps ``pr`` → bool (default True).
    """

    states: dict[int, list[CiStatus]] = field(default_factory=dict)
    default: CiStatus = CiStatus.GREEN
    update_branch_results: dict[int, bool] = field(default_factory=dict)
    merge_results: dict[int, bool] = field(default_factory=dict)
    calls: list[tuple[str, int]] = field(default_factory=list)

    def pr_state(self, pr: int) -> CiStatus:
        self.calls.append(("pr_state", pr))
        seq = self.states.get(pr, [])
        if seq:
            return seq.pop(0)
        return self.default

    def update_branch(self, pr: int) -> bool:
        self.calls.append(("update_branch", pr))
        return self.update_branch_results.get(pr, True)

    def merge(self, pr: int) -> bool:
        self.calls.append(("merge", pr))
        return self.merge_results.get(pr, True)
