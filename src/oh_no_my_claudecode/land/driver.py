"""PR-landing driver — drives the planner using an injectable I/O layer.

The ``land()`` function is the main entry point.  It polls PR state through
a ``GhProtocol`` implementation, delegates every decision to the pure
``next_step()`` planner, and loops until the PR is merged, a hard failure is
detected, or the deadline expires.

The ``GhProtocol`` is an injectable ``Protocol``; the real implementation in
``commands.py`` shells out to ``gh``.  Tests inject a ``FakeGh`` that returns
scripted state sequences — no network calls needed.

The ``sleep`` parameter (default ``time.sleep``) is also injectable so that
tests can record sleep intervals without real blocking.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol, TypedDict, runtime_checkable

from oh_no_my_claudecode.land.planner import Step, next_step


class LandResult(TypedDict):
    """Outcome returned by a completed or deferred ``land()`` call."""

    outcome: str  # "merged" | "deferred" | "timeout"
    reason: str | None  # human-readable detail; None when not applicable


@runtime_checkable
class GhProtocol(Protocol):
    """Injectable GitHub client used by the landing driver.

    The real implementation shells out to ``gh``.  Tests inject a fake
    that returns scripted responses without touching the network.
    """

    def pr_state(self, pr: int) -> dict[str, Any]:
        """Fetch the current state of PR *pr* as a planner-compatible dict."""
        ...  # pragma: no cover

    def update_branch(self, pr: int) -> None:
        """Rebase the PR branch onto the current target (``gh pr update-branch``)."""
        ...  # pragma: no cover

    def resolve_thread(self, thread_id: str) -> None:
        """Resolve a single review thread by *thread_id* via the GraphQL API."""
        ...  # pragma: no cover

    def merge(self, pr: int) -> None:
        """Squash-merge PR *pr* with ``--admin --delete-branch``."""
        ...  # pragma: no cover


class LandError(Exception):
    """Raised when landing is permanently blocked with no recovery path.

    This is distinct from a transient failure (WAIT) or timeout: a ``LandError``
    means the planner returned ``Step.FAIL`` and the lander cannot proceed.
    """


def land(
    pr: int,
    *,
    gh: GhProtocol,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval: float = 30.0,
    max_wait: float = 1800.0,
    only_if_contention_le: int | None = None,
) -> LandResult:
    """Drive the PR landing loop until DONE, FAIL, or the deadline expires.

    Parameters
    ----------
    pr:
        PR number to land.
    gh:
        ``GhProtocol`` implementation (real or fake).
    sleep:
        Callable invoked to wait between polls.  Defaults to ``time.sleep``.
        Tests inject a list's ``append`` method to record durations without
        blocking.
    poll_interval:
        Seconds to wait between state polls (default 30 s).  The actual sleep
        is ``min(poll_interval, remaining_deadline)`` to avoid overshooting.
    max_wait:
        Maximum seconds to wait for the PR to become mergeable (default
        1800 s = 30 min).  When exceeded the loop returns
        ``{"outcome": "timeout"}``.
    only_if_contention_le:
        When set, the first poll checks ``pr_state["contention"]``.  If the
        value exceeds this ceiling the call returns
        ``{"outcome": "deferred", "reason": "contention=N"}`` immediately
        without taking any action.  Pass ``None`` (the default) to disable
        the contention gate.

    Returns
    -------
    LandResult
        ``outcome`` is one of ``"merged"``, ``"deferred"``, or ``"timeout"``.
        ``"merged"`` means the PR was squash-merged successfully.

    Raises
    ------
    LandError
        When the planner returns ``Step.FAIL`` — a hard blocker (CodeQL
        failure, BLOCKED merge state) that the lander cannot recover from.
    """
    deadline = time.monotonic() + max_wait

    while True:
        state = gh.pr_state(pr)

        # Contention gate: defer if the repo CI queue is too hot.
        if only_if_contention_le is not None:
            _raw = state.get("contention")
            contention: int = _raw if isinstance(_raw, int) else 0
            if contention > only_if_contention_le:
                return LandResult(outcome="deferred", reason=f"contention={contention}")

        step = next_step(state)

        if step == Step.DONE:
            return LandResult(outcome="merged", reason=None)

        if step == Step.FAIL:
            raise LandError(f"PR #{pr}: landing blocked — cannot proceed safely")

        if step == Step.MERGE:
            gh.merge(pr)
            return LandResult(outcome="merged", reason=None)

        if step == Step.REBASE:
            gh.update_branch(pr)

        elif step == Step.RESOLVE_THREADS:
            raw_ids: object = state.get("unresolved_thread_ids") or []
            thread_ids = [str(t) for t in raw_ids] if isinstance(raw_ids, list) else []
            for tid in thread_ids:
                gh.resolve_thread(tid)

        # Step.WAIT, or after REBASE/RESOLVE: check deadline then sleep.
        now = time.monotonic()
        if now >= deadline:
            return LandResult(outcome="timeout", reason=None)
        actual_sleep = min(poll_interval, deadline - now)
        sleep(actual_sleep)
