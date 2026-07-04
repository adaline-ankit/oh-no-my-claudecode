"""CI-fix autopilot — turn a failed PR's CI log into a deterministic fix plan.

``onmc fix-ci <pr>`` reads a failed CI run's log, extracts the failing step and
the error excerpt, recalls related past dead-ends (via the guard/recall
compilers), maps the error to likely-fix source files (via the structural code
graph), and emits a fix *plan* — including a suggested swarm unit it would run.

The plan is **plan-only by default**: nothing is spawned, no agent runs, no
money is spent. The CI-log fetch is injectable so the core planner
(:func:`oh_no_my_claudecode.fixci.autopilot.plan_ci_fix`) is pure over an
in-memory ``log_text`` and fully offline/deterministic in tests. The real
``gh run view --log-failed`` shell-out lives in
:func:`oh_no_my_claudecode.fixci.autopilot.fetch_ci_log` and is never exercised
by tests.
"""

from __future__ import annotations

from oh_no_my_claudecode.fixci.autopilot import (
    CiFailure,
    fetch_ci_log,
    plan_ci_fix,
)

__all__ = ["CiFailure", "fetch_ci_log", "plan_ci_fix"]
