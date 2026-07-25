"""Tests for the deterministic mutation / fault-injection harness."""

from __future__ import annotations

import pytest

from oh_no_my_claudecode.proof_graph import Outcome
from oh_no_my_claudecode.verifier import (
    FunctionUnderTest,
    Mutant,
    MutationOperator,
    generate_mutants,
    run_mutation_campaign,
)

_CLAMP = FunctionUnderTest(
    qualname="clamp",
    source=(
        "def clamp(x, lo, hi):\n"
        "    if x < lo:\n"
        "        return lo\n"
        "    if x > hi:\n"
        "        return hi\n"
        "    return x"
    ),
)


def test_generation_covers_each_operator() -> None:
    mutants = generate_mutants(_CLAMP)
    operators = {m.operator for m in mutants}
    assert MutationOperator.FLIP_COMPARISON in operators
    assert MutationOperator.DROP_STATEMENT in operators


def test_generation_is_deterministic() -> None:
    first = generate_mutants(_CLAMP)
    second = generate_mutants(_CLAMP)
    assert [m.mutant_id for m in first] == [m.mutant_id for m in second]
    assert first == second


def test_comparison_operators_flip_to_opposite() -> None:
    fn = FunctionUnderTest(qualname="cmp", source="    if a <= b and c >= d and e == f:")
    mutated_lines = {
        m.mutated for m in generate_mutants(fn) if m.operator is MutationOperator.FLIP_COMPARISON
    }
    assert "    if a > b and c >= d and e == f:" in mutated_lines
    assert "    if a <= b and c < d and e == f:" in mutated_lines
    assert "    if a <= b and c >= d and e != f:" in mutated_lines


def test_off_by_one_increments_integer_literals() -> None:
    fn = FunctionUnderTest(qualname="g", source="    return n + 1")
    off_by_one = [m for m in generate_mutants(fn) if m.operator is MutationOperator.OFF_BY_ONE]
    assert any(m.mutated == "    return n + 2" for m in off_by_one)


def test_survivor_detected_when_suite_never_fails() -> None:
    # A blind suite: it passes against every mutant -> everything survives.
    report = run_mutation_campaign(_CLAMP, lambda _mutant: Outcome.PASSED)
    assert report.weak_tests is True
    assert report.survivors == report.total
    assert report.mutation_score == 0.0
    assert report.killed == ()


def test_all_mutants_killed_is_a_strong_suite() -> None:
    report = run_mutation_campaign(_CLAMP, lambda _mutant: Outcome.FAILED)
    assert report.weak_tests is False
    assert report.survived == ()
    assert report.mutation_score == 1.0
    assert len(report.killed) == report.total


def test_selective_survivor_is_reported_with_full_mutant() -> None:
    # A suite that only notices comparison flips; off-by-one / drop survive.
    def runner(mutant: Mutant) -> Outcome:
        if mutant.operator is MutationOperator.FLIP_COMPARISON:
            return Outcome.FAILED
        return Outcome.PASSED

    report = run_mutation_campaign(_CLAMP, runner)
    assert report.weak_tests is True
    survived_ops = {m.operator for m in report.survived}
    assert MutationOperator.FLIP_COMPARISON not in survived_ops
    assert MutationOperator.DROP_STATEMENT in survived_ops
    # Survivors carry the full mutated source so a caller can reproduce them.
    for mutant in report.survived:
        assert mutant.mutated != mutant.original
        assert "pass" in mutant.mutated or mutant.mutated != _CLAMP.source


def test_errored_mutants_excluded_from_score() -> None:
    report = run_mutation_campaign(_CLAMP, lambda _mutant: Outcome.ERROR)
    assert report.killed == ()
    assert report.survived == ()
    assert len(report.errored) == report.total
    # Nothing was graded, so the score is a vacuous 1.0 (no evidence of weakness).
    assert report.mutation_score == 1.0
    assert report.weak_tests is False


def test_limit_selects_reproducible_subset() -> None:
    calls_a: list[str] = []
    calls_b: list[str] = []

    def make_runner(sink: list[str]) -> object:
        def runner(mutant: Mutant) -> Outcome:
            sink.append(mutant.mutant_id)
            return Outcome.FAILED

        return runner

    run_mutation_campaign(_CLAMP, make_runner(calls_a), limit=2, seed=7)  # type: ignore[arg-type]
    run_mutation_campaign(_CLAMP, make_runner(calls_b), limit=2, seed=7)  # type: ignore[arg-type]
    assert len(calls_a) == 2
    assert calls_a == calls_b  # same seed -> same subset, same order


def test_limit_zero_runs_nothing() -> None:
    report = run_mutation_campaign(_CLAMP, lambda _m: Outcome.FAILED, limit=0)
    assert report.total == 0
    assert report.mutation_score == 1.0


def test_empty_function_name_rejected() -> None:
    with pytest.raises(ValueError, match="qualname must not be empty"):
        FunctionUnderTest(qualname="  ", source="return 1")
