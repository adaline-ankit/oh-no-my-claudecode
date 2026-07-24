"""Real adapters that make the pure verifier operable on actual runs.

The pure cores in this package deliberately take *injected* data:
:mod:`~oh_no_my_claudecode.verifier.reachability` wants changed regions plus
per-test executions, and :mod:`~oh_no_my_claudecode.verifier.mutation` wants a
:data:`~oh_no_my_claudecode.verifier.mutation.MutantTestRunner` seam. Neither
performs I/O. This module supplies the missing edges:

- :func:`coverage_to_executions` / :func:`build_changed_regions` turn a standard
  ``coverage.py`` JSON report (``coverage json``) into the reachability inputs,
  so :func:`~oh_no_my_claudecode.verifier.reachability.assess_reachability` and
  :func:`~oh_no_my_claudecode.verifier.reachability.is_false_green` can run
  against a real coverage file. Parsing is pure over an injected dict/path — the
  caller is responsible for actually *running* coverage.
- :class:`SubprocessMutantRunner` implements the ``MutantTestRunner`` seam by
  materialising a mutant into a temp copy of the repo and shelling a test
  command. The subprocess boundary is itself an injected :class:`CommandRunner`
  Protocol, so unit tests substitute a fake and never spawn a process.
- :func:`verified_or_false_green` composes the coverage adapter with
  reachability into a single boolean check shaped for the harness_run
  ``verifier_false_green_check`` seam (added in #387).

Everything here is deterministic: identical inputs (and, for the mutant runner,
an identical injected command runner) always yield identical results.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from oh_no_my_claudecode.proof_graph.models import Outcome
from oh_no_my_claudecode.verifier.mutation import Mutant
from oh_no_my_claudecode.verifier.reachability import (
    ChangedRegion,
    TestExecution,
    assess_reachability,
    is_false_green,
)

#: Synthetic ``test_id`` for the single aggregate execution derived from a
#: coverage report. ``coverage.py`` records which lines a *run* executed, not a
#: per-test pass/fail matrix, so the whole green suite's coverage collapses into
#: one passing :class:`TestExecution`.
DEFAULT_COVERAGE_TEST_ID = "coverage.py::suite"

#: A coverage report is a parsed ``coverage json`` document (or anything shaped
#: like one). Values are ``Any`` because the schema nests ints, lists and dicts.
CoverageReport = Mapping[str, Any]


# --------------------------------------------------------------------------- #
# Coverage adapter — coverage.py JSON -> reachability inputs
# --------------------------------------------------------------------------- #


def _as_report(source: CoverageReport | str | Path) -> CoverageReport:
    """Normalise an injected dict or a path-to-JSON into a report mapping."""
    if isinstance(source, (str, Path)):
        raw: Any = json.loads(Path(source).read_text(encoding="utf-8"))
    else:
        raw = source
    if not isinstance(raw, Mapping):
        raise TypeError("coverage report must be a JSON object with a 'files' key")
    return raw


def _files(report: CoverageReport) -> dict[str, Any]:
    """Return the ``files`` sub-mapping, tolerating a missing/odd shape."""
    files = report.get("files")
    if isinstance(files, Mapping):
        return {str(path): entry for path, entry in files.items()}
    return {}


def _int_set(values: Any) -> frozenset[int]:
    """Coerce a coverage line list into positive 1-based ints, dropping junk.

    Non-iterables, strings, booleans and non-positive/non-int members are
    ignored rather than raising — real reports occasionally carry nulls.
    """
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
        return frozenset()
    out: set[int] = set()
    for value in values:
        # ``bool`` is an ``int`` subclass; a stray ``True`` is not a line number.
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value > 0:
            out.add(value)
    return frozenset(out)


def _entry_lines(entry: Any, *keys: str) -> frozenset[int]:
    """Union the int line-sets under *keys* on one file entry (missing → empty)."""
    if not isinstance(entry, Mapping):
        return frozenset()
    result: frozenset[int] = frozenset()
    for key in keys:
        result = result | _int_set(entry.get(key))
    return result


def executed_lines(report: CoverageReport | str | Path, file: str) -> frozenset[int]:
    """Lines that a coverage run actually executed for *file* (empty if absent)."""
    return _entry_lines(_files(_as_report(report)).get(file), "executed_lines")


def executable_lines(report: CoverageReport | str | Path, file: str) -> frozenset[int]:
    """Lines coverage considers executable for *file*: executed + missing + excluded.

    This is what lets the changed-region builder drop blanks/comments — coverage
    only lists lines that carry executable intent.
    """
    return _entry_lines(
        _files(_as_report(report)).get(file),
        "executed_lines",
        "missing_lines",
        "excluded_lines",
    )


def coverage_to_executions(
    report: CoverageReport | str | Path,
    *,
    test_id: str = DEFAULT_COVERAGE_TEST_ID,
    outcome: Outcome = Outcome.PASSED,
) -> list[TestExecution]:
    """Map a coverage report to the per-test executions reachability expects.

    ``coverage.py`` records line execution for a *run*, not a per-test outcome
    matrix, so the honest mapping of a green suite's coverage is a single
    execution whose ``outcome`` is :attr:`Outcome.PASSED` and whose ``covered``
    is the per-file executed-line set. Returned as a list so it drops straight
    into :func:`~...reachability.assess_reachability`.
    """
    files = _files(_as_report(report))
    covered: dict[str, frozenset[int]] = {}
    for path, entry in files.items():
        lines = _entry_lines(entry, "executed_lines")
        if lines:
            covered[path] = lines
    return [TestExecution(test_id=test_id, outcome=outcome, covered=covered)]


def build_changed_regions(
    report: CoverageReport | str | Path,
    changed: Mapping[str, Iterable[int]],
) -> list[ChangedRegion]:
    """Build reachability regions from raw changed lines, filtered by coverage.

    For a file coverage measured, changed lines are intersected with its
    *executable* lines so blanks/comments never count. For a changed file
    coverage never saw, the raw lines are kept verbatim — an unmeasured change
    is precisely the false-green a reachability check should surface. Regions
    with no executable changed lines are omitted. Output is sorted by file for
    determinism.
    """
    files = _files(_as_report(report))
    regions: list[ChangedRegion] = []
    for path in sorted(changed):
        raw = _int_set(changed[path])
        if not raw:
            continue
        if path in files:
            allowed = _entry_lines(files[path], "executed_lines", "missing_lines", "excluded_lines")
            lines = raw & allowed if allowed else raw
        else:
            lines = raw
        if lines:
            regions.append(ChangedRegion(file=path, lines=lines))
    return regions


# --------------------------------------------------------------------------- #
# Mutant-runner adapter — MutantTestRunner over an injected CommandRunner
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Outcome of one shelled test command."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


def _as_text(value: str | bytes | None) -> str:
    """Decode captured process output to text (``text=True`` yields str already)."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class CommandRunner(Protocol):
    """The single subprocess seam the mutant runner depends on.

    Tests inject a fake so no real process is spawned; the real implementation
    is :class:`SubprocessCommandRunner`.
    """

    def __call__(self, argv: Sequence[str], *, cwd: str) -> CommandResult: ...


