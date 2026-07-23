"""Data models for the A/B outcome-level eval harness.

Methodology (honest description)
----------------------------------
This harness measures whether ONMC memory context (cc_onmc) produces better
coding outcomes than a bare Claude Code agent (cc_alone).

Two conditions
--------------
cc_alone:
    Claude CLI invoked with only the task prompt.  No ONMC context, no
    prior-failure hints.  This is the REAL cold baseline — NOT simulated.
    When the baseline can genuinely fail, a positive ONMC delta is meaningful.

cc_onmc:
    Claude CLI invoked with an ONMC-style system preamble prepended to the
    prompt.  The preamble contains the same memory context that ONMC's
    compile_recall() and compile_guard() would inject in a real grounded run.

Gate
----
Each ABTask defines a ``gate_command`` — a shell command that exits 0 on
success and non-zero on failure.  The harness records whether the agent's
changes cause the gate to pass.  This is SWE-bench-style objective evaluation:
no rubrics, no human judges, just a deterministic pass/fail signal.

Honesty note
------------
A positive ONMC delta only counts on tasks where the cc_alone baseline can
genuinely fail.  Tasks where any competent agent trivially succeeds (both
conditions pass) still confirm ONMC does not regress.  The diagnostic signal
comes from tasks where cc_alone fails AND cc_onmc passes, proving the injected
context changed the outcome.

Fixture/offline mode
---------------------
Live mode runs a real ``claude`` subprocess per task per condition — requires
the claude CLI and a valid API key.  Fixture mode replays pre-recorded
``ABTaskResult`` payloads from fixtures.py, making CI deterministic and free
of LLM API calls.  Fixture results are clearly labelled as pre-recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Task format
# ---------------------------------------------------------------------------


@dataclass
class ABTask:
    """One outcome-level A/B eval task.

    The harness creates a temporary Git repo, runs ``setup_script`` to plant
    the buggy state, then runs the agent under both conditions (cc_alone and
    cc_onmc), then evaluates the result via ``gate_command``.

    Attributes
    ----------
    id:
        Stable identifier for this task (used in fixture keys and reports).
    description:
        Human-readable task description passed as the agent prompt.
    setup_script:
        Python source code executed inside the temp repo to plant the bug.
        Should write one or more Python files and a test file.  The test file
        MUST fail before the fix and pass after.
    gate_command:
        Shell command (run inside the temp repo) that exits 0 if the agent
        fixed the bug, non-zero otherwise.  Typically ``python -m pytest
        test_<name>.py -x -q``.
    onmc_hint:
        Context that ONMC's compile_recall/compile_guard would inject.
        Prepended to the prompt in the cc_onmc condition.  Should describe
        what dead-ends to avoid and what the correct approach is, as ONMC
        would recall from past failures.
    note:
        Human-readable explanation of why this task is meaningful for the eval.
    """

    id: str
    description: str
    setup_script: str
    gate_command: str
    onmc_hint: str
    note: str = ""


# ---------------------------------------------------------------------------
# Per-task per-condition result
# ---------------------------------------------------------------------------

ABCondition = Literal["cc_alone", "cc_onmc"]


@dataclass
class ABTaskResult:
    """Result of running one ABTask under one condition.

    Attributes
    ----------
    task_id:
        Corresponds to :attr:`ABTask.id`.
    condition:
        Which agent condition was used.
    passed:
        True when the gate command exited 0 after the agent ran.
    tokens:
        Total tokens consumed by the agent, when available.
    duration_s:
        Wall-clock seconds from agent invocation to gate evaluation.
    agent_output:
        Truncated stdout/response from the agent (for debugging).
    error:
        If the agent itself errored (not just the gate failing), a short
        description.  None on clean runs.
    fixture:
        True when this result was replayed from a fixture (not live).
    """

    task_id: str
    condition: ABCondition
    passed: bool
    tokens: int | None
    duration_s: float
    agent_output: str
    error: str | None = None
    fixture: bool = False

    def to_dict(self) -> dict[str, object]:
        """Serialise for JSON storage."""
        return {
            "task_id": self.task_id,
            "condition": self.condition,
            "passed": self.passed,
            "tokens": self.tokens,
            "duration_s": self.duration_s,
            "agent_output": self.agent_output,
            "error": self.error,
            "fixture": self.fixture,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> ABTaskResult:
        """Deserialise from JSON storage."""
        return cls(
            task_id=str(d["task_id"]),
            condition=d["condition"],  # type: ignore[arg-type]
            passed=bool(d["passed"]),
            tokens=d.get("tokens"),  # type: ignore[arg-type]
            duration_s=float(d.get("duration_s", 0.0)),  # type: ignore[arg-type]
            agent_output=str(d.get("agent_output", "")),
            error=d.get("error"),  # type: ignore[arg-type]
            fixture=bool(d.get("fixture", False)),
        )


# ---------------------------------------------------------------------------
# Per-task comparison (both conditions)
# ---------------------------------------------------------------------------


@dataclass
class ABTaskComparison:
    """Side-by-side result for one task across both conditions.

    Attributes
    ----------
    task:
        The task that was run.
    alone:
        Result for the cc_alone (cold, no ONMC) condition.
    onmc:
        Result for the cc_onmc (ONMC-grounded) condition.
    """

    task: ABTask
    alone: ABTaskResult
    onmc: ABTaskResult

    @property
    def onmc_wins(self) -> bool:
        """True when ONMC passed but cc_alone failed — meaningful delta."""
        return self.onmc.passed and not self.alone.passed

    @property
    def both_pass(self) -> bool:
        """True when both conditions pass — task too easy to differentiate."""
        return self.onmc.passed and self.alone.passed

    @property
    def both_fail(self) -> bool:
        """True when both conditions fail — task too hard for either."""
        return not self.onmc.passed and not self.alone.passed

    @property
    def alone_wins(self) -> bool:
        """True when cc_alone passed but ONMC failed — ONMC regression."""
        return self.alone.passed and not self.onmc.passed

    @property
    def token_delta(self) -> int | None:
        """ONMC tokens minus cc_alone tokens (negative = ONMC cheaper)."""
        if self.onmc.tokens is None or self.alone.tokens is None:
            return None
        return self.onmc.tokens - self.alone.tokens


# ---------------------------------------------------------------------------
# Aggregate report
# ---------------------------------------------------------------------------


@dataclass
class ABReport:
    """Full A/B comparison report across all tasks.

    Attributes
    ----------
    comparisons:
        Per-task side-by-side results.
    fixture:
        True when all results are from pre-recorded fixtures (CI mode).

    Honesty note
    ------------
    A positive ``onmc_win_rate`` only counts tasks where the baseline can
    genuinely fail (i.e. the cc_alone condition actually failed at least once
    in the fixture or live run).  Tasks where both conditions always pass show
    as ``both_pass`` and do not inflate the win rate.
    """

    comparisons: list[ABTaskComparison] = field(default_factory=list)
    fixture: bool = False

    @property
    def total_tasks(self) -> int:
        return len(self.comparisons)

    @property
    def onmc_wins(self) -> int:
        """Tasks where ONMC passed but cc_alone failed."""
        return sum(1 for c in self.comparisons if c.onmc_wins)

    @property
    def both_pass(self) -> int:
        """Tasks where both conditions passed."""
        return sum(1 for c in self.comparisons if c.both_pass)

    @property
    def both_fail(self) -> int:
        """Tasks where both conditions failed."""
        return sum(1 for c in self.comparisons if c.both_fail)

    @property
    def alone_wins(self) -> int:
        """Tasks where cc_alone passed but ONMC failed (regressions)."""
        return sum(1 for c in self.comparisons if c.alone_wins)

    @property
    def onmc_pass_rate(self) -> float:
        """Fraction of tasks where cc_onmc passed."""
        if not self.total_tasks:
            return 0.0
        return sum(1 for c in self.comparisons if c.onmc.passed) / self.total_tasks

    @property
    def alone_pass_rate(self) -> float:
        """Fraction of tasks where cc_alone passed."""
        if not self.total_tasks:
            return 0.0
        return sum(1 for c in self.comparisons if c.alone.passed) / self.total_tasks

    def to_dict(self) -> dict[str, object]:
        """Serialise for JSON output."""
        return {
            "fixture": self.fixture,
            "total_tasks": self.total_tasks,
            "onmc_wins": self.onmc_wins,
            "alone_wins": self.alone_wins,
            "both_pass": self.both_pass,
            "both_fail": self.both_fail,
            "onmc_pass_rate": round(self.onmc_pass_rate, 4),
            "alone_pass_rate": round(self.alone_pass_rate, 4),
            "comparisons": [
                {
                    "task_id": c.task.id,
                    "task_note": c.task.note,
                    "alone": c.alone.to_dict(),
                    "onmc": c.onmc.to_dict(),
                    "onmc_wins": c.onmc_wins,
                    "both_pass": c.both_pass,
                    "both_fail": c.both_fail,
                    "token_delta": c.token_delta,
                }
                for c in self.comparisons
            ],
        }

    def to_markdown(self) -> str:
        """Render the A/B report as a markdown comparison table."""
        mode = "FIXTURE (pre-recorded, no live LLM)" if self.fixture else "LIVE"
        lines = [
            "## A/B Eval Report — ONMC+Claude Code vs Claude Code alone",
            "",
            f"**Mode:** {mode}",
            f"**Tasks:** {self.total_tasks}",
            "",
            "| Task | cc_alone | cc_onmc | Outcome | ONMC tokens | Alone tokens | Delta |",
            "|---|---|---|---|---|---|---|",
        ]
        for c in self.comparisons:
            outcome = (
                "ONMC wins" if c.onmc_wins
                else "tie-pass" if c.both_pass
                else "tie-fail" if c.both_fail
                else "REGRESSION"
            )
            alone_tok = str(c.alone.tokens) if c.alone.tokens is not None else "n/a"
            onmc_tok = str(c.onmc.tokens) if c.onmc.tokens is not None else "n/a"
            delta_tok = str(c.token_delta) if c.token_delta is not None else "n/a"
            lines.append(
                f"| {c.task.id}"
                f" | {'pass' if c.alone.passed else 'fail'}"
                f" | {'pass' if c.onmc.passed else 'fail'}"
                f" | {outcome}"
                f" | {onmc_tok}"
                f" | {alone_tok}"
                f" | {delta_tok}"
                f" |"
            )
        lines += [
            "",
            "### Aggregate",
            "",
            f"- **cc_alone pass rate:** {self.alone_pass_rate:.0%}"
            f" ({sum(1 for c in self.comparisons if c.alone.passed)}/{self.total_tasks})",
            f"- **cc_onmc pass rate:** {self.onmc_pass_rate:.0%}"
            f" ({sum(1 for c in self.comparisons if c.onmc.passed)}/{self.total_tasks})",
            f"- **ONMC wins (cc_alone failed, cc_onmc passed):** {self.onmc_wins}",
            f"- **Regressions (cc_alone passed, cc_onmc failed):** {self.alone_wins}",
            f"- **Both pass (task too easy to differentiate):** {self.both_pass}",
            f"- **Both fail (task too hard for either):** {self.both_fail}",
            "",
            "> **Honesty note:** A positive ONMC delta only counts on tasks where the",
            "> cc_alone baseline can genuinely fail.  'tie-pass' tasks confirm ONMC",
            "> does not regress on easy tasks but contribute no signal about ONMC value.",
            "> The fixture baseline is pre-recorded, NOT auto-fail — results reflect",
            "> realistic agent behaviour on these tasks.",
        ]
        return "\n".join(lines)
