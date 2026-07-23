"""Data models for the A/B outcome-level eval harness.

Methodology (honest description)
----------------------------------
This harness measures whether ONMC memory context (cc_onmc) produces better
coding outcomes than a bare Claude Code agent (cc_alone).

Three conditions
----------------
cc_alone:
    Claude CLI invoked with only the task prompt.  No ONMC context, no
    prior-failure hints.  This is the REAL cold baseline — NOT simulated.
    When the baseline can genuinely fail, a positive ONMC delta is meaningful.

cc_onmc:
    Claude CLI invoked with context retrieved from a temporary ONMC brain via
    the production compile_prompt_recall() path.  The brain is seeded with the
    hand-authored ``onmc_hint`` string.

cc_onmc_auto:
    Claude CLI invoked with context retrieved from a temporary ONMC brain that
    was seeded by INGESTING a realistic repository artifact (``grounding_doc``)
    through the real doc-ingest → recall pipeline — no hand-written hint.
    This condition tests whether onmc's OWN capture→recall reproduces the
    hand-hint win (the product-loop question).

Gate
----
Each ABTask defines a ``gate_command`` — a structured command that exits 0 on
success and non-zero on failure. The harness records whether the agent's
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
Live mode runs a real ``claude`` subprocess per task per condition using the
CLI's configured authentication. Fixture mode replays pre-recorded
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
        Structured command (run without a shell inside the temp repo) that exits 0 if the agent
        fixed the bug, non-zero otherwise.  Typically ``python -m pytest
        test_<name>.py -x -q``.
    onmc_hint:
        Prior repository lesson seeded into a temporary ONMC brain. The live
        cc_onmc condition retrieves it through the production recall compiler.
    note:
        Human-readable explanation of why this task is meaningful for the eval.
    """

    id: str
    description: str
    setup_script: str
    gate_command: str
    onmc_hint: str
    note: str = ""
    repo_url: str | None = None
    repo_commit: str | None = None
    setup_patch: str = ""
    setup_commands: tuple[tuple[str, ...], ...] = ()
    pass_to_pass_commands: tuple[tuple[str, ...], ...] = ()
    protected_paths: tuple[str, ...] = ()
    hidden_gate_test: str = ""
    """When non-empty, this pytest source is WITHHELD during setup (the agent never
    sees it) and written to the working dir only after the agent finishes, before
    the gate is evaluated.  This preserves info-asymmetry: the private rule encoded
    in the test is not leakable by reading the test file.  When empty, behaves
    exactly like the old setup_script-includes-test path (backward compatible)."""

    grounding_doc: str = ""
    """A realistic repository artifact (prose excerpt from a doc, postmortem, or
    DESIGN.md) that CONTAINS the private rule the way a real codebase document
    would state it.  Used by the ``cc_onmc_auto`` condition: this text is ingested
    into a temporary ONMC brain via the real doc-ingest pipeline, then recall is
    compiled from it — no hand-written hint.  When empty, ``cc_onmc_auto`` returns
    an empty context (effectively a cold run)."""


# ---------------------------------------------------------------------------
# Per-task per-condition result
# ---------------------------------------------------------------------------

