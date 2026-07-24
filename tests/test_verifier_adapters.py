"""Tests for the real verifier adapters (coverage + mutant-runner + glue)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from oh_no_my_claudecode.proof_graph import Outcome
from oh_no_my_claudecode.verifier import (
    FunctionUnderTest,
    assess_reachability,
    generate_mutants,
    run_mutation_campaign,
)
from oh_no_my_claudecode.verifier.adapters import (
    CommandResult,
    SubprocessMutantRunner,
    build_changed_regions,
    coverage_to_executions,
    executable_lines,
    executed_lines,
    verified_or_false_green,
)
from oh_no_my_claudecode.verifier.mutation import Mutant

# A tiny coverage.py JSON report: cache.py has lines 10-12 executed and 13-14
# executable-but-missing; util.py is fully executed.
_COVERAGE_REPORT = {
    "meta": {"version": "7.6.0"},
    "files": {
        "src/cache.py": {
            "executed_lines": [10, 11, 12],
            "missing_lines": [13, 14],
            "summary": {"num_statements": 5},
        },
        "src/util.py": {
            "executed_lines": [1, 2, 3],
            "missing_lines": [],
        },
    },
}


# --------------------------------------------------------------------------- #
# Coverage adapter
# --------------------------------------------------------------------------- #


def test_coverage_to_executions_maps_executed_lines_to_one_passing_execution() -> None:
    executions = coverage_to_executions(_COVERAGE_REPORT)
    assert len(executions) == 1
    execution = executions[0]
    assert execution.outcome is Outcome.PASSED
    assert execution.covered["src/cache.py"] == frozenset({10, 11, 12})
    assert execution.covered["src/util.py"] == frozenset({1, 2, 3})


def test_executed_and_executable_line_helpers() -> None:
    assert executed_lines(_COVERAGE_REPORT, "src/cache.py") == frozenset({10, 11, 12})
    # Executable = executed + missing (+ excluded), so blanks/comments drop out.
    assert executable_lines(_COVERAGE_REPORT, "src/cache.py") == frozenset({10, 11, 12, 13, 14})


def test_changed_covered_line_is_reached_but_uncovered_is_false_green() -> None:
    # Line 11 was executed (reached); line 13 is executable-but-missing (unreached).
    regions = build_changed_regions(_COVERAGE_REPORT, {"src/cache.py": [11, 13]})
    assert len(regions) == 1
    assert regions[0].lines == frozenset({11, 13})
    report = assess_reachability(regions, coverage_to_executions(_COVERAGE_REPORT))
    # 13 is not covered → not fully reached → a claimed-verified change is false-green.
    assert report.reached is False
    assert report.unreached[0].lines == (13,)


def test_changed_region_filters_out_non_executable_lines() -> None:
    # Line 99 is neither executed nor missing in the report → not executable → dropped.
    regions = build_changed_regions(_COVERAGE_REPORT, {"src/cache.py": [10, 99]})
    assert regions[0].lines == frozenset({10})


def test_changed_file_absent_from_coverage_keeps_raw_lines() -> None:
    # An unmeasured changed file is itself a false-green signal: keep its lines
    # so reachability flags them as unreached.
    regions = build_changed_regions(_COVERAGE_REPORT, {"src/new.py": [1, 2]})
    assert regions[0].file == "src/new.py"
    assert regions[0].lines == frozenset({1, 2})


def test_coverage_report_loads_from_path(tmp_path: Path) -> None:
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(_COVERAGE_REPORT), encoding="utf-8")
    executions = coverage_to_executions(path)
    assert executions[0].covered["src/cache.py"] == frozenset({10, 11, 12})


def test_missing_files_key_handled_gracefully() -> None:
    assert coverage_to_executions({})[0].covered == {}
    assert build_changed_regions({}, {"src/x.py": [1]})[0].lines == frozenset({1})
    assert executed_lines({}, "src/x.py") == frozenset()


def test_junk_line_values_are_ignored() -> None:
    report = {"files": {"a.py": {"executed_lines": [1, "2", None, True, -3, 4]}}}
    assert executed_lines(report, "a.py") == frozenset({1, 4})


# --------------------------------------------------------------------------- #
# Mutant-runner adapter
# --------------------------------------------------------------------------- #


class _FakeCommandRunner:
    """Fake CommandRunner that decides pass/fail by reading the mutated file.

    Records every invocation's cwd so the test can assert a temp copy was used.
    ``killer`` is a predicate over the mutated source: True → the suite catches
    the fault (exit 1, killed); False → suite blind (exit 0, survived).
    """

    def __init__(self, target_rel: str, killer: Sequence[str]) -> None:
        self._target_rel = target_rel
        self._killed_markers = tuple(killer)
        self.cwds: list[str] = []

    def __call__(self, argv: Sequence[str], *, cwd: str) -> CommandResult:
        self.cwds.append(cwd)
        source = (Path(cwd) / self._target_rel).read_text(encoding="utf-8")
        caught = any(marker in source for marker in self._killed_markers)
        return CommandResult(returncode=1 if caught else 0)


def _write_repo(root: Path, rel: str, source: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")


def test_mutant_runner_reports_survivors_with_injected_fake(tmp_path: Path) -> None:
    rel = "src/mod.py"
    original = "def is_adult(age):\n    return age >= 18\n"
    _write_repo(tmp_path, rel, original)

    # A suite that only checks the boundary catches the ``>=`` -> ``<`` flip
    # (which reads ``age < 18``) but is blind to the off-by-one (``age >= 19``).
    # So the fake "kills" the flipped compare and lets the literal mutant survive.
    fake = _FakeCommandRunner(rel, killer=["age < 18"])
    runner = SubprocessMutantRunner(
        repo_root=str(tmp_path),
        target_file=rel,
        test_command=("pytest", "-q"),
        command_runner=fake,
    )

    fn = FunctionUnderTest(qualname="is_adult", source=original)
    report = run_mutation_campaign(fn, runner)

    assert report.total > 0
    assert report.survivors >= 1
    # Every survivor is a mutant the fake saw as still-passing.
    assert all(isinstance(m, Mutant) for m in report.survived)
    # The mutated source that survived is the off-by-one (19), never a flipped compare.
    assert any("19" in m.mutated for m in report.survived)
    # It shelled into a temp copy, not the real repo root.
    assert fake.cwds and all(str(tmp_path) not in cwd for cwd in fake.cwds)


def test_mutant_runner_kills_when_command_fails(tmp_path: Path) -> None:
    rel = "m.py"
    _write_repo(tmp_path, rel, "def f():\n    return 1\n")

    class _AlwaysFail:
        def __call__(self, argv: Sequence[str], *, cwd: str) -> CommandResult:
            return CommandResult(returncode=1)

    runner = SubprocessMutantRunner(
        repo_root=str(tmp_path),
        target_file=rel,
        test_command=("pytest",),
        command_runner=_AlwaysFail(),
    )
    mutant = Mutant(
        mutant_id="x-1-1",
        operator=generate_mutants(FunctionUnderTest(qualname="f", source="return 1"))[0].operator,
        qualname="f",
        lineno=1,
        original="    return 1",
        mutated="    return 2",
    )
    assert runner(mutant) is Outcome.FAILED


def test_mutant_runner_reports_error_on_timeout(tmp_path: Path) -> None:
    rel = "m.py"
    _write_repo(tmp_path, rel, "x = 1\n")

    class _Timeout:
        def __call__(self, argv: Sequence[str], *, cwd: str) -> CommandResult:
            return CommandResult(returncode=-1, timed_out=True)

    runner = SubprocessMutantRunner(
        repo_root=str(tmp_path),
        target_file=rel,
        test_command=("pytest",),
        command_runner=_Timeout(),
    )
    mutant = Mutant(
        mutant_id="y-1-1",
        operator=generate_mutants(FunctionUnderTest(qualname="g", source="x = 1"))[0].operator,
        qualname="g",
        lineno=1,
        original="x = 1",
        mutated="x = 2",
    )
    assert runner(mutant) is Outcome.ERROR


def test_mutant_runner_rejects_empty_config(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="target_file"):
        SubprocessMutantRunner(repo_root=str(tmp_path), target_file="  ", test_command=("pytest",))
    with pytest.raises(ValueError, match="test_command"):
        SubprocessMutantRunner(repo_root=str(tmp_path), target_file="m.py", test_command=())


# --------------------------------------------------------------------------- #
# Glue: verified_or_false_green
# --------------------------------------------------------------------------- #


def test_verified_or_false_green_true_on_unreached_change() -> None:
    # Line 13 is executable-but-missing → the passing suite never reached it.
    assert verified_or_false_green(_COVERAGE_REPORT, {"src/cache.py": [13]}) is True


def test_verified_or_false_green_false_on_fully_covered_change() -> None:
    # Lines 10-12 are all executed → the change is reached → not a false green.
    assert verified_or_false_green(_COVERAGE_REPORT, {"src/cache.py": [10, 11, 12]}) is False


def test_verified_or_false_green_never_flags_unclaimed_change() -> None:
    # Even an unreached change is not a false green if nobody claimed it verified.
    assert (
        verified_or_false_green(_COVERAGE_REPORT, {"src/cache.py": [13]}, claimed_verified=False)
        is False
    )