@dataclass(frozen=True, slots=True)
class SubprocessCommandRunner:
    """Real :class:`CommandRunner` that runs a command via :mod:`subprocess`."""

    timeout: float | None = None

    def __call__(self, argv: Sequence[str], *, cwd: str) -> CommandResult:
        try:
            # Trusted caller-supplied argv (the configured test command); no shell,
            # so S603 is a false positive here (ruff already ignores S603/S607).
            completed = subprocess.run(  # noqa: S603
                list(argv),
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                returncode=-1,
                stdout=_as_text(exc.stdout),
                stderr=_as_text(exc.stderr),
                timed_out=True,
            )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


@dataclass(frozen=True, slots=True)
class SubprocessMutantRunner:
    """A ``MutantTestRunner`` that grades a mutant against a real test command.

    For each mutant it copies the repo working tree into a throwaway temp
    directory, overwrites ``target_file`` with the mutant's source, and asks the
    injected :class:`CommandRunner` to run ``test_command`` there. A command
    that *passes* (exit 0) means the suite did not notice the fault → the mutant
    :attr:`~Outcome.PASSED` (survived); a *failing* command killed it
    (:attr:`~Outcome.FAILED`); a timeout is ungraded (:attr:`~Outcome.ERROR`).

    The real repo is never mutated in place; only the temp copy is touched.
    """

    repo_root: str
    target_file: str
    test_command: tuple[str, ...]
    command_runner: CommandRunner = field(default_factory=SubprocessCommandRunner)
    ignore_dirs: tuple[str, ...] = (
        ".git",
        "__pycache__",
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
    )

    def __post_init__(self) -> None:
        if not self.target_file.strip():
            raise ValueError("SubprocessMutantRunner.target_file must not be empty")
        if not self.test_command:
            raise ValueError("SubprocessMutantRunner.test_command must not be empty")

    def __call__(self, mutant: Mutant) -> Outcome:
        with tempfile.TemporaryDirectory(prefix="onmc-mutant-") as tmp:
            workspace = Path(tmp) / "repo"
            shutil.copytree(
                self.repo_root,
                workspace,
                ignore=shutil.ignore_patterns(*self.ignore_dirs),
            )
            target = workspace / self.target_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(mutant.mutated, encoding="utf-8")
            result = self.command_runner(self.test_command, cwd=str(workspace))
        if result.timed_out:
            return Outcome.ERROR
        return Outcome.PASSED if result.returncode == 0 else Outcome.FAILED


# --------------------------------------------------------------------------- #
# Glue — coverage adapter + reachability, as one harness-shaped check
# --------------------------------------------------------------------------- #


def verified_or_false_green(
    coverage_report: CoverageReport | str | Path,
    changed_regions: Mapping[str, Iterable[int]],
    *,
    claimed_verified: bool = True,
    test_id: str = DEFAULT_COVERAGE_TEST_ID,
) -> bool:
    """Compose coverage parsing + reachability into one false-green verdict.

    Returns ``True`` only on positive false-green evidence: the caller claims
    the change is verified (``claimed_verified``) yet the coverage report shows
    the changed executable lines were not reached by the passing suite. Shaped
    to drop into the harness_run ``verifier_false_green_check`` seam — it can
    fail a pass, never bless one (an unclaimed change is never a false green).
    """
    report = _as_report(coverage_report)
    regions = build_changed_regions(report, changed_regions)
    executions = coverage_to_executions(report, test_id=test_id)
    reachability = assess_reachability(regions, executions)
    return is_false_green(reachability, claimed_verified=claimed_verified)
