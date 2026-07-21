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

Fresh-worktree robustness
-------------------------
A clean swarm worktree usually has no dev dependencies installed (``ruff``,
``mypy``, ``pytest`` are absent), so a bare ``ruff check .`` crashes with
``No module named ruff`` and the staff-engineer verify gate FALSE-FAILS.  Two
mechanisms keep the gate honest:

* **Provisioning** (``provision=True``, the default for the swarm gate): each
  tool runs via ``uv run --with <tool> ...`` so a fresh worktree resolves the
  toolchain on demand.  The cli-reference step additionally pins
  ``typer==0.26.8`` (``--upgrade-package typer``) so its generated output matches
  CI's typer and never drifts.  If ``uv`` itself is missing, provisioning
  degrades gracefully to the plain command plus a clear message.
* **Availability detection** (when NOT provisioning): before running a tool we
  check whether it is importable.  A missing tool yields a clear, honest
  :class:`StepResult` ("ruff not installed — run ``pip install -e .[dev]`` or
  re-run with ``--provision``") instead of a confusing crash.

``--exact`` mode
----------------
:func:`run_preflight_exact` mirrors the CI quality gate with the **exact**
commands from ``.github/workflows/ci.yml``, including the full pytest coverage
flags (``--cov-fail-under=80``) and the typer==0.26.8 pin for cli-reference.  It
always provisions via ``uv run --with`` when ``uv`` is available so a fresh
worktree produces the same verdict as CI.

``--fix`` mode
--------------
:func:`run_preflight_fix` auto-heals common drift before pushing:

1. ``ruff check --fix .`` — auto-fix lint violations (never ``ruff format``).
2. Regenerate ``docs/cli-reference.md`` with pinned ``typer==0.26.8``.
3. Re-run the exact gate and report the updated result.

An :class:`ExactReport` bundles the fix-step outcomes with the final gate
result so callers can distinguish "fixed + gate passed" from "fix applied but
gate still fails".
"""

from __future__ import annotations

import importlib.util
import shutil
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

# Importable module name backing each step's tool.  Used by availability
# detection to give a clear "not installed" result instead of a raw crash.
# ``cliref`` shells out to ``python scripts/generate-cli-reference.py`` which
# only needs ``typer`` (already a runtime dependency), so it has no extra
# tool to detect — it is intentionally absent here.
_STEP_TOOL_MODULE: dict[str, str] = {
    "ruff": "ruff",
    "mypy": "mypy",
    "pytest": "pytest",
}

# PyPI package each tool ships in, for ``uv run --with <pkg>`` provisioning.
_STEP_TOOL_PACKAGE: dict[str, str] = {
    "ruff": "ruff",
    "mypy": "mypy",
    "pytest": "pytest",
}

# typer pin for the cli-reference step. CI runs this exact version; pinning keeps
# the generated reference byte-identical to CI's so ``--check`` never drifts.
_TYPER_PIN: str = "typer==0.26.8"


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


def _uv_available() -> bool:
    """Return ``True`` when the ``uv`` binary is on ``PATH``."""
    return shutil.which("uv") is not None


def _tool_importable(step_id: str) -> bool:
    """Return ``True`` when ``step_id``'s backing tool can be imported.

    Steps with no extra tool (e.g. ``cliref``) are always considered available.
    """
    module = _STEP_TOOL_MODULE.get(step_id)
    if module is None:
        return True
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # pragma: no cover - defensive
        return False


def _base_command_for(step_id: str) -> list[str]:
    """Return the *unprovisioned* argv for ``step_id``, mirroring ``ci.yml``."""
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


def _provisioned_command_for(step_id: str) -> list[str]:
    """Return the ``uv run --with ...`` form of ``step_id``'s command.

    The tool is supplied to a fresh, on-demand environment so a clean worktree
    (no dev deps installed) resolves it without a prior ``pip install``.  The
    ``cliref`` step additionally pins ``typer==0.26.8`` (and forces an upgrade to
    the newest matching release) so its generated output matches CI exactly.
    """
    base = _base_command_for(step_id)
    package = _STEP_TOOL_PACKAGE.get(step_id)
    if package is not None:
        # ruff / mypy / pytest — supply the tool to the ephemeral env.
        return ["uv", "run", "--with", package, *base]
    if step_id == "cliref":
        # Pin typer so generated CLI reference is byte-identical to CI.
        return [
            "uv",
            "run",
            "--with",
            _TYPER_PIN,
            "--upgrade-package",
            "typer",
            *base,
        ]
    return base  # pragma: no cover - all known steps handled above


def _command_for(step_id: str, *, provision: bool = False) -> list[str]:
    """Return the argv for ``step_id``.

    When ``provision`` is ``True`` the command is wrapped with ``uv run`` so a
    fresh worktree resolves the toolchain on demand; otherwise the plain CI
    command is returned.
    """
    if provision:
        return _provisioned_command_for(step_id)
    return _base_command_for(step_id)


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


def _missing_tool_result(step_id: str) -> StepResult:
    """Build a clear, honest result for a step whose tool isn't installed."""
    tool = _STEP_TOOL_MODULE.get(step_id, step_id)
    summary = (
        f"{tool} not installed — run `pip install -e .[dev]` "
        f"or re-run with --provision"
    )
    return StepResult(name=step_id, ok=False, summary=summary)


def run_preflight(
    repo_root: Path,
    *,
    steps: Sequence[str] | None = None,
    executor: Executor | None = None,
    provision: bool = False,
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
    provision:
        When ``True`` each tool runs via ``uv run --with <tool>`` so a fresh
        worktree (no dev deps installed) resolves the toolchain on demand, and
        the cli-reference step pins ``typer==0.26.8`` to match CI exactly.  If
        ``uv`` is not on ``PATH`` provisioning degrades to the plain command
        and the step is annotated.  When ``False`` (default, back-compatible
        with an already-provisioned env such as CI) a step whose tool is not
        importable returns a clear "not installed" result instead of crashing.

    Returns
    -------
    PreflightReport
        One :class:`StepResult` per executed step, plus an aggregate ``ok``.
    """
    # When the caller injects an executor it owns command execution entirely
    # (tests, simulations) — we trust it and skip real tool-availability
    # detection, which is only meaningful for the default subprocess path.
    injected = executor is not None
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

    # Resolve once: when asked to provision but ``uv`` is missing, fall back to
    # plain commands + availability detection so we never crash.
    use_provision = provision and _uv_available()
    provision_unavailable = provision and not use_provision

    results: list[StepResult] = []
    for step_id in selected:
        if not injected and not use_provision and not _tool_importable(step_id):
            # Tool absent in this (unprovisioned) env — report it honestly
            # rather than letting subprocess raise a confusing crash.
            result = _missing_tool_result(step_id)
            if provision_unavailable:
                result = StepResult(
                    name=step_id,
                    ok=False,
                    summary=(
                        f"{result.summary} (--provision requested but `uv` "
                        f"is not installed)"
                    ),
                )
            results.append(result)
            continue

        returncode, output = run(_command_for(step_id, provision=use_provision))
        results.append(
            StepResult(
                name=step_id,
                ok=returncode == 0,
                summary=_summarize(step_id, returncode, output),
            )
        )

    overall = all(step.ok for step in results)
    return PreflightReport(steps=results, ok=overall)


# ---------------------------------------------------------------------------
# Exact-CI mode: commands that match ci.yml verbatim
# ---------------------------------------------------------------------------

# Exact pytest command from the CI quality job (includes coverage gate).
_EXACT_PYTEST_ARGS: tuple[str, ...] = (
    "--cov=oh_no_my_claudecode",
    "--cov-report=term-missing",
    "--cov-report=xml",
    "--cov-fail-under=80",
    "tests/",
)

# Package name for pytest-cov, needed alongside pytest for the coverage flags.
_PYTEST_COV_PACKAGE: str = "pytest-cov"


def _exact_command_for(step_id: str) -> list[str]:
    """Return the *unprovisioned* exact-CI argv for ``step_id``.

    These commands match ``.github/workflows/ci.yml`` verbatim:

    * ``ruff check .``
    * ``mypy --strict src/oh_no_my_claudecode``
    * ``pytest --cov=... --cov-fail-under=80 tests/``  (full coverage gate)
    * ``python scripts/generate-cli-reference.py --check``
    """
    if step_id == "ruff":
        return ["ruff", "check", "."]
    if step_id == "mypy":
        return ["mypy", "--strict", "src/oh_no_my_claudecode"]
    if step_id == "cliref":
        return ["python", "scripts/generate-cli-reference.py", "--check"]
    if step_id == "pytest":
        return ["pytest", *_EXACT_PYTEST_ARGS]
    msg = f"unknown preflight step: {step_id!r}"
    raise ValueError(msg)


def _provisioned_exact_command_for(step_id: str) -> list[str]:
    """Return the ``uv run --with ...`` form of the exact-CI command.

    pytest is provisioned with both ``pytest`` *and* ``pytest-cov`` so the
    ``--cov-fail-under`` flag works in a fresh worktree.  The cli-reference
    step pins ``typer==0.26.8`` (and forces an upgrade) so the generated reference
    is byte-identical to CI's.
    """
    base = _exact_command_for(step_id)
    if step_id in ("ruff", "mypy"):
        pkg = _STEP_TOOL_PACKAGE[step_id]
        return ["uv", "run", "--with", pkg, *base]
    if step_id == "pytest":
        return [
            "uv",
            "run",
            "--with",
            _STEP_TOOL_PACKAGE["pytest"],
            "--with",
            _PYTEST_COV_PACKAGE,
            *base,
        ]
    if step_id == "cliref":
        return [
            "uv",
            "run",
            "--with",
            _TYPER_PIN,
            "--upgrade-package",
            "typer",
            *base,
        ]
    return base  # pragma: no cover


def run_preflight_exact(
    repo_root: Path,
    *,
    steps: Sequence[str] | None = None,
    executor: Executor | None = None,
) -> PreflightReport:
    """Run the exact CI quality gate and return a :class:`PreflightReport`.

    Like :func:`run_preflight` but uses commands that match
    ``.github/workflows/ci.yml`` verbatim, including:

    * ``pytest --cov=oh_no_my_claudecode --cov-fail-under=80`` (coverage gate)
    * cli-reference ``--check`` with pinned ``typer==0.26.8``

    When ``uv`` is available, each tool is provisioned on demand (``uv run
    --with <pkg>``) so a fresh worktree produces the same verdict as CI.  If
    ``uv`` is absent the exact plain commands run instead, relying on the
    caller's environment.

    Parameters
    ----------
    repo_root:
        Directory the commands run in.
    steps:
        Subset of :data:`STEP_IDS` to run.  ``None`` runs all in CI order.
    executor:
        Injectable ``(cmd) -> (returncode, output)`` callable.  Defaults to
        a subprocess runner.  Tests inject a fake for offline, deterministic
        runs.
    """
    run = executor if executor is not None else _default_executor(repo_root)

    if steps is None:
        selected = list(STEP_IDS)
    else:
        requested = set(steps)
        selected = [step_id for step_id in STEP_IDS if step_id in requested]

    if not selected:
        placeholder = StepResult(
            name="(none)",
            ok=False,
            summary="no matching preflight steps selected",
        )
        return PreflightReport(steps=[placeholder], ok=False)

    use_uv = _uv_available()

    results: list[StepResult] = []
    for step_id in selected:
        cmd = _provisioned_exact_command_for(step_id) if use_uv else _exact_command_for(step_id)
        returncode, output = run(cmd)
        results.append(
            StepResult(
                name=step_id,
                ok=returncode == 0,
                summary=_summarize(step_id, returncode, output),
            )
        )

    overall = all(step.ok for step in results)
    return PreflightReport(steps=results, ok=overall)


# ---------------------------------------------------------------------------
# Fix mode: auto-heal ruff violations + cli-reference drift
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FixStep:
    """Outcome of a single auto-fix action in :func:`run_preflight_fix`.

    Parameters
    ----------
    name:
        Stable identifier for the fix action (e.g. ``"ruff-fix"``).
    ok:
        ``True`` when the fix command exited zero.
    summary:
        One-line human summary.
    cmd:
        The exact command that was run (for test assertions).
    """

    name: str
    ok: bool
    summary: str
    cmd: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExactReport:
    """Result of a ``--fix`` + ``--exact`` preflight run.

    Bundles the outcomes of the auto-fix actions with the final exact gate
    result so callers can distinguish "fixed + gate passed" from "fix applied
    but gate still fails".

    Parameters
    ----------
    gate:
        The :class:`PreflightReport` from the exact gate re-run after fixes.
    fix_steps:
        One :class:`FixStep` per auto-fix action (ruff-fix, cliref-regen).
    """

    gate: PreflightReport
    fix_steps: list[FixStep] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """``True`` when every fix action AND the gate passed."""
        return all(f.ok for f in self.fix_steps) and self.gate.ok


# Canonical fix-action identifiers.
FIX_STEP_IDS: tuple[str, ...] = ("ruff-fix", "cliref-regen")


def _fix_command_for(fix_id: str, *, use_uv: bool = False) -> list[str]:
    """Return the argv for a fix action.

    ``ruff-fix`` runs ``ruff check --fix .`` (never ``ruff format``).
    ``cliref-regen`` regenerates ``docs/cli-reference.md`` without ``--check``,
    pinning ``typer==0.26.8`` so the output matches CI.
    """
    if fix_id == "ruff-fix":
        base = ["ruff", "check", "--fix", "."]
        if use_uv:
            return ["uv", "run", "--with", "ruff", *base]
        return base
    if fix_id == "cliref-regen":
        base = ["python", "scripts/generate-cli-reference.py"]
        if use_uv:
            return [
                "uv",
                "run",
                "--with",
                _TYPER_PIN,
                "--upgrade-package",
                "typer",
                *base,
            ]
        return base
    msg = f"unknown fix step: {fix_id!r}"  # pragma: no cover
    raise ValueError(msg)


def run_preflight_fix(
    repo_root: Path,
    *,
    executor: Executor | None = None,
) -> ExactReport:
    """Auto-fix ruff violations + cli-reference drift, then re-run the exact gate.

    Runs in three phases:

    1. ``ruff check --fix .`` — auto-fix lint violations (never ``ruff format``).
    2. Regenerate ``docs/cli-reference.md`` with pinned ``typer==0.26.8``.
    3. Re-run :func:`run_preflight_exact` and bundle the result.

    The injected ``executor`` (if any) receives ALL commands — fix actions and
    exact gate commands — so tests can assert every invocation without running
    real subprocesses.

    Parameters
    ----------
    repo_root:
        Directory the commands run in.
    executor:
        Injectable ``(cmd) -> (returncode, output)`` callable.  Defaults to a
        subprocess runner.  Tests inject a fake for offline, deterministic runs.
    """
    run = executor if executor is not None else _default_executor(repo_root)
    use_uv = _uv_available()

    fix_steps: list[FixStep] = []
    for fix_id in FIX_STEP_IDS:
        cmd = _fix_command_for(fix_id, use_uv=use_uv)
        returncode, output = run(cmd)
        if returncode == 0:
            summary = "applied" if fix_id == "ruff-fix" else "regenerated"
        else:
            tail = next(
                (line.strip() for line in reversed(output.splitlines()) if line.strip()),
                "",
            )
            if tail:
                summary = f"failed (exit {returncode}): {tail}"
            else:
                summary = f"failed (exit {returncode})"
        fix_steps.append(
            FixStep(name=fix_id, ok=returncode == 0, summary=summary, cmd=list(cmd))
        )

    gate = run_preflight_exact(repo_root, executor=executor)
    return ExactReport(gate=gate, fix_steps=fix_steps)
