"""Tests for changed-code reachability assessment."""

from __future__ import annotations

import pytest

from oh_no_my_claudecode.proof_graph import Outcome
from oh_no_my_claudecode.verifier import (
    ChangedRegion,
    TestExecution,
    assess_reachability,
    is_false_green,
)


def _exec(test_id: str, outcome: Outcome, **covered: frozenset[int]) -> TestExecution:
    return TestExecution(test_id=test_id, outcome=outcome, covered=dict(covered))


def test_changed_lines_reached_by_passing_test_is_verified() -> None:
    regions = [ChangedRegion(file="src/cache.py", lines=frozenset({10, 11, 12}))]
    executions = [
        _exec("t_cache", Outcome.PASSED, **{"src/cache.py": frozenset({10, 11, 12, 13})}),
    ]
    report = assess_reachability(regions, executions)
    assert report.reached is True
    assert report.false_green is False
    assert report.total_changed_lines == 3
    assert report.reached_lines == 3
    assert report.unreached == ()
    assert is_false_green(report, claimed_verified=True) is False


def test_changed_lines_unreached_is_false_green() -> None:
    regions = [ChangedRegion(file="src/cache.py", lines=frozenset({10, 11, 12}))]
    # A passing test that exercises entirely unrelated lines.
    executions = [_exec("t_other", Outcome.PASSED, **{"src/cache.py": frozenset({1, 2, 3})})]
    report = assess_reachability(regions, executions)
    assert report.reached is False
    assert report.false_green is True
    assert report.reached_lines == 0
    assert report.unreached[0].lines == (10, 11, 12)
    assert is_false_green(report, claimed_verified=True) is True
    # If nobody claimed it verified, there is no false-green to flag.
    assert is_false_green(report, claimed_verified=False) is False


def test_line_reached_only_by_failing_test_is_not_verified() -> None:
    regions = [ChangedRegion(file="src/api.py", lines=frozenset({20}))]
    executions = [_exec("t_fail", Outcome.FAILED, **{"src/api.py": frozenset({20})})]
    report = assess_reachability(regions, executions)
    assert report.reached is False
    assert report.unreached[0].reached_only_by_failing == (20,)
    assert any("ONLY by failing" in reason for reason in report.reasons)


def test_partial_reach_reports_only_the_gap() -> None:
    regions = [ChangedRegion(file="src/api.py", lines=frozenset({20, 21, 22}))]
    executions = [_exec("t_partial", Outcome.PASSED, **{"src/api.py": frozenset({20, 21})})]
    report = assess_reachability(regions, executions)
    assert report.reached is False
    assert report.reached_lines == 2
    assert report.unreached[0].lines == (22,)


def test_no_changed_executable_lines_is_vacuous_false_green() -> None:
    regions = [ChangedRegion(file="src/api.py", lines=frozenset())]
    executions = [_exec("t", Outcome.PASSED, **{"src/api.py": frozenset({1})})]
    report = assess_reachability(regions, executions)
    assert report.reached is False
    assert report.total_changed_lines == 0
    assert any("vacuous" in reason for reason in report.reasons)


def test_multi_file_change_all_reached() -> None:
    regions = [
        ChangedRegion(file="src/a.py", lines=frozenset({1, 2})),
        ChangedRegion(file="src/b.py", lines=frozenset({5})),
    ]
    executions = [
        _exec("t_a", Outcome.PASSED, **{"src/a.py": frozenset({1, 2})}),
        _exec("t_b", Outcome.PASSED, **{"src/b.py": frozenset({5})}),
    ]
    report = assess_reachability(regions, executions)
    assert report.reached is True
    assert report.total_changed_lines == 3


def test_reachability_is_order_independent_and_deterministic() -> None:
    regions_a = [
        ChangedRegion(file="src/b.py", lines=frozenset({5})),
        ChangedRegion(file="src/a.py", lines=frozenset({1})),
    ]
    regions_b = list(reversed(regions_a))
    executions = [_exec("t", Outcome.PASSED, **{"src/a.py": frozenset({1})})]
    report_a = assess_reachability(regions_a, executions)
    report_b = assess_reachability(regions_b, executions)
    assert report_a == report_b
    # Deterministic unreached ordering (sorted by file): src/b.py is the gap.
    assert report_a.unreached[0].file == "src/b.py"


def test_skipped_test_does_not_verify() -> None:
    regions = [ChangedRegion(file="src/x.py", lines=frozenset({1}))]
    executions = [_exec("t_skip", Outcome.SKIPPED, **{"src/x.py": frozenset({1})})]
    report = assess_reachability(regions, executions)
    assert report.reached is False


def test_duplicate_test_ids_rejected() -> None:
    regions = [ChangedRegion(file="src/x.py", lines=frozenset({1}))]
    executions = [
        _exec("dup", Outcome.PASSED, **{"src/x.py": frozenset({1})}),
        _exec("dup", Outcome.PASSED, **{"src/x.py": frozenset({1})}),
    ]
    with pytest.raises(ValueError, match="duplicate test_id"):
        assess_reachability(regions, executions)


def test_invalid_region_rejected() -> None:
    with pytest.raises(ValueError, match="positive 1-based"):
        ChangedRegion(file="src/x.py", lines=frozenset({0}))
    with pytest.raises(ValueError, match="must not be empty"):
        ChangedRegion(file="  ", lines=frozenset({1}))
