"""Data models for the onmc eval harness.

All dataclasses are plain Python — no ORM, no DB schema.  Eval *cases* live
in ``.onmc/evals/<id>.json`` (like traces use ``.onmc/traces/<id>.jsonl``).

Metric definitions
------------------
- ``files_hit``: ``compile_recall(query)`` returns at least one entry whose
  ``memory_id`` or ``title`` matches one of ``expected_files``.  Proxy for
  "the brain surfaced the right memory given this query."
- ``deadend_hit``: ``compile_guard(query)`` returns at least one entry whose
  ``what_was_tried`` or ``title`` contains one of ``expected_deadend_substrings``.
  Proxy for "the don't-repeat property — a recorded dead-end was surfaced."
- ``passed``: both metrics are True (or only the applicable ones if the case
  defines only one type of expectation).
- ``injected_chars``: total char length of recall entries returned (proxy for
  context cost).
- ``recall_entries``: count of entries returned by compile_recall.

With-memory vs without-memory
------------------------------
- ``with_memory=True`` (default): run actual compile_recall / compile_guard
  against the live storage.  Scores reflect what the brain actually returns.
- ``with_memory=False`` (cold baseline): simulate no retrieval by treating
  all recall/guard results as empty.  Every case fails; injected_chars = 0.
  The delta (with minus without) is the brain's measurable contribution.

Score (0–100)
-------------
``EvalReport.score = pass_rate * 100`` rounded to two decimals.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalCase:
    """A single eval case: a question/query + expected memory behavior.

    Attributes
    ----------
    id:
        Stable identifier used as the filename stem (``<id>.json``).
    query:
        The natural-language query / task description passed to recall and
        guard.  Should be representative of real agent input.
    expected_files:
        List of strings that must appear in the ``memory_id`` or ``title`` of
        at least one :class:`~oh_no_my_claudecode.recall.compiler.RecallEntry`
        for the ``files_hit`` metric to be True.  Empty list → metric skipped
        (does not penalise the case).
    expected_deadend_substrings:
        List of substrings that must appear in the ``what_was_tried`` or
        ``title`` of at least one
        :class:`~oh_no_my_claudecode.guard.compiler.GuardEntry` for the
        ``deadend_hit`` metric to be True.  Empty list → metric skipped.
    note:
        Optional human-readable explanation of what this case is testing.
    """

    id: str
    query: str
    expected_files: list[str] = field(default_factory=list)
    expected_deadend_substrings: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class EvalCaseResult:
    """Result of running one :class:`EvalCase`.

    Attributes
    ----------
    case_id:
        Corresponds to :attr:`EvalCase.id`.
    files_hit:
        True when ``expected_files`` is non-empty and at least one entry in
        compile_recall output matches.  True (vacuous) when ``expected_files``
        is empty.
    deadend_hit:
        True when ``expected_deadend_substrings`` is non-empty and at least
        one guard entry matches.  True (vacuous) when
        ``expected_deadend_substrings`` is empty.
    recall_entries:
        Count of :class:`~oh_no_my_claudecode.recall.compiler.RecallEntry`
        items returned by compile_recall.
    injected_chars:
        Total character length of all recall entry text returned (a proxy for
        context tokens injected into the agent).
    passed:
        True when both ``files_hit`` and ``deadend_hit`` are True.
    """

    case_id: str
    files_hit: bool
    deadend_hit: bool
    recall_entries: int
    injected_chars: int
    passed: bool


@dataclass
class EvalReport:
    """Aggregate metrics for one evaluation run (one condition).

    Attributes
    ----------
    results:
        Per-case results.
    pass_rate:
        Fraction of cases that passed (0.0–1.0).
    with_memory:
        True when this report was produced against the live brain.
    mean_injected_chars:
        Mean injected_chars across all cases (context-cost proxy).
    score:
        ``pass_rate * 100`` rounded to two decimal places (0–100 scale for
        human legibility and ``--fail-under`` comparison).
    """

    results: list[EvalCaseResult]
    pass_rate: float
    with_memory: bool
    mean_injected_chars: float
    score: float

    @property
    def total_cases(self) -> int:
        """Total number of cases in this report."""
        return len(self.results)

    @property
    def passed_cases(self) -> int:
        """Number of cases that passed."""
        return sum(1 for r in self.results if r.passed)

    def to_markdown(self) -> str:
        """Render the report as a markdown table."""
        condition = "WITH memory" if self.with_memory else "WITHOUT memory"
        lines = [
            f"## Eval Report — {condition}",
            "",
            f"**Score:** {self.score:.2f} / 100  "
            f"({self.passed_cases}/{self.total_cases} passed, "
            f"pass_rate={self.pass_rate:.1%})",
            f"**Mean injected chars:** {self.mean_injected_chars:.0f}",
            "",
            "| Case ID | files_hit | deadend_hit | recall_entries | injected_chars | passed |",
            "|---|---|---|---|---|---|",
        ]
        for r in self.results:
            lines.append(
                f"| {r.case_id} | {'✓' if r.files_hit else '✗'} |"
                f" {'✓' if r.deadend_hit else '✗'} |"
                f" {r.recall_entries} |"
                f" {r.injected_chars} |"
                f" {'✓' if r.passed else '✗'} |"
            )
        return "\n".join(lines)


@dataclass
class EvalComparison:
    """Side-by-side comparison of with-memory vs without-memory eval reports.

    Attributes
    ----------
    with_memory:
        Report produced with the live brain.
    without_memory:
        Report produced with no retrieval (cold baseline — all misses).
    """

    with_memory: EvalReport
    without_memory: EvalReport

    @property
    def score_delta(self) -> float:
        """Score improvement from using memory (positive = brain helps)."""
        return self.with_memory.score - self.without_memory.score

    @property
    def pass_rate_delta(self) -> float:
        """Pass-rate improvement (positive = brain helps)."""
        return self.with_memory.pass_rate - self.without_memory.pass_rate

    @property
    def chars_delta(self) -> float:
        """Reduction in mean injected chars (positive = more concise with memory)."""
        return self.without_memory.mean_injected_chars - self.with_memory.mean_injected_chars

    def to_markdown(self) -> str:
        """Render a comparison table."""
        w = self.with_memory
        n = self.without_memory
        lines = [
            "## Eval Comparison — with vs without memory",
            "",
            "| Metric | Without memory | With memory | Delta |",
            "|---|---|---|---|",
            (
                f"| Score (0–100) | {n.score:.2f} | {w.score:.2f} |"
                f" +{self.score_delta:.2f} |"
            ),
            (
                f"| Pass rate | {n.pass_rate:.1%} | {w.pass_rate:.1%} |"
                f" +{self.pass_rate_delta:.1%} |"
            ),
            (
                f"| Mean injected chars | {n.mean_injected_chars:.0f} |"
                f" {w.mean_injected_chars:.0f} |"
                f" -{self.chars_delta:.0f} |"
            ),
            (
                f"| Cases passed | {n.passed_cases}/{n.total_cases} |"
                f" {w.passed_cases}/{w.total_cases} | — |"
            ),
            "",
            "> **Methodology:** deterministic, offline. No LLM calls.",
            "> without-memory baseline simulates empty retrieval (all misses).",
            "> Delta = with-memory minus without-memory (positive = brain helps).",
        ]
        return "\n".join(lines)
