"""Data models for the autonomous-continuity eval SIM.

Methodology (honest description)
----------------------------------
This harness measures ORCHESTRATION SAFETY — what happens across a whole
unattended multi-task run — not per-task precision (the A/B harness covers
that).  The differentiator is POLICY, not model quality, so the simulation is
deterministic: no LLM calls, no subprocess, no network.  Each task has a
pre-assigned ``outcome`` that the two orchestrator policies interpret
differently.

Task outcomes
-------------
``clean``
    Agent produced green tests AND a real diff AND edited only owned paths.
    Both orchestrators count this as a success.

``false_green``
    Tests pass but the diff is empty — the agent gave up and changed nothing.
    Naive accepts this (tests pass = done).  ONMC rejects it (no diff).

``broken``
    Agent left the shared tree with failing tests.  Naive: fails AND poisons
    the tree so every subsequent task cascades.  ONMC: isolates and reverts,
    tree stays healthy.

``scope_violation``
    Agent edited a protected path outside its owned scope.  Naive: accepts
    (tests pass).  ONMC: rejects (out-of-scope check fails).

``transient_env``
    Agent failed with an environment error (permission denied, timeout).
    Naive: failure.  ONMC: retried once then skipped safely — no tree
    poisoning, not recorded as a dead-end either.

Metrics
-------
``correctly_completed``
    Clean tasks that were actually accepted and committed.  Higher = better.

``false_completions``
    false_green or scope_violation tasks accepted as done — BAD.  Lower = better
    (0 is ideal).

``cascade_failures``
    Tasks that failed ONLY because a prior broken task poisoned the shared tree.
    Lower = better (ONMC = 0 by design via isolation).

``interventions_needed``
    Count of bad end-states a human must manually fix at session end:
      - 1 if the shared tree is unhealthy (poisoned by a broken task)
      - +1 per accepted false-green
      - +1 per accepted scope violation
    Lower = better (ONMC = 0 by design).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Task definition
# ---------------------------------------------------------------------------

TaskOutcome = Literal["clean", "false_green", "broken", "scope_violation", "transient_env"]
OrchestratorName = Literal["naive", "onmc"]


@dataclass
class ContinuityTask:
    """One task in the autonomous-continuity session.

    Attributes
    ----------
    id:
        Stable identifier (used in reports and tests).
    outcome:
        Pre-assigned ground-truth outcome the simulation uses.  Both
        orchestrators interpret this according to their own policy gate.
    owned_paths:
        Paths this task is permitted to edit (used by ONMC's in-scope check).
    protected_paths:
        Paths this task must NOT edit.  A ``scope_violation`` task edits one
        of these; ONMC's gate catches it, naive's gate does not.
    note:
        Human-readable description of what this task represents.
    """

    id: str
    outcome: TaskOutcome
    owned_paths: list[str] = field(default_factory=list)
    protected_paths: list[str] = field(default_factory=list)
    note: str = ""


# ---------------------------------------------------------------------------
# Per-task result
# ---------------------------------------------------------------------------


@dataclass
class TaskRun:
    """Result of one :class:`ContinuityTask` under one orchestrator's policy.

    Attributes
    ----------
    task_id:
        Corresponds to :attr:`ContinuityTask.id`.
    orchestrator:
        Which policy evaluated this task.
    outcome:
        The underlying :attr:`ContinuityTask.outcome` (stored here so the run
        is self-contained for reporting without needing the task list).
    completed:
        True when the orchestrator accepted the task as done.
    false_completion:
        True when the task was accepted but SHOULD NOT have been (false_green
        or scope_violation accepted by naive policy).
    cascade_failure:
        True when the task failed only because a prior broken task poisoned the
        shared tree (naive policy only — ONMC isolation prevents this).
    gate_passed:
        The raw gate result under this orchestrator's policy.
    """

    task_id: str
    orchestrator: OrchestratorName
    outcome: TaskOutcome
    completed: bool
    false_completion: bool
    cascade_failure: bool
    gate_passed: bool


# ---------------------------------------------------------------------------
# Per-orchestrator aggregate
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorReport:
    """Aggregate metrics for one orchestrator across the full task sequence.

    Attributes
    ----------
    orchestrator:
        Which policy produced this report.
    runs:
        Per-task results.
    correctly_completed:
        Clean tasks accepted as done (higher = better).
    false_completions:
        false_green or scope_violation tasks accepted (lower = better; 0 ideal).
    cascade_failures:
        Tasks that failed only because a prior broken task poisoned the tree
        (lower = better; ONMC = 0 by design).
    interventions_needed:
        Total bad end-states a human must fix at session end (lower = better;
        ONMC = 0 by design).
    """

    orchestrator: OrchestratorName
    runs: list[TaskRun]
    correctly_completed: int
    false_completions: int
    cascade_failures: int
    interventions_needed: int

    @property
    def total_tasks(self) -> int:
        """Total tasks in the session."""
        return len(self.runs)

    @property
    def total_completed(self) -> int:
        """Tasks accepted as done (correct + false)."""
        return sum(1 for r in self.runs if r.completed)

    def to_dict(self) -> dict[str, object]:
        """Serialise to JSON-compatible dict."""
        return {
            "orchestrator": self.orchestrator,
            "total_tasks": self.total_tasks,
            "correctly_completed": self.correctly_completed,
            "false_completions": self.false_completions,
            "cascade_failures": self.cascade_failures,
            "interventions_needed": self.interventions_needed,
            "runs": [
                {
                    "task_id": r.task_id,
                    "outcome": r.outcome,
                    "completed": r.completed,
                    "false_completion": r.false_completion,
                    "cascade_failure": r.cascade_failure,
                    "gate_passed": r.gate_passed,
                }
                for r in self.runs
            ],
        }


# ---------------------------------------------------------------------------
# Side-by-side comparison
# ---------------------------------------------------------------------------

_OUTCOME_ICON: dict[str, str] = {
    "clean": "clean",
    "false_green": "false-green",
    "broken": "broken",
    "scope_violation": "scope-violation",
    "transient_env": "transient-env",
}


def _run_label(r: TaskRun) -> str:
    if r.cascade_failure:
        return "cascade-fail ✗"
    if r.false_completion:
        return "false-complete ⚠"
    if r.completed:
        return "completed ✓"
    return "rejected/skipped"


@dataclass
class ContinuityComparison:
    """Side-by-side comparison of naive vs ONMC orchestration.

    Attributes
    ----------
    naive:
        Report from the naive policy (tests-pass-only gate, shared mutable tree).
    onmc:
        Report from the ONMC policy (rich gate, isolation, scope enforcement).
    """

    naive: OrchestratorReport
    onmc: OrchestratorReport

    @property
    def correctly_completed_delta(self) -> int:
        """ONMC minus naive correctly_completed (positive = ONMC does more real work)."""
        return self.onmc.correctly_completed - self.naive.correctly_completed

    @property
    def false_completions_delta(self) -> int:
        """ONMC minus naive false_completions (negative = ONMC accepts fewer ghosts)."""
        return self.onmc.false_completions - self.naive.false_completions

    @property
    def cascade_failures_delta(self) -> int:
        """ONMC minus naive cascade_failures (negative = ONMC prevents cascades)."""
        return self.onmc.cascade_failures - self.naive.cascade_failures

    @property
    def interventions_delta(self) -> int:
        """ONMC minus naive interventions_needed (negative = ONMC leaves fewer messes)."""
        return self.onmc.interventions_needed - self.naive.interventions_needed

    def to_dict(self) -> dict[str, object]:
        """Serialise to JSON-compatible dict."""
        return {
            "naive": self.naive.to_dict(),
            "onmc": self.onmc.to_dict(),
            "deltas": {
                "correctly_completed": self.correctly_completed_delta,
                "false_completions": self.false_completions_delta,
                "cascade_failures": self.cascade_failures_delta,
                "interventions_needed": self.interventions_delta,
            },
        }

    def to_markdown(self) -> str:
        """Render a comparison table: naive vs ONMC with per-task breakdown."""
        n = self.naive
        o = self.onmc

        def _delta(d: int, *, lower_is_better: bool = True) -> str:
            if d == 0:
                return "—"
            sign = "+" if d > 0 else ""
            if lower_is_better:
                arrow = "↓" if d < 0 else "↑"
            else:
                arrow = "↑" if d > 0 else "↓"
            return f"{sign}{d} {arrow}"

        lines = [
            "## Continuity Eval — Orchestration-Safety SIM (naive vs ONMC)",
            "",
            "> **Methodology (SIM):** deterministic policy simulation — no LLM, no subprocess,",
            "> fully reproducible in CI.  Each task carries a pre-assigned outcome; both",
            "> orchestrator policies are applied to the identical task sequence.",
            "> This measures where ONMC's policy beats naive orchestration over a whole",
            "> unattended session, complementing the per-task A/B (which ties on precision).",
            "",
            "| Metric | Naive | ONMC | Delta |",
            "|---|---|---|---|",
            (
                f"| Correctly completed (↑ better)"
                f" | {n.correctly_completed}/{n.total_tasks}"
                f" | {o.correctly_completed}/{o.total_tasks}"
                f" | {_delta(self.correctly_completed_delta, lower_is_better=False)} |"
            ),
            (
                f"| False completions accepted (↓ better)"
                f" | {n.false_completions}"
                f" | {o.false_completions}"
                f" | {_delta(self.false_completions_delta)} |"
            ),
            (
                f"| Cascade failures (↓ better)"
                f" | {n.cascade_failures}"
                f" | {o.cascade_failures}"
                f" | {_delta(self.cascade_failures_delta)} |"
            ),
            (
                f"| Human interventions needed (↓ better)"
                f" | {n.interventions_needed}"
                f" | {o.interventions_needed}"
                f" | {_delta(self.interventions_delta)} |"
            ),
            "",
            "### Per-task breakdown",
            "",
            "| Task | Outcome | Naive result | ONMC result |",
            "|---|---|---|---|",
        ]

        naive_by_id = {r.task_id: r for r in n.runs}
        onmc_by_id = {r.task_id: r for r in o.runs}
        for tid in (r.task_id for r in n.runs):
            nr = naive_by_id[tid]
            or_ = onmc_by_id[tid]
            outcome_display = _OUTCOME_ICON.get(nr.outcome, nr.outcome)
            lines.append(
                f"| {tid} | {outcome_display} | {_run_label(nr)} | {_run_label(or_)} |"
            )

        lines += [
            "",
            "### Glossary",
            "",
            "- **false-complete ⚠** — accepted as done but the diff was empty (false_green)",
            "  or edited a protected path (scope_violation). A human must detect and undo it.",
            "- **cascade-fail ✗** — failed only because a prior broken task poisoned the shared",
            "  tree. The task itself was fine; ONMC isolation would have saved it.",
            "- **rejected/skipped** — ONMC's rich gate refused to commit (no diff, out-of-scope,",
            "  broken tests, or transient error). Tree is always restored to a clean state.",
        ]

        return "\n".join(lines)
