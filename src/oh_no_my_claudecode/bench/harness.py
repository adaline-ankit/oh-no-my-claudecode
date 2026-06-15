"""Deterministic benchmark harness for measuring onmc memory effectiveness.

Methodology (honest description)
----------------------------------
This is a *simulation*, not a live-LLM evaluation. A real LLM is never called.
Instead we model a deterministic agent policy that, for each task, picks
approaches from a fixed candidate pool.  The two conditions differ only in
whether the agent has access to onmc memory (brief/recall output):

  WITHOUT memory:
    - The agent does not know which approaches previously failed.
    - It may re-attempt known-dead-ends (modelled as: if a dead-end approach
      appears in the task's candidate pool, the agent tries it).
    - It must "discover" context that onmc memory already captures, requiring
      a large baseline context block.

  WITH memory:
    - The agent receives a compact onmc brief/recall surface
      (``failed_approach`` and ``invariant``/``decision`` memories).
    - It skips recorded dead-ends entirely.
    - Context tokens = tokens in the compiled brief rather than the large
      baseline.

Metrics per condition (summed across the task set):
  - repeated_failure_rate: fraction of tasks where the agent re-attempts a
    known-bad approach.
  - wasted_attempts: total dead-end attempts across all tasks.
  - context_tokens: token-proxy count (using utils/text.tokenize).
  - tasks_resolved: tasks reaching "solved" state within the attempt budget.

Future work: replace the deterministic policy with a live-LLM judge that
actually calls a model and measures real generation quality.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from oh_no_my_claudecode.utils.text import tokenize

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskSpec:
    """One benchmark task in the scenario."""

    task_id: str
    description: str
    # Known bad approaches for this task (should be in memory as failed_approach)
    dead_ends: Sequence[str]
    # The one correct approach that resolves the task
    correct_approach: str
    # Candidate approaches the without-memory agent considers (includes dead ends)
    candidate_pool_without: Sequence[str]
    # Attempt budget (max tries before giving up)
    attempt_budget: int = 3


@dataclass(frozen=True)
class MemoryRecord:
    """A simulated onmc memory entry used during WITH-memory condition."""

    kind: str  # "failed_approach", "invariant", "decision", "gotcha"
    summary: str
    # Which task_ids this memory is relevant to (empty = all)
    relevant_to: Sequence[str] = field(default_factory=list)


@dataclass
class BenchScenario:
    """A named benchmark scenario: tasks + the memory store they run against."""

    name: str
    description: str
    tasks: Sequence[TaskSpec]
    memories: Sequence[MemoryRecord]
    # Token count for the large "must discover" baseline (without memory)
    baseline_context_tokens: int = 800


@dataclass
class ConditionResult:
    """Per-condition metrics."""

    repeated_failure_rate: float  # fraction 0.0–1.0
    wasted_attempts: int
    context_tokens: int
    tasks_resolved: int


@dataclass
class BenchResult:
    """Full benchmark output for both conditions + computed deltas."""

    scenario_name: str
    without_memory: ConditionResult
    with_memory: ConditionResult

    @property
    def repeated_failure_rate_delta(self) -> float:
        """Reduction in repeated-failure rate (positive = improvement)."""
        return self.without_memory.repeated_failure_rate - self.with_memory.repeated_failure_rate

    @property
    def wasted_attempts_delta(self) -> int:
        """Reduction in wasted attempts (positive = improvement)."""
        return self.without_memory.wasted_attempts - self.with_memory.wasted_attempts

    @property
    def context_tokens_pct_reduction(self) -> float:
        """Percentage reduction in context tokens (positive = improvement)."""
        if self.without_memory.context_tokens == 0:
            return 0.0
        return (
            (self.without_memory.context_tokens - self.with_memory.context_tokens)
            / self.without_memory.context_tokens
        ) * 100.0

    @property
    def tasks_resolved_delta(self) -> int:
        """Additional tasks resolved with memory (positive = improvement)."""
        return self.with_memory.tasks_resolved - self.without_memory.tasks_resolved

    def to_markdown(self) -> str:
        w = self.without_memory
        m = self.with_memory
        lines = [
            f"## Benchmark: {self.scenario_name}",
            "",
            "| Metric | Without memory | With memory | Delta |",
            "|---|---|---|---|",
            (
                f"| Repeated-failure rate | {w.repeated_failure_rate:.0%} |"
                f" {m.repeated_failure_rate:.0%} |"
                f" -{self.repeated_failure_rate_delta:.0%} |"
            ),
            (
                f"| Wasted attempts | {w.wasted_attempts} |"
                f" {m.wasted_attempts} |"
                f" -{self.wasted_attempts_delta} |"
            ),
            (
                f"| Context tokens (proxy) | {w.context_tokens} |"
                f" {m.context_tokens} |"
                f" -{self.context_tokens_pct_reduction:.0f}% |"
            ),
            (
                f"| Tasks resolved | {w.tasks_resolved} |"
                f" {m.tasks_resolved} |"
                f" +{self.tasks_resolved_delta} |"
            ),
            "",
            "> **Methodology:** deterministic simulation — no live LLM calls.",
            "> The agent policy is seeded and reproducible.",
            "> Metric definitions: see `bench/harness.py` module docstring.",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Deterministic simulation engine
# ---------------------------------------------------------------------------


def _relevant_failed_approaches(memories: Sequence[MemoryRecord], task_id: str) -> set[str]:
    """Return the set of known-bad approach summaries for a given task."""
    bad: set[str] = set()
    for mem in memories:
        if mem.kind != "failed_approach":
            continue
        if not mem.relevant_to or task_id in mem.relevant_to:
            bad.add(mem.summary)
    return bad


def _brief_tokens(memories: Sequence[MemoryRecord], task_id: str) -> int:
    """Count token-proxy for the compiled brief surface shown to the agent."""
    relevant = [
        m for m in memories if not m.relevant_to or task_id in m.relevant_to
    ]
    combined = " ".join(m.summary for m in relevant)
    return len(tokenize(combined))


def _simulate_without(task: TaskSpec, baseline_tokens: int) -> tuple[bool, int, int]:
    """Simulate the WITHOUT-memory agent for one task.

    Returns (repeated_failure, wasted_attempts_this_task, resolved).
    The agent works through candidate_pool_without in order, spending one
    attempt per candidate until it hits correct_approach or exhausts the budget.
    """
    repeated_failure = False
    wasted = 0
    resolved = False
    attempts_used = 0

    for approach in task.candidate_pool_without:
        if attempts_used >= task.attempt_budget:
            break
        attempts_used += 1  # noqa: SIM113
        if approach in task.dead_ends:
            wasted += 1
            repeated_failure = True
        elif approach == task.correct_approach:
            resolved = True
            break

    return repeated_failure, wasted, resolved


def _simulate_with(
    task: TaskSpec,
    memories: Sequence[MemoryRecord],
) -> tuple[bool, int, int]:
    """Simulate the WITH-memory agent for one task.

    The agent skips any approach that matches a known failed_approach from
    memory.  It never has a repeated failure on a known dead-end.
    """
    known_bad = _relevant_failed_approaches(memories, task.task_id)
    wasted = 0
    resolved = False
    attempts_used = 0

    for approach in task.candidate_pool_without:
        if attempts_used >= task.attempt_budget:
            break
        # Skip approaches the memory flagged as failed
        if approach in known_bad:
            continue
        attempts_used += 1
        if approach in task.dead_ends:
            # A dead-end the memory didn't cover (shouldn't happen in well-seeded scenario)
            wasted += 1
        elif approach == task.correct_approach:
            resolved = True
            break

    # WITH memory: never a repeated failure on known-bad approaches
    return False, wasted, resolved


def run_benchmark(scenario: BenchScenario) -> BenchResult:
    """Run a deterministic benchmark and return both conditions' metrics.

    This function is pure and deterministic: given the same scenario it always
    produces the same BenchResult.  No randomness, no I/O, no LLM calls.
    """
    # --- WITHOUT memory ---
    without_repeated_failures = 0
    without_wasted = 0
    without_resolved = 0

    # Context: agent must carry the large baseline every task (no brief to lean on)
    without_context_tokens = scenario.baseline_context_tokens * len(scenario.tasks)

    for task in scenario.tasks:
        rf, wasted, resolved = _simulate_without(task, scenario.baseline_context_tokens)
        if rf:
            without_repeated_failures += 1
        without_wasted += wasted
        if resolved:
            without_resolved += 1

    total_tasks = len(scenario.tasks)
    without_rfr = without_repeated_failures / total_tasks if total_tasks else 0.0

    # --- WITH memory ---
    with_repeated_failures = 0
    with_wasted = 0
    with_resolved = 0

    # Context: compact brief per task (only relevant memories, token-counted)
    with_context_tokens = sum(
        _brief_tokens(scenario.memories, task.task_id) for task in scenario.tasks
    )

    for task in scenario.tasks:
        rf, wasted, resolved = _simulate_with(task, scenario.memories)
        if rf:
            with_repeated_failures += 1
        with_wasted += wasted
        if resolved:
            with_resolved += 1

    with_rfr = with_repeated_failures / total_tasks if total_tasks else 0.0

    return BenchResult(
        scenario_name=scenario.name,
        without_memory=ConditionResult(
            repeated_failure_rate=without_rfr,
            wasted_attempts=without_wasted,
            context_tokens=without_context_tokens,
            tasks_resolved=without_resolved,
        ),
        with_memory=ConditionResult(
            repeated_failure_rate=with_rfr,
            wasted_attempts=with_wasted,
            context_tokens=with_context_tokens,
            tasks_resolved=with_resolved,
        ),
    )


# ---------------------------------------------------------------------------
# Built-in synthetic scenario
# ---------------------------------------------------------------------------

#: The canonical built-in scenario. Numbers are seeded from domain knowledge
#: about onmc's feature set; they are stable across Python versions and
#: platforms (no randomness).
BUILTIN_SCENARIO = BenchScenario(
    name="onmc-builtin-v1",
    description=(
        "Synthetic scenario: 5 engineering tasks against a seeded memory store. "
        "Dead-ends are based on common mistakes in Python CLI / SQLite projects."
    ),
    tasks=[
        TaskSpec(
            task_id="task-cache",
            description="Fix flaky cache invalidation bug in worker refresh flow",
            dead_ends=[
                "add a sleep to wait for invalidation",
                "bypass cache layer entirely in worker",
            ],
            correct_approach="pass explicit key to invalidate_cache and assert deterministic",
            candidate_pool_without=[
                "add a sleep to wait for invalidation",
                "bypass cache layer entirely in worker",
                "pass explicit key to invalidate_cache and assert deterministic",
            ],
            attempt_budget=3,
        ),
        TaskSpec(
            task_id="task-sqlite",
            description="Add migration for new vector_cache table",
            dead_ends=[
                "drop and recreate database on startup",
                "use ALTER TABLE on SQLite TEXT column to add type constraint",
            ],
            correct_approach="add versioned migration in schema upgrade path",
            candidate_pool_without=[
                "drop and recreate database on startup",
                "use ALTER TABLE on SQLite TEXT column to add type constraint",
                "add versioned migration in schema upgrade path",
            ],
            attempt_budget=3,
        ),
        TaskSpec(
            task_id="task-cli",
            description="Add --json flag to onmc brief command",
            dead_ends=[
                "print raw dict repr instead of JSON",
            ],
            correct_approach="use json.dumps on model_dump output",
            candidate_pool_without=[
                "print raw dict repr instead of JSON",
                "use json.dumps on model_dump output",
            ],
            attempt_budget=2,
        ),
        TaskSpec(
            task_id="task-hook",
            description="Fix session-start hook returning empty context",
            dead_ends=[
                "write debug output to stdout before JSON payload",
                "return empty string when brief is None",
            ],
            correct_approach="guard with if brief_md before writing JSON to stdout",
            candidate_pool_without=[
                "write debug output to stdout before JSON payload",
                "return empty string when brief is None",
                "guard with if brief_md before writing JSON to stdout",
            ],
            attempt_budget=3,
        ),
        TaskSpec(
            task_id="task-ruff",
            description="Pass ruff check after adding new module",
            dead_ends=[
                "add noqa: ignore comment on every flagged line",
                "disable E501 globally in pyproject.toml",
            ],
            correct_approach="fix imports and line lengths to match project conventions",
            candidate_pool_without=[
                "add noqa: ignore comment on every flagged line",
                "disable E501 globally in pyproject.toml",
                "fix imports and line lengths to match project conventions",
            ],
            attempt_budget=3,
        ),
    ],
    memories=[
        MemoryRecord(
            kind="failed_approach",
            summary="add a sleep to wait for invalidation",
            relevant_to=["task-cache"],
        ),
        MemoryRecord(
            kind="failed_approach",
            summary="bypass cache layer entirely in worker",
            relevant_to=["task-cache"],
        ),
        MemoryRecord(
            kind="invariant",
            summary="cache invalidation must go through invalidate_cache with explicit key",
            relevant_to=["task-cache"],
        ),
        MemoryRecord(
            kind="failed_approach",
            summary="drop and recreate database on startup",
            relevant_to=["task-sqlite"],
        ),
        MemoryRecord(
            kind="failed_approach",
            summary="use ALTER TABLE on SQLite TEXT column to add type constraint",
            relevant_to=["task-sqlite"],
        ),
        MemoryRecord(
            kind="decision",
            summary="SQLite schema changes use versioned migration in schema upgrade path",
            relevant_to=["task-sqlite"],
        ),
        MemoryRecord(
            kind="failed_approach",
            summary="print raw dict repr instead of JSON",
            relevant_to=["task-cli"],
        ),
        MemoryRecord(
            kind="invariant",
            summary="CLI JSON output must use json.dumps on model_dump output",
            relevant_to=["task-cli"],
        ),
        MemoryRecord(
            kind="failed_approach",
            summary="write debug output to stdout before JSON payload",
            relevant_to=["task-hook"],
        ),
        MemoryRecord(
            kind="failed_approach",
            summary="return empty string when brief is None",
            relevant_to=["task-hook"],
        ),
        MemoryRecord(
            kind="gotcha",
            summary=(
                "hook stdout must be pure JSON; any other write"
                " before JSON payload breaks Claude Code"
            ),
            relevant_to=["task-hook"],
        ),
        MemoryRecord(
            kind="failed_approach",
            summary="add noqa: ignore comment on every flagged line",
            relevant_to=["task-ruff"],
        ),
        MemoryRecord(
            kind="failed_approach",
            summary="disable E501 globally in pyproject.toml",
            relevant_to=["task-ruff"],
        ),
        MemoryRecord(
            kind="invariant",
            summary=(
                "ruff violations must be fixed at source;"
                " per-line noqa and global disables are rejected in review"
            ),
            relevant_to=["task-ruff"],
        ),
    ],
    # 800 tokens is a realistic "must rediscover" baseline for a project without
    # onmc (e.g. reading README + CLAUDE.md + git log to reconstruct context)
    baseline_context_tokens=800,
)
