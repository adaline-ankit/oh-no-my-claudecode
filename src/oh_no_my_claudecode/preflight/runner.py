"""Deterministic core for ``onmc preflight``.

The runner executes the same commands CI runs, in the same order, against the
local working tree.  Commands are issued through an injectable ``executor``
callable so the logic is fully testable offline — the default executor shells
out via :mod:`subprocess`, but tests inject a fake that returns canned
``(returncode, output)`` pairs.

The CI gate (``.github/workflows/ci.yml``) runs, in order:

1. ``ruff check .``
2. ``mypy src``               (we scope to ``src/oh_no_my_claudecode``)
3. ``generate-cli-reference.py --check``
4. ``pytest``

Steps run in this fixed order; each step's pass/fail is independent so a single
``run_preflight`` call reports the status of every requested step rather than
stopping at the first failure.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# An executor takes a command (argv list) and returns ``(returncode, output)``.
# ``output`` is the combined stdout+stderr of the command, already decoded.
Executor = Callable[[Sequence[str]], "tuple[int, str]"]

# Canonical CI step order.  Each entry is ``(step_id, human_name)``.  The
# ``step_id`` is the stable key used by ``--only`` and JSON output; the name is
# the human-facing label shown in the renderer.
PREFLIGHT_STEPS: tuple[tuple[str, str], ...] = (
    ("ruff", "ruff check"),
    ("mypy", "mypy --strict"),
    ("cliref", "cli-reference --check"),
    ("pytest", "pytest"),
)

#: Valid ``step_id`` values, in CI order.
STEP_IDS: tuple[str, ...] = tuple(step_id for step_id, _ in PREFLIGHT_STEPS)

_STEP_NAMES: dict[str, str] = dict(PREFLIGHT_STEPS)


@dataclass(frozen=True)
class StepResult:
    """Outcome of a single preflight step.

    Parameters
    ----------
    name:
        Stable step identifier (one of :data:`STEP_IDS`).
    ok:
        ``True`` when the underlying command exited zero.
    summary:
        One-line human summary — the command's exit status plus, on failure,
        the last meaningful line of its output.
    """

    name: str
    ok: bool
    summary: str

    @property
    def label(self) -> str:
        """Human-facing label for this step (e.g. ``"ruff check"``)."""
        return _STEP_NAMES.get(self.name, self.name)


@dataclass(frozen=True)
class PreflightReport:
    """Aggregate result of a preflight run.

    ``ok`` is ``True`` only when every step that ran passed.  An empty run
    (no matching steps) is reported as ``ok=False`` with a single failing
    placeholder step so callers never mistake "nothing ran" for success.
    """

    steps: list[StepResult] = field(default_factory=list)
    ok: bool = True

    @property
    def failed(self) -> list[StepResult]:
        """The subset of steps that did not pass."""
        return [step for step in self.steps if not step.ok]


def _default_executor(repo_root: Path) -> Executor:
    """Build a subprocess-backed executor rooted at ``repo_root``.

    Commands run with ``cwd=repo_root`` and stdout+stderr merged so the
    summary can quote the tail of whatever the tool printed.
    """

    def _run(cmd: Sequence[str]) -> tuple[int, str]:
        completed = subprocess.run(  # noqa: S603 - argv is fixed, never shell
            list(cmd),
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        return completed.returncode, completed.stdout or ""

    return _run


def _command_for(step_id: str) -> list[str]:
    """Return the argv for ``step_id``, mirroring ``ci.yml`` exactly."""
    if step_id == "ruff":
        return ["ruff", "check", "."]
    if step_id == "mypy":
        return ["mypy", "--strict", "src/oh_no_my_claudecode"]
    if step_id == "cliref":
        return ["python", "scripts/generate-cli-reference.py", "--check"]
    if step_id == "pytest":
        return ["python", "-m", "pytest", "tests/"]
    msg = f"unknown preflight step: {step_id!r}"  # pragma: no cover - guarded by caller
    raise ValueError(msg)


def _summarize(step_id: str, returncode: int, output: str) -> str:
    """Build a one-line summary from a command's exit code and output."""
    if returncode == 0:
        return "passed"
    tail = ""
    for line in reversed(output.splitlines()):
        if line.strip():
            tail = line.strip()
            break
    if tail:
        return f"failed (exit {returncode}): {tail}"
    return f"failed (exit {returncode})"


def run_preflight(
    repo_root: Path,
    *,
    steps: Sequence[str] | None = None,
    executor: Executor | None = None,
) -> PreflightReport:
    """Run the local CI gate and return a :class:`PreflightReport`.

    Parameters
    ----------
    repo_root:
        Directory the commands run in (the repo root).
    steps:
        Subset of :data:`STEP_IDS` to run, e.g. ``["ruff", "pytest"]``.  When
        ``None`` (the default) all steps run in CI order.  Any requested step
        runs in canonical order regardless of the order given; unknown ids are
        ignored.
    executor:
        Injectable ``(cmd) -> (returncode, output)`` callable.  Defaults to a
        :mod:`subprocess` runner rooted at ``repo_root``.  Tests inject a fake
        for deterministic, offline runs.

    Returns
    -------
    PreflightReport
        One :class:`StepResult` per executed step, plus an aggregate ``ok``.
    """
    run = executor if executor is not None else _default_executor(repo_root)

    if steps is None:
        selected = list(STEP_IDS)
    else:
        requested = set(steps)
        selected = [step_id for step_id in STEP_IDS if step_id in requested]

    if not selected:
        # Nothing matched — never report this as a pass.
        placeholder = StepResult(
            name="(none)",
            ok=False,
            summary="no matching preflight steps selected",
        )
        return PreflightReport(steps=[placeholder], ok=False)

    results: list[StepResult] = []
    for step_id in selected:
        returncode, output = run(_command_for(step_id))
        results.append(
            StepResult(
                name=step_id,
                ok=returncode == 0,
                summary=_summarize(step_id, returncode, output),
            )
        )

    overall = all(step.ok for step in results)
    return PreflightReport(steps=results, ok=overall)
