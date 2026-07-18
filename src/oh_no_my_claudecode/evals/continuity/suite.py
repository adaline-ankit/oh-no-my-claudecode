"""Default task suite for the continuity eval SIM.

The suite is designed to exercise every failure mode that ONMC's policy
handles differently from naive orchestration:

Composition (~10 tasks)
-----------------------
- 6 clean tasks  — straightforward agent successes
- 1 false_green  — tests pass but zero diff (agent gave up silently)
- 1 broken       — agent leaves tests failing (mid-sequence to expose cascade)
- 1 scope_violation — agent edits a protected path outside its scope
- 1 transient_env   — environment error (permission denied / timeout)

Order
-----
false_green and scope_violation appear BEFORE the broken task so they are
exposed to naive's false-acceptance bug.  The broken task is mid-sequence
(position 6 of 10) so three clean tasks after it cascade-fail under naive,
demonstrating the poisoning problem.  transient_env comes last to show it
does not interact with cascade.

Under naive policy (expected results)
--------------------------------------
- Tasks 1-5: 3 correctly completed, 2 false_completions (false_green + scope)
- Task 6 (broken): fails, tree poisoned
- Tasks 7-9 (clean): 3 cascade failures
- Task 10 (transient_env): fails on its own (not a cascade victim)

correctly_completed=3, false_completions=2, cascade_failures=3,
interventions_needed=3 (1 poisoned tree + 2 false_completions).

Under ONMC policy (expected results)
--------------------------------------
- All 6 clean tasks: completed
- false_green: rejected (no diff)
- broken: isolated, reverted, tree stays healthy
- scope_violation: rejected
- transient_env: retried once, skipped safely

correctly_completed=6, false_completions=0, cascade_failures=0,
interventions_needed=0.
"""

from __future__ import annotations

from oh_no_my_claudecode.evals.continuity.models import ContinuityTask


# ---------------------------------------------------------------------------
# Individual task definitions
# ---------------------------------------------------------------------------

TASK_ADD_VALIDATION = ContinuityTask(
    id="add_validation",
    outcome="clean",
    owned_paths=["utils.py"],
    protected_paths=["config.py", "db.py"],
    note="Add input validation to utils.py — straightforward clean task.",
)

TASK_FALSE_GREEN_TYPE_HINTS = ContinuityTask(
    id="false_green_type_hints",
    outcome="false_green",
    owned_paths=["utils.py"],
    protected_paths=["config.py"],
    note=(
        "Add type hints to existing functions — agent passes tests but produces "
        "zero diff (gave up after seeing tests already pass). "
        "Naive accepts this as done; ONMC's no-diff check rejects it."
    ),
)

TASK_FIX_PARSER_OFFBYONE = ContinuityTask(
    id="fix_parser_offbyone",
    outcome="clean",
    owned_paths=["parser.py"],
    protected_paths=["config.py"],
    note="Fix off-by-one error in parser.py — clean task, in-scope.",
)

TASK_SCOPE_VIOLATION_CONFIG = ContinuityTask(
    id="scope_violation_config",
    outcome="scope_violation",
    owned_paths=["handler.py"],
    protected_paths=["config.py"],
    note=(
        "Fix a bug in handler.py, but the agent also edits config.py (protected). "
        "Tests pass so naive accepts it; ONMC's in-scope check rejects the diff."
    ),
)

TASK_ADD_ERROR_HANDLING = ContinuityTask(
    id="add_error_handling",
    outcome="clean",
    owned_paths=["fetcher.py"],
    protected_paths=["config.py", "db.py"],
    note="Add try/except around network calls in fetcher.py — clean task.",
)

# ⚠  MID-SEQUENCE BROKEN TASK — poisons the tree for naive
TASK_BROKEN_DB_REFACTOR = ContinuityTask(
    id="broken_db_refactor",
    outcome="broken",
    owned_paths=["db.py"],
    protected_paths=["config.py"],
    note=(
        "Refactor db.py connection pooling — agent leaves the test suite red "
        "(forgot to update a call-site). Naive: tree poisoned, all subsequent "
        "tasks cascade-fail. ONMC: isolated + reverted, tree stays healthy."
    ),
)

TASK_ADD_LOGGING = ContinuityTask(
    id="add_logging",
    outcome="clean",
    owned_paths=["router.py"],
    protected_paths=["config.py", "db.py"],
    note="Add structured logging to router.py — clean task after the broken one.",
)

TASK_FIX_REGEX = ContinuityTask(
    id="fix_regex",
    outcome="clean",
    owned_paths=["validator.py"],
    protected_paths=["config.py"],
    note="Fix greedy-vs-lazy regex in validator.py — clean task after the broken one.",
)

TASK_ADD_CACHING = ContinuityTask(
    id="add_caching",
    outcome="clean",
    owned_paths=["cache.py"],
    protected_paths=["config.py", "db.py"],
    note="Add LRU caching to cache.py — clean task after the broken one.",
)

TASK_TRANSIENT_ENV_TIMEOUT = ContinuityTask(
    id="transient_env_timeout",
    outcome="transient_env",
    owned_paths=["build_step.py"],
    protected_paths=["config.py"],
    note=(
        "Build step times out due to a flaky CI environment — not a logic bug. "
        "Naive: failure. ONMC: retried once, skipped safely, no tree poisoning."
    ),
)


# ---------------------------------------------------------------------------
# Default suite (ordered for maximum signal)
# ---------------------------------------------------------------------------

BUILTIN_TASKS: list[ContinuityTask] = [
    # 1. Clean (before broken) — naive correctly completes
    TASK_ADD_VALIDATION,
    # 2. False-green (before broken) — naive falsely accepts, ONMC rejects
    TASK_FALSE_GREEN_TYPE_HINTS,
    # 3. Clean (before broken)
    TASK_FIX_PARSER_OFFBYONE,
    # 4. Scope violation (before broken) — naive falsely accepts, ONMC rejects
    TASK_SCOPE_VIOLATION_CONFIG,
    # 5. Clean (before broken)
    TASK_ADD_ERROR_HANDLING,
    # 6. BROKEN (mid-sequence) — naive: tree poisoned; ONMC: isolated, reverted
    TASK_BROKEN_DB_REFACTOR,
    # 7. Clean (after broken) — naive: CASCADE FAIL; ONMC: completed
    TASK_ADD_LOGGING,
    # 8. Clean (after broken) — naive: CASCADE FAIL; ONMC: completed
    TASK_FIX_REGEX,
    # 9. Clean (after broken) — naive: CASCADE FAIL; ONMC: completed
    TASK_ADD_CACHING,
    # 10. Transient env — naive: failure; ONMC: retry+skip, no poisoning
    TASK_TRANSIENT_ENV_TIMEOUT,
]
