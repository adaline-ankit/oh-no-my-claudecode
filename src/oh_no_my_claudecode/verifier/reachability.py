"""Changed-code reachability — did a passing test actually exercise the change?

A green test suite proves nothing about a change whose lines no passing test
ever runs. That is a classic false-green signature: the agent edits ``foo``,
the pre-existing suite still passes, and "verified" is declared — but the suite
never touches ``foo`` at all.

This module answers one question, purely and deterministically over injected
data: **are the changed executable lines reached by at least one passing test?**
It performs no I/O and never runs a test — coverage and per-test outcomes are
handed in by the caller (the real CLI collects them from ``coverage.py`` /
pytest; tests inject fakes). It complements
:mod:`oh_no_my_claudecode.verifydiff.checker`'s line-coverage note by attributing
coverage to *passing* tests specifically and by treating "changed but unreached"
as a false-green rather than a soft note.

It deliberately does **not** re-implement proof-graph evaluation: it reuses
:class:`oh_no_my_claudecode.proof_graph.models.Outcome` for per-test outcomes so
a reachability finding can feed straight into the same evidence vocabulary the
proof graph already understands.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from oh_no_my_claudecode.proof_graph.models import Outcome


@dataclass(frozen=True, slots=True)
class ChangedRegion:
    """The executable lines a change touched in one file.

    ``lines`` are 1-based line numbers that carry executable intent (the caller
    is responsible for excluding blanks/comments, mirroring what a coverage tool
    reports). An empty ``lines`` means the change touched no executable code in
    this file — vacuous to "verify".
    """

    file: str
    lines: frozenset[int]

    def __post_init__(self) -> None:
        if not self.file.strip():
            raise ValueError("ChangedRegion.file must not be empty")
        if any(n <= 0 for n in self.lines):
            raise ValueError("ChangedRegion.lines must be positive 1-based line numbers")


@dataclass(frozen=True, slots=True)
class TestExecution:
    """One test's observed outcome plus the lines it exercised.

    ``covered`` maps a file path to the set of 1-based line numbers that this
    single test ran. Only tests whose ``outcome`` is :attr:`Outcome.PASSED`
    count toward verification — a line touched exclusively by a failing test is
    *not* verified.
    """

    # Opt this class out of pytest collection — its name starts with "Test"
    # but it is a data record, not a test case.
    __test__: ClassVar[bool] = False

    test_id: str
    outcome: Outcome
    covered: Mapping[str, frozenset[int]]

    def __post_init__(self) -> None:
        if not self.test_id.strip():
            raise ValueError("TestExecution.test_id must not be empty")


@dataclass(frozen=True, slots=True)
class UnreachedRegion:
    """Changed lines in one file that no passing test reached."""

    file: str
    lines: tuple[int, ...]
    reached_only_by_failing: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ReachabilityReport:
    """Verdict of a reachability assessment.

    ``reached`` is ``True`` only when there is at least one changed executable
    line and *every* changed line is exercised by at least one passing test.
    """

    reached: bool
    total_changed_lines: int
    reached_lines: int
    unreached: tuple[UnreachedRegion, ...]
    reasons: tuple[str, ...]

    @property
    def false_green(self) -> bool:
        """A ``verified`` claim over an unreached change is a false-green."""
        return not self.reached


def _covered_lines(
    executions: Sequence[TestExecution],
    file: str,
    *,
    outcome: Outcome,
) -> set[int]:
    """Union of lines in *file* exercised by tests with the given *outcome*."""
    covered: set[int] = set()
    for execution in executions:
        if execution.outcome is outcome:
            covered |= set(execution.covered.get(file, frozenset()))
    return covered


def assess_reachability(
    regions: Sequence[ChangedRegion],
    executions: Sequence[TestExecution],
) -> ReachabilityReport:
    """Assess whether changed executable lines are reached by passing tests.

    Pure and deterministic: no I/O, no clock, no test execution. Identical
    inputs always yield an identical :class:`ReachabilityReport`. Regions are
    processed in sorted ``(file, line)`` order so output is stable regardless of
    input ordering.
    """
    seen_ids: set[str] = set()
    for execution in executions:
        if execution.test_id in seen_ids:
            raise ValueError(f"duplicate test_id: {execution.test_id}")
        seen_ids.add(execution.test_id)

    total_changed = 0
    total_reached = 0
    unreached: list[UnreachedRegion] = []
    reasons: list[str] = []

    for region in sorted(regions, key=lambda r: r.file):
        if not region.lines:
            continue
        passing = _covered_lines(executions, region.file, outcome=Outcome.PASSED)
        failing = _covered_lines(executions, region.file, outcome=Outcome.FAILED)
        errored = _covered_lines(executions, region.file, outcome=Outcome.ERROR)
        non_passing = failing | errored

        region_lines = sorted(region.lines)
        total_changed += len(region_lines)
        missed = [n for n in region_lines if n not in passing]
        total_reached += len(region_lines) - len(missed)
        if missed:
            only_failing = tuple(n for n in missed if n in non_passing)
            unreached.append(
                UnreachedRegion(
                    file=region.file,
                    lines=tuple(missed),
                    reached_only_by_failing=only_failing,
                )
            )
            sample = ", ".join(f"{region.file}:{n}" for n in missed[:5])
            suffix = "" if len(missed) <= 5 else f" (+{len(missed) - 5} more)"
            reasons.append(f"changed lines not reached by any passing test: {sample}{suffix}")
            if only_failing:
                fail_sample = ", ".join(f"{region.file}:{n}" for n in only_failing[:5])
                reasons.append(
                    "changed lines reached ONLY by failing/errored tests "
                    f"(not verified): {fail_sample}"
                )

    if total_changed == 0 and regions and all(
        _non_executable_documentation_file(region.file) for region in regions
    ):
        reasons.insert(0, "change touches no executable lines in documentation-only files")
        reached = True
    elif total_changed == 0:
        reasons.insert(
            0,
            "no changed executable lines to verify — a 'verified' claim here is vacuous",
        )
        reached = False
    else:
        reached = not unreached

    return ReachabilityReport(
        reached=reached,
        total_changed_lines=total_changed,
        reached_lines=total_reached,
        unreached=tuple(unreached),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _non_executable_documentation_file(path: str) -> bool:
    lowered = path.lower()
    return lowered.startswith(("docs/", "doc/")) or lowered.endswith(
        (
            ".md",
            ".markdown",
            ".rst",
            ".txt",
        )
    )


def is_false_green(report: ReachabilityReport, *, claimed_verified: bool) -> bool:
    """Return whether a *claimed_verified* change is contradicted by reachability.

    ``True`` exactly when the caller asserts the change is verified but the
    changed code is not reached by any passing test.
    """
    return claimed_verified and not report.reached