ABCondition = Literal["cc_alone", "cc_onmc", "cc_onmc_auto"]


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
    evidence_kind: Literal["fixture", "live"] = "live"
    gate_output: str = ""
    changed_files: list[str] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    turns: int | None = None
    cost_usd: float | None = None
    model: str | None = None
    repo_url: str | None = None
    repo_commit: str | None = None
    prompt_sha256: str = ""
    stub_fails_precheck: bool | None = None
    """True when the stub (pre-agent) fails the gate — as expected.
    False when the stub already passes (task has no signal — surfaces as a warning).
    None means the precheck was not performed (e.g. fixture mode)."""

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
            "evidence_kind": self.evidence_kind,
            "gate_output": self.gate_output,
            "changed_files": self.changed_files,
            "additions": self.additions,
            "deletions": self.deletions,
            "turns": self.turns,
            "cost_usd": self.cost_usd,
            "model": self.model,
            "repo_url": self.repo_url,
            "repo_commit": self.repo_commit,
            "prompt_sha256": self.prompt_sha256,
            "stub_fails_precheck": self.stub_fails_precheck,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> ABTaskResult:
        """Deserialise from JSON storage."""
        changed_raw = d.get("changed_files", [])
        changed_files = [str(item) for item in changed_raw] if isinstance(changed_raw, list) else []

        def as_int(value: object, default: int = 0) -> int:
            return value if isinstance(value, int) and not isinstance(value, bool) else default

        def as_optional_int(value: object) -> int | None:
            return value if isinstance(value, int) and not isinstance(value, bool) else None

        cost_raw = d.get("cost_usd")
        cost_usd = float(cost_raw) if isinstance(cost_raw, (int, float)) else None
        evidence_kind: Literal["fixture", "live"] = (
            "fixture" if bool(d.get("fixture", False)) else "live"
        )
        stub_raw = d.get("stub_fails_precheck")
        stub_fails_precheck: bool | None = bool(stub_raw) if stub_raw is not None else None
        return cls(
            task_id=str(d["task_id"]),
            condition=d["condition"],  # type: ignore[arg-type]
            passed=bool(d["passed"]),
            tokens=d.get("tokens"),  # type: ignore[arg-type]
            duration_s=float(d.get("duration_s", 0.0)),  # type: ignore[arg-type]
            agent_output=str(d.get("agent_output", "")),
            error=d.get("error"),  # type: ignore[arg-type]
            fixture=bool(d.get("fixture", False)),
            evidence_kind=evidence_kind,
            gate_output=str(d.get("gate_output", "")),
            changed_files=changed_files,
            additions=as_int(d.get("additions")),
            deletions=as_int(d.get("deletions")),
            turns=as_optional_int(d.get("turns")),
            cost_usd=cost_usd,
            model=str(d["model"]) if d.get("model") is not None else None,
            repo_url=str(d["repo_url"]) if d.get("repo_url") is not None else None,
            repo_commit=(str(d["repo_commit"]) if d.get("repo_commit") is not None else None),
            prompt_sha256=str(d.get("prompt_sha256", "")),
            stub_fails_precheck=stub_fails_precheck,
        )


# ---------------------------------------------------------------------------
# Per-task comparison (both conditions)
# ---------------------------------------------------------------------------


