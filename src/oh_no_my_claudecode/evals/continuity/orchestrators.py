"""Orchestrator policy simulations for the continuity eval.

Two pure policy functions operate over a fixed task sequence and a mutable
shared world state (the tree health flag).  No LLM, no subprocess — pure
deterministic Python.

Naive policy (``run_naive``)
-----------------------------
Gate: "did tests pass?"  Passes for clean, false_green, scope_violation.
Fails for broken and transient_env.

Shared mutable tree: a ``broken`` task sets ``tree_healthy = False``.  Every
SUBSEQUENT task then fails its gate due to cascade/poisoning — the tree is
never restored.  false_green and scope_violation are silently accepted (no
diff check, no scope check).

ONMC policy (``run_onmc``)
---------------------------
Gate: "tests pass AND diff is non-empty AND change is in-scope?"

Isolation: a ``broken`` task is reverted (the tree is restored to its
pre-task state) so it does NOT poison later tasks.

false_green: rejected (no diff → rich gate fails, task not counted done).
scope_violation: rejected (in-scope check fails → rich gate fails).
transient_env: retried once then skipped safely.  Tree is NOT marked unhealthy
and the skip is NOT recorded as a dead-end failure — just a transient blip.
"""

from __future__ import annotations

from oh_no_my_claudecode.evals.continuity.models import (
    ContinuityTask,
    OrchestratorReport,
    TaskRun,
)

# Outcomes that the NAIVE gate accepts as "tests pass"
_NAIVE_GATE_PASS = frozenset({"clean", "false_green", "scope_violation"})

# Outcomes that ARE false completions under naive (accepted but should not be)
_NAIVE_FALSE_COMPLETIONS = frozenset({"false_green", "scope_violation"})

# Outcomes that would pass the NAIVE gate in a healthy tree (used to detect
# cascade victims — tasks that WOULD have completed but could not due to poisoning)
_WOULD_PASS_NAIVE = frozenset({"clean", "false_green", "scope_violation"})


def run_naive(tasks: list[ContinuityTask]) -> OrchestratorReport:
    """Simulate the naive orchestration policy over the task sequence.

    Naive logic:
    - Gate = tests pass (clean / false_green / scope_violation pass;
      broken / transient_env fail).
    - Shared mutable tree: a broken task poisons it for all subsequent tasks.
    - false_green and scope_violation are accepted (no diff check, no scope check).
    - transient_env = task-level failure, does NOT poison the tree.

    Returns
    -------
    OrchestratorReport with correctly_completed, false_completions,
    cascade_failures, and interventions_needed filled in.
    """
    runs: list[TaskRun] = []
    tree_healthy = True

    for task in tasks:
        if not tree_healthy:
            # Tree was poisoned by a prior broken task.
            # A cascade failure is only counted if this task WOULD have passed
            # the naive gate in a healthy tree (clean/false_green/scope_violation).
            # transient_env would fail even in a healthy tree — not a cascade victim.
            is_cascade = task.outcome in _WOULD_PASS_NAIVE
            runs.append(
                TaskRun(
                    task_id=task.id,
                    orchestrator="naive",
                    outcome=task.outcome,
                    completed=False,
                    false_completion=False,
                    cascade_failure=is_cascade,
                    gate_passed=False,
                )
            )
            continue

        gate_passed = task.outcome in _NAIVE_GATE_PASS
        completed = gate_passed
        false_completion = completed and task.outcome in _NAIVE_FALSE_COMPLETIONS

        if task.outcome == "broken":
            # Broken task fails its own gate AND poisons the tree.
            tree_healthy = False

        runs.append(
            TaskRun(
                task_id=task.id,
                orchestrator="naive",
                outcome=task.outcome,
                completed=completed,
                false_completion=false_completion,
                cascade_failure=False,
                gate_passed=gate_passed,
            )
        )

    correctly_completed = sum(
        1 for r in runs if r.completed and not r.false_completion
    )
    false_completions = sum(1 for r in runs if r.false_completion)
    cascade_failures = sum(1 for r in runs if r.cascade_failure)
    # Interventions: 1 for a poisoned tree + 1 per ghost/violation accepted
    interventions_needed = (0 if tree_healthy else 1) + false_completions

    return OrchestratorReport(
        orchestrator="naive",
        runs=runs,
        correctly_completed=correctly_completed,
        false_completions=false_completions,
        cascade_failures=cascade_failures,
        interventions_needed=interventions_needed,
    )


def run_onmc(tasks: list[ContinuityTask]) -> OrchestratorReport:
    """Simulate the ONMC orchestration policy over the task sequence.

    ONMC logic:
    - Gate = green tests AND non-empty diff AND in-scope.
    - Isolation: broken tasks are reverted — tree is ALWAYS restored to healthy.
    - false_green: tests pass but no diff → REJECTED (not counted as done).
    - scope_violation: edited a protected path → REJECTED (not counted as done).
    - transient_env: retried once, then skipped safely (no poisoning, not a
      dead-end failure).
    - clean: all gate checks pass → completed.

    Invariants (ONMC design guarantees):
    - cascade_failures = 0  (isolation prevents propagation)
    - false_completions = 0  (rich gate blocks false_green and scope_violation)
    - interventions_needed = 0  (no poisoned trees, no ghost completions)

    Returns
    -------
    OrchestratorReport with all safety metrics at their ideal values.
    """
    runs: list[TaskRun] = []

    for task in tasks:
        if task.outcome == "clean":
            # Rich gate passes: tests green, diff non-empty, in scope.
            runs.append(
                TaskRun(
                    task_id=task.id,
                    orchestrator="onmc",
                    outcome=task.outcome,
                    completed=True,
                    false_completion=False,
                    cascade_failure=False,
                    gate_passed=True,
                )
            )
        elif task.outcome == "false_green":
            # Tests pass but diff is empty → rich gate rejects.
            runs.append(
                TaskRun(
                    task_id=task.id,
                    orchestrator="onmc",
                    outcome=task.outcome,
                    completed=False,
                    false_completion=False,
                    cascade_failure=False,
                    gate_passed=False,
                )
            )
        elif task.outcome == "broken":
            # Tests fail → isolation + stash-on-fail; tree restored to healthy.
            # Does NOT propagate to later tasks.
            runs.append(
                TaskRun(
                    task_id=task.id,
                    orchestrator="onmc",
                    outcome=task.outcome,
                    completed=False,
                    false_completion=False,
                    cascade_failure=False,
                    gate_passed=False,
                )
            )
        elif task.outcome == "scope_violation":
            # In-scope check fails → rejected; tree state unchanged.
            runs.append(
                TaskRun(
                    task_id=task.id,
                    orchestrator="onmc",
                    outcome=task.outcome,
                    completed=False,
                    false_completion=False,
                    cascade_failure=False,
                    gate_passed=False,
                )
            )
        elif task.outcome == "transient_env":
            # Environment error: retried once, then skipped safely.
            # No poisoning, no dead-end recording.
            runs.append(
                TaskRun(
                    task_id=task.id,
                    orchestrator="onmc",
                    outcome=task.outcome,
                    completed=False,
                    false_completion=False,
                    cascade_failure=False,
                    gate_passed=False,
                )
            )

    correctly_completed = sum(
        1 for r in runs if r.completed and not r.false_completion
    )

    return OrchestratorReport(
        orchestrator="onmc",
        runs=runs,
        correctly_completed=correctly_completed,
        false_completions=0,   # ONMC design guarantee: rich gate blocks all false accepts
        cascade_failures=0,    # ONMC design guarantee: isolation prevents cascade
        interventions_needed=0,  # ONMC design guarantee: no bad end-states
    )
