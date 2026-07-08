"""Pure PR-landing planner — zero I/O.

``next_step`` maps a snapshot of PR state to the single action the lander
should take next.  It has no network calls, no filesystem access, and no
global state — it is deterministic and trivially unit-testable.

PR-state dict shape
-------------------
::

    {
      "merged": bool,
      "mergeStateStatus": "CLEAN" | "BEHIND" | "BLOCKED" | "UNSTABLE" | "UNKNOWN",
      "checks": [
        {
          "name": str,
          "status": "QUEUED" | "IN_PROGRESS" | "COMPLETED",
          "conclusion": "SUCCESS" | "FAILURE" | "CANCELLED"
                       | "SKIPPED" | "NEUTRAL" | None,
        },
        ...
      ],
      "unresolved_threads": int,        # count of open review threads
      "unresolved_thread_ids": [str],   # ids to pass to resolve_thread()
      "contention": int | None,         # optional: concurrent CI runs
    }

Gate logic
----------
1. Already merged               → DONE
2. Hard-blocker (CodeQL) FAIL  → FAIL
3. Branch behind target         → REBASE
4. Unresolved review threads    → RESOLVE_THREADS
5. Any non-advisory check FAIL → FAIL
6. Any non-advisory check PENDING → WAIT
7. mergeStateStatus CLEAN       → MERGE
8. mergeStateStatus BLOCKED     → FAIL
9. Otherwise                    → WAIT

Advisory checks (never block): Sourcery AI, greetings, apply-area-labels,
auto-assign, label bots.
Hard-blocking checks (FAILURE = FAIL): CodeQL.
"""

from __future__ import annotations

import enum
from typing import Any


class Step(enum.Enum):
    """Next action the lander should perform."""

    WAIT = "wait"
    REBASE = "rebase"
    RESOLVE_THREADS = "resolve_threads"
    MERGE = "merge"
    DONE = "done"
    FAIL = "fail"


# Substrings that identify advisory checks — never block landing.
_ADVISORY: frozenset[str] = frozenset(
    {
        "sourcery",
        "greetings",
        "apply-area-labels",
        "auto-assign",
        "label",
    }
)

# Substrings that identify hard-blocking checks — FAILURE → FAIL immediately.
_HARD_BLOCKERS: frozenset[str] = frozenset({"codeql"})


def _is_advisory(name: str) -> bool:
    """True when *name* belongs to an advisory check that should never gate landing."""
    nl = name.lower()
    return any(p in nl for p in _ADVISORY)


def _is_hard_blocker(name: str) -> bool:
    """True when *name* belongs to a hard-blocking check (e.g. CodeQL)."""
    nl = name.lower()
    return any(p in nl for p in _HARD_BLOCKERS)


def next_step(pr_state: dict[str, Any]) -> Step:
    """Return the next landing action given a PR-state snapshot.

    Parameters
    ----------
    pr_state:
        Dict matching the shape documented in the module docstring.  Unknown
        keys are silently ignored so callers can embed extra metadata.

    Returns
    -------
    Step
        One of ``DONE``, ``FAIL``, ``MERGE``, ``REBASE``, ``RESOLVE_THREADS``,
        or ``WAIT``.  The driver loop acts on the returned step, then calls
        this function again after the action completes.
    """
    if pr_state.get("merged"):
        return Step.DONE

    merge_state: str = pr_state.get("mergeStateStatus", "UNKNOWN")
    checks: list[dict[str, Any]] = pr_state.get("checks", [])

    # Hard blockers (CodeQL FAILURE) refuse to proceed regardless of other state.
    for check in checks:
        if _is_hard_blocker(check.get("name", "")) and check.get("conclusion") == "FAILURE":
            return Step.FAIL

    # Branch is behind the target — rebase before checks can be meaningful.
    if merge_state == "BEHIND":
        return Step.REBASE

    # Open review threads (e.g. Sourcery "changes requested") must be resolved.
    unresolved: int = pr_state.get("unresolved_threads", 0)
    if unresolved > 0:
        return Step.RESOLVE_THREADS

    # Evaluate non-advisory checks.
    any_pending = False
    for check in checks:
        if _is_advisory(check.get("name", "")):
            continue
        conclusion: str | None = check.get("conclusion")
        status: str = check.get("status", "")
        if conclusion == "FAILURE":
            return Step.FAIL
        if conclusion is None or status in ("QUEUED", "IN_PROGRESS"):
            any_pending = True

    if any_pending:
        return Step.WAIT

    # All non-advisory checks passed (or the list is empty).
    if merge_state == "CLEAN":
        return Step.MERGE

    # BLOCKED: branch protection or required review not satisfied — cannot fix.
    if merge_state == "BLOCKED":
        return Step.FAIL

    # UNSTABLE, UNKNOWN, or anything unexpected — wait for state to settle.
    return Step.WAIT