@dataclass
class ABTaskComparison:
    """Side-by-side result for one task across all conditions.

    Attributes
    ----------
    task:
        The task that was run.
    alone:
        Result for the cc_alone (cold, no ONMC) condition.
    onmc:
        Result for the cc_onmc (ONMC hand-hint) condition.
    auto:
        Result for the cc_onmc_auto condition (auto-captured from grounding_doc),
        or None when the condition was not run (e.g. no grounding_doc).
    """

    task: ABTask
    alone: ABTaskResult
    onmc: ABTaskResult
    auto: ABTaskResult | None = None

    @property
    def onmc_wins(self) -> bool:
        """True when ONMC passed but cc_alone failed — meaningful delta."""
        return self.onmc.passed and not self.alone.passed

    @property
    def auto_wins(self) -> bool:
        """True when cc_onmc_auto passed but cc_alone failed — product-loop win.

        This property answers the question: does the REAL ingest→recall pipeline
        supply enough context (without a hand-written hint) to change the outcome?
        """
        if self.auto is None:
            return False
        return self.auto.passed and not self.alone.passed

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

    @staticmethod
    def _reduction_pct(alone: float | int | None, onmc: float | int | None) -> float | None:
        if alone is None or onmc is None or alone <= 0:
            return None
        return ((float(alone) - float(onmc)) / float(alone)) * 100

    @property
    def token_reduction_pct(self) -> float | None:
        """Token reduction relative to cc_alone (positive = ONMC cheaper)."""
        return self._reduction_pct(self.alone.tokens, self.onmc.tokens)

    @property
    def turn_reduction_pct(self) -> float | None:
        """Agent-turn reduction relative to cc_alone."""
        return self._reduction_pct(self.alone.turns, self.onmc.turns)

    @property
    def cost_reduction_pct(self) -> float | None:
        """Reported Claude cost reduction relative to cc_alone."""
        return self._reduction_pct(self.alone.cost_usd, self.onmc.cost_usd)

    @property
    def duration_reduction_pct(self) -> float | None:
        """Wall-time reduction relative to cc_alone."""
        return self._reduction_pct(self.alone.duration_s, self.onmc.duration_s)

    @property
    def efficiency_win(self) -> bool:
        """True when both solve and ONMC improves metrics without regressing one."""
        if not self.both_pass:
            return False
        reductions = [
            value
            for value in (
                self.token_reduction_pct,
                self.turn_reduction_pct,
                self.cost_reduction_pct,
                self.duration_reduction_pct,
            )
            if value is not None
        ]
        return (
            bool(reductions)
            and all(value >= 0 for value in reductions)
            and any(value > 0 for value in reductions)
        )


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
    def efficiency_wins(self) -> int:
        """Tasks both conditions solve where ONMC improves all measured efficiency metrics."""
        return sum(1 for c in self.comparisons if c.efficiency_win)

    @property
    def auto_wins(self) -> int:
        """Tasks where cc_onmc_auto passed but cc_alone failed (product-loop wins)."""
        return sum(1 for c in self.comparisons if c.auto_wins)

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
            "auto_wins": self.auto_wins,
            "alone_wins": self.alone_wins,
            "efficiency_wins": self.efficiency_wins,
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
                    "auto": c.auto.to_dict() if c.auto is not None else None,
                    "onmc_wins": c.onmc_wins,
                    "auto_wins": c.auto_wins,
                    "both_pass": c.both_pass,
                    "both_fail": c.both_fail,
                    "token_delta": c.token_delta,
                    "token_reduction_pct": c.token_reduction_pct,
                    "turn_reduction_pct": c.turn_reduction_pct,
                    "cost_reduction_pct": c.cost_reduction_pct,
                    "duration_reduction_pct": c.duration_reduction_pct,
                    "efficiency_win": c.efficiency_win,
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
            "| Task | cc_alone | cc_onmc | cc_auto | Outcome | Token reduction | "
            "Cost reduction | Time reduction |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for c in self.comparisons:
            outcome = (
                "ONMC wins"
                if c.onmc_wins
                else "tie-pass"
                if c.both_pass
                else "tie-fail"
                if c.both_fail
                else "REGRESSION"
            )
            auto_cell = (
                "pass"
                if c.auto is not None and c.auto.passed
                else "fail"
                if c.auto is not None
                else "n/r"  # not run
            )
            token_reduction = (
                f"{c.token_reduction_pct:.1f}%" if c.token_reduction_pct is not None else "n/a"
            )
            cost_reduction = (
                f"{c.cost_reduction_pct:.1f}%" if c.cost_reduction_pct is not None else "n/a"
            )
            time_reduction = (
                f"{c.duration_reduction_pct:.1f}%"
                if c.duration_reduction_pct is not None
                else "n/a"
            )
            lines.append(
                f"| {c.task.id}"
                f" | {'pass' if c.alone.passed else 'fail'}"
                f" | {'pass' if c.onmc.passed else 'fail'}"
                f" | {auto_cell}"
                f" | {outcome}"
                f" | {token_reduction}"
                f" | {cost_reduction}"
                f" | {time_reduction}"
                f" |"
            )
        auto_wins_str = (
            f"- **Auto wins (cc_alone failed, cc_onmc_auto passed):** {self.auto_wins}\n"
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
            auto_wins_str.rstrip(),
            f"- **Regressions (cc_alone passed, cc_onmc failed):** {self.alone_wins}",
            "- **Efficiency wins (both pass, all measured resources improve):** "
            f"{self.efficiency_wins}",
            f"- **Both pass (task too easy to differentiate):** {self.both_pass}",
            f"- **Both fail (task too hard for either):** {self.both_fail}",
            "",
            "> **Honesty note:** A positive ONMC delta only counts on tasks where the",
            "> cc_alone baseline can genuinely fail.  'tie-pass' tasks confirm ONMC",
            "> does not regress on easy tasks but contribute no signal about ONMC value.",
            "> The fixture baseline is pre-recorded, NOT auto-fail — results reflect",
            "> realistic agent behaviour on these tasks.",
            "> cc_auto (auto-capture) tests whether the REAL ingest→recall pipeline",
            "> can surface the rule without a hand-written hint.",
        ]
        return "\n".join(lines)
