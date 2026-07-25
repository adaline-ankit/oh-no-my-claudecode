#!/usr/bin/env python
"""Run the claim protocol's THREE-condition comparison plus single-factor ablations.

``scripts/run_external_eval.py`` answers "does ONMC beat a bare agent?" with two
conditions. The claim protocol also demands (a) a third condition — a *candidate*
ONMC defined as current ONMC plus one declared config/env delta — and (b) an
**ablation**: a family of arms that each differ from ``onmc-current`` by exactly
one factor, so a measured win can be attributed to a mechanism instead of to the
harness as an undifferentiated blob.

This runner adds the arm dimension and nothing else. Every cell-level invariant
that made the external benchmark trustworthy is *imported* from
``run_external_eval`` rather than re-derived, because each of those was a real bug
that produced a wrong benchmark:

* per-cell fresh clone at the pinned SHA (:func:`prepare_clone`);
* a per-cell venv INSIDE the checkout (:func:`prepare_venv`), so ONMC's reference
  monitor does not correctly deny a verifier that lives outside repo scope;
* the verifier argv left LITERALLY ``python -m pytest …`` (:func:`verifier_argv`)
  and the interpreter bound through PATH (:func:`cell_env`) — rewriting argv[0]
  makes the monitor DENY the verifier and silently zeroes any ONMC arm;
* a NON-editable pinned ONMC snapshot (:func:`prepare_onmc_venv`), never
  ``uv run --project`` (which re-points the verifier's ``python`` at ONMC's
  interpreter);
* both validity gates — :func:`guard_pristine_verifier` (upstream suite must PASS
  before mutation) and :func:`guard_regression_active` (the mutation must BREAK
  it);
* infra-failure accounting that EXCLUDES infra cells from pass rates instead of
  scoring them 0, and the shared failure :func:`_taxonomy` so the two reports
  bucket failures identically.

Statistics come from :mod:`oh_no_my_claudecode.experiment.stats`; none are
hand-rolled. Cost is ``None`` when the provider did not report one — never ``0``.

Arms are derived from ONMC's OWN knobs, looked up at runtime, never invented:
``--budget-mode`` / ``--context-budget`` (which is where ``retrieval_mode`` and
``top_k`` actually live — see :mod:`~.harness_run.budget_modes`),
``ONMC_LEARNING`` (the learning kill switch in
:mod:`~.learning.activation`), and ``--max-iterations``.

An arm that cannot be implemented honestly is reported as ``SKIPPED`` with a
machine-readable reason. See :data:`ADVISORY_MONITOR_SKIP_REASON`: advisory
enforcement is not reachable from the CLI, and weakening the monitor policy to
manufacture the arm would corrupt the very thing being measured.

Usage::

    python scripts/run_ablations.py \
        --manifest datasets/experiment/portfolio_external_v3.json \
        --workdir /tmp/abl --out /tmp/abl/report.json --dry-run

    # bare vs current vs candidate (candidate = current + one declared delta)
    python scripts/run_ablations.py ... --candidate-budget-mode deep
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shlex
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
for _entry in (str(REPO_ROOT / "src"), str(SCRIPTS_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

# Imported, not reimplemented. Every name below encodes a hard-won cell-level
# invariant of the external benchmark; a second copy would be a second chance to
# regress one of them, and a taxonomy that drifted between the two reports would
# make the ablation non-comparable with the headline benchmark.
from run_external_eval import (  # noqa: E402
    REPO_TEST_DEPS,
    EvalConfig,
    TrialRecord,
    _extract_cost,
    _observed_change,
    _pass_hat_k,
    _run,
    _taxonomy,
    cell_env,
    code_sha,
    guard_pristine_verifier,
    guard_regression_active,
    inject_regression,
    prepare_clone,
    prepare_onmc_venv,
    prepare_venv,
    verifier_argv,
    verify,
)

from oh_no_my_claudecode.experiment.contracts import (  # noqa: E402
    Condition,
    MetricLabel,
)
from oh_no_my_claudecode.experiment.portfolio import (  # noqa: E402
    PortfolioManifest,
    TaskSpec,
)
from oh_no_my_claudecode.experiment.stats import (  # noqa: E402
    bootstrap_ci,
    derive_seed,
    mean,
    median,
    paired_deltas,
    variance,
)
from oh_no_my_claudecode.harness_run.budget_modes import (  # noqa: E402
    BudgetMode,
    resolve_budget_profile,
)
from oh_no_my_claudecode.learning.activation import LEARNING_ENABLED_ENV  # noqa: E402

#: Machine-readable reason the advisory-monitor ablation cannot be measured.
#:
#: ``harness_run/controller.py::default_dependencies`` builds the monitor as
#: ``ReferenceMonitor(_monitor_policy(repo_root), enforced=True)``. That literal
#: is the ONLY production construction site; ``enforced=False`` is reachable
#: exclusively by injecting ``ControllerDependencies`` in-process (which is what
#: the unit tests do). ``onmc run --help`` exposes no enforcement flag and no
#: ``ONMC_*`` variable toggles it.
#:
#: The two ways to manufacture this arm are both forbidden: patching ONMC's
#: source would unpin ``code_sha`` mid-run, and relaxing ``_monitor_policy`` would
#: weaken the very policy under measurement. A SKIPPED arm is a valid result.
ADVISORY_MONITOR_SKIP_REASON = "advisory-monitor-not-reachable-from-cli"

#: Tokens whose appearance in ``onmc run --help`` would mean the skip reason above
#: has gone stale and the arm should be implemented for real.
_ADVISORY_FLAG_TOKENS: tuple[str, ...] = (
    "--advisory",
    "--enforce",
    "--no-enforce",
    "--monitor-mode",
    "--enforcement",
)

#: Substrings in ONMC's output that mean ONMC NEVER EXECUTED. Copied (not
#: imported) from ``run_external_eval.run_onmc``, where they are a function-local
#: tuple with no importable name. Kept byte-identical on purpose: provider-side
#: stops and denied capabilities are INFRA failures, never agent losses. Banking
#: a provider outage as evidence about the agent is the measurement-integrity bug
#: that already invalidated one run of the headline benchmark.
ONMC_INFRA_MARKERS: tuple[str, ...] = (
    "capability was denied",
    "verifier=deny",
    "verifier-unavailable",
    "agent-unavailable",
    "agent-credentials",
)

#: The reference arm every paired delta is computed against.
REFERENCE_ARM = "onmc-current"


class ArmKind(StrEnum):
    """How an arm is executed. Determines which runner drives the cell."""

    BARE = "bare"
    ONMC = "onmc"


class CellStatus(StrEnum):
    """Why a cell does or does not contribute to a pass rate.

    Only :attr:`MEASURED` cells enter any denominator. The other four are counted
    and reported separately so a thin arm is visible as thin rather than as bad —
    the distinction the external benchmark already makes for ``infra``, extended
    to budget and skip accounting.
    """

    MEASURED = "measured"
    INFRA = "infra"
    BUDGET_STOPPED = "budget-stopped"
    SKIPPED = "skipped"
    DRY_RUN = "dry-run"


@dataclass(frozen=True, slots=True)
class Arm:
    """One comparison arm: a name, a lineage condition, and ONE varied factor.

    ``factor`` names the single knob that differs from :data:`REFERENCE_ARM`.
    ``factor_confounds`` is the honest caveat list: where ONMC's CLI bundles
    several parameters behind one flag, the bundled parameters are recorded so the
    arm is never read as a cleaner ablation than it is.
    """

    name: str
    condition: Condition
    kind: ArmKind
    factor: str
    budget_mode: BudgetMode = BudgetMode.STANDARD
    context_budget: int | None = None
    max_iterations: int | None = None
    env_delta: Mapping[str, str] = field(default_factory=dict)
    skipped_reason: str | None = None
    skip_detail: str = ""
    factor_confounds: tuple[str, ...] = ()

    @property
    def is_active(self) -> bool:
        return self.skipped_reason is None

    def resolved_config(self, cfg: EvalConfig) -> dict[str, object]:
        """The arm's effective knobs, resolved through ONMC's own profile table.

        Reading ``retrieval_mode`` / ``top_k`` out of :func:`resolve_budget_profile`
        (rather than restating them here) is what keeps the "exactly one factor"
        claim auditable: if ONMC retunes a profile, this report changes with it.
        """
        if self.kind is ArmKind.BARE:
            return {"agent_cli": "claude", "onmc": False}
        profile = resolve_budget_profile(self.budget_mode)
        return {
            "onmc": True,
            "budget_mode": self.budget_mode.value,
            "retrieval_mode": profile.retrieval_mode,
            "top_k": profile.top_k,
            "context_budget": self.context_budget or profile.token_budget,
            "max_iterations": self.max_iterations or cfg.max_iterations,
            "env_delta": dict(self.env_delta),
        }


@dataclass(frozen=True, slots=True)
class Cell:
    """One (task, arm, trial) measurement unit."""

    task: TaskSpec
    arm: Arm
    trial: int

    @property
    def slug(self) -> str:
        return f"{self.task.task_id}.{self.arm.name}.t{self.trial}"


@dataclass
class ArmRecord(TrialRecord):
    """A :class:`TrialRecord` plus the arm dimension and an explicit status.

    ``condition`` keeps its external-benchmark meaning (the lineage condition), so
    records from both runners remain comparable; ``arm`` is the new dimension.
    """

    arm: str = ""
    factor: str = ""
    status: str = CellStatus.MEASURED.value
    enforcement_mode: str | None = None
    iterations: int | None = None

    def to_dict(self) -> dict[str, object]:
        data = super().to_dict()
        data.update(
            {
                "arm": self.arm,
                "factor": self.factor,
                "status": self.status,
                "enforcement_mode": self.enforcement_mode,
                "iterations": self.iterations,
            }
        )
        return data


# --------------------------------------------------------------------------- #
# Arm construction
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    """The operator's declared delta for the ``onmc-candidate`` condition."""

    budget_mode: str | None = None
    context_budget: int | None = None
    max_iterations: int | None = None
    env: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_declared(self) -> bool:
        return bool(
            self.budget_mode is not None
            or self.context_budget is not None
            or self.max_iterations is not None
            or self.env
        )


def build_candidate_arm(spec: CandidateSpec, cfg: EvalConfig) -> Arm:
    """Condition 3: current ONMC plus ONE declared config/env delta.

    An undeclared candidate is SKIPPED rather than aliased onto ``onmc-current``:
    a third arm that is byte-identical to the second is not a candidate, and
    reporting it as one would fabricate a comparison.
    """
    reference = Arm(
        name=REFERENCE_ARM,
        condition=Condition.ONMC_CURRENT,
        kind=ArmKind.ONMC,
        factor="none (reference arm)",
    )
    if not spec.is_declared:
        return Arm(
            name="onmc-candidate",
            condition=Condition.ONMC_CANDIDATE,
            kind=ArmKind.ONMC,
            factor="operator-declared",
            skipped_reason="candidate-delta-undeclared",
            skip_detail=(
                "No --candidate-budget-mode / --candidate-context-budget / "
                "--candidate-max-iterations / --candidate-env was supplied, so the "
                "candidate arm would be identical to onmc-current. Declaring it as a "
                "third condition anyway would fabricate a comparison."
            ),
        )
    candidate = Arm(
        name="onmc-candidate",
        condition=Condition.ONMC_CANDIDATE,
        kind=ArmKind.ONMC,
        factor="operator-declared",
        budget_mode=BudgetMode(spec.budget_mode) if spec.budget_mode else BudgetMode.STANDARD,
        context_budget=spec.context_budget,
        max_iterations=spec.max_iterations,
        env_delta=dict(spec.env),
    )
    if candidate.resolved_config(cfg) == reference.resolved_config(cfg):
        return Arm(
            name="onmc-candidate",
            condition=Condition.ONMC_CANDIDATE,
            kind=ArmKind.ONMC,
            factor="operator-declared",
            skipped_reason="candidate-delta-empty",
            skip_detail=(
                "The declared candidate flags resolve to exactly onmc-current's "
                "configuration, so there is no delta to measure."
            ),
        )
    return candidate


def build_arms(cfg: EvalConfig, candidate: CandidateSpec) -> list[Arm]:
    """The full arm set: three conditions plus the single-factor ablations.

    Each ablation arm changes exactly one CLI/env knob relative to
    :data:`REFERENCE_ARM`. Where a knob is a bundle, the bundled parameters land
    in ``factor_confounds`` instead of being quietly ignored.
    """
    standard = resolve_budget_profile(BudgetMode.STANDARD)
    deep = resolve_budget_profile(BudgetMode.DEEP)
    return [
        # --- Condition 1: the real control. Same prompt/permissions/verifier. ---
        Arm(
            name="bare-agent",
            condition=Condition.BARE_AGENT,
            kind=ArmKind.BARE,
            factor="whole-harness (no ONMC retrieval, policy, or loop)",
        ),
        # --- Condition 2: the reference arm. ---
        Arm(
            name=REFERENCE_ARM,
            condition=Condition.ONMC_CURRENT,
            kind=ArmKind.ONMC,
            factor="none (reference arm)",
        ),
        # --- Condition 3: operator-declared candidate. ---
        build_candidate_arm(candidate, cfg),
        # --- Ablation: retrieval mode. ---
        # ONMC exposes retrieval_mode only through the budget profile
        # (budget_modes.BudgetProfile.retrieval_mode): standard -> "bm25",
        # deep -> "hybrid". There is no --retrieval-mode flag, so --budget-mode is
        # the knob. --context-budget pins deep's token ceiling back to standard's
        # value, which removes the token-budget confound; top_k still moves with
        # the profile and is recorded rather than hidden.
        Arm(
            name="abl-retrieval-hybrid",
            condition=Condition.ONMC_CANDIDATE,
            kind=ArmKind.ONMC,
            factor="retrieval-mode (bm25 -> hybrid via --budget-mode deep)",
            budget_mode=BudgetMode.DEEP,
            context_budget=standard.token_budget,
            factor_confounds=(
                f"top_k moves with the profile: {standard.top_k} -> {deep.top_k} "
                "(ONMC exposes no independent top_k flag)",
                "planner gates min_context_roi/min_freshness also differ between "
                "the standard and deep profiles",
            ),
        ),
        # --- Ablation: memory / learning kill switch. ---
        Arm(
            name="abl-memory-off",
            condition=Condition.ONMC_CANDIDATE,
            kind=ArmKind.ONMC,
            factor=f"learned-memory ({LEARNING_ENABLED_ENV}=0 kill switch)",
            env_delta={LEARNING_ENABLED_ENV: "0"},
            factor_confounds=(
                f"{LEARNING_ENABLED_ENV}=0 makes every learned artifact inert "
                "(no ingest, no promotion, no activation); repository retrieval "
                "is unaffected, so this ablates learned memory, not context.",
            ),
        ),
        # --- Ablation: advisory vs enforced monitor — NOT MEASURABLE. ---
        Arm(
            name="abl-monitor-advisory",
            condition=Condition.ONMC_CANDIDATE,
            kind=ArmKind.ONMC,
            factor="monitor enforcement (enforced -> advisory)",
            skipped_reason=ADVISORY_MONITOR_SKIP_REASON,
            skip_detail=(
                "harness_run/controller.py::default_dependencies hardcodes "
                "ReferenceMonitor(_monitor_policy(repo_root), enforced=True). "
                "enforced=False is reachable only by injecting "
                "ControllerDependencies in-process; `onmc run --help` exposes no "
                "enforcement flag and no ONMC_* variable toggles it. Patching the "
                "source would unpin code_sha mid-run and relaxing _monitor_policy "
                "would weaken the policy under measurement, so this arm is skipped "
                "rather than faked."
            ),
        ),
        # --- Ablation: adaptive loop vs one shot. ---
        Arm(
            name="abl-single-iteration",
            condition=Condition.ONMC_CANDIDATE,
            kind=ArmKind.ONMC,
            factor="adaptive loop (--max-iterations 1 instead of N)",
            max_iterations=1,
        ),
    ]


# --------------------------------------------------------------------------- #
# Cell execution
# --------------------------------------------------------------------------- #


def _last_json_object(out: str) -> dict[str, object] | None:
    """The last line of *out* that parses as a JSON object, else ``None``.

    Best-effort and never fabricating: a run that emitted no parseable JSON yields
    ``None``, so downstream fields stay ``None`` instead of gaining a default.
    """
    for line in reversed(out.splitlines()):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


@dataclass(frozen=True, slots=True)
class ArmOutcome:
    """What running one arm on one cell produced, before adjudication."""

    infra_error: str | None
    cost_usd: float | None
    enforcement_mode: str | None = None
    iterations: int | None = None


def run_bare_arm(task: TaskSpec, repo: Path, cfg: EvalConfig, python: Path) -> ArmOutcome:
    """The control: the agent CLI directly, same prompt/permissions/verifier.

    Mirrors ``run_external_eval.run_bare_agent`` argv-for-argv so the control is
    the same control in both reports.
    """
    argv = [
        "claude",
        "-p",
        f"{task.prompt}\n\nThe adjudicating test command is: "
        f"{shlex.join(verifier_argv(task, python))}",
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
    ]
    code, out = _run(argv, repo, cfg.timeout_s, env=cell_env(repo))
    cost = _extract_cost(out)
    if code == 127:
        return ArmOutcome(f"agent CLI unavailable: {out[:200]}", cost)
    if "[timeout]" in out:
        return ArmOutcome("agent timeout", cost)
    return ArmOutcome(None, cost)


def onmc_argv(arm: Arm, task: TaskSpec, cfg: EvalConfig, python: Path) -> list[str]:
    """The ``onmc run`` argv for *arm*.

    The verifier is passed through :func:`verifier_argv`, which deliberately keeps
    the command literally ``python -m pytest …``: ONMC's reference monitor
    allowlists verifier commands by ARGV PREFIX, so rewriting argv[0] to an
    interpreter path makes the monitor DENY the verifier and abort the run before
    it executes. The interpreter is bound through PATH by :func:`cell_env`.

    Every ONMC arm — including the reference arm — goes through this one function.
    Giving ``onmc-current`` its own code path would reintroduce exactly the kind of
    between-arm asymmetry this benchmark exists to avoid.
    """
    if cfg.onmc_bin is None:  # pragma: no cover - guarded by the caller
        raise ValueError("onmc entry point not prepared")
    profile = resolve_budget_profile(arm.budget_mode)
    return [
        str(cfg.onmc_bin),
        "run",
        task.prompt,
        "--execute",
        "--agent",
        "claude",
        "--max-iterations",
        str(arm.max_iterations or cfg.max_iterations),
        "--max-cost-usd",
        str(cfg.max_cost_usd),
        "--budget-mode",
        arm.budget_mode.value,
        "--context-budget",
        str(arm.context_budget or profile.token_budget),
        "--verifier",
        shlex.join(verifier_argv(task, python)),
        "--json",
    ]


def arm_env(arm: Arm, repo: Path) -> dict[str, str]:
    """:func:`cell_env` for the cell, plus the arm's declared env delta.

    The base must stay :func:`cell_env`: it puts the cell venv first on PATH and
    clears ``VIRTUAL_ENV``/``UV_PROJECT_ENVIRONMENT`` so nothing can re-point the
    verifier's ``python`` at ONMC's own interpreter.
    """
    env = cell_env(repo)
    env.update(arm.env_delta)
    return env


def run_onmc_arm(arm: Arm, task: TaskSpec, repo: Path, cfg: EvalConfig, python: Path) -> ArmOutcome:
    """Run one ONMC arm through the full ``onmc run`` vertical path."""
    if cfg.onmc_bin is None:
        return ArmOutcome("onmc entry point not prepared", None)
    env = arm_env(arm, repo)
    _run([str(cfg.onmc_bin), "init"], repo, 300, env=env)
    code, out = _run(onmc_argv(arm, task, cfg, python), repo, cfg.timeout_s, env=env)
    cost = _extract_cost(out)
    payload = _last_json_object(out) or {}
    mode = payload.get("enforcement_mode")
    iterations = payload.get("iterations")
    outcome = ArmOutcome(
        None,
        cost,
        enforcement_mode=mode if isinstance(mode, str) else None,
        iterations=iterations if isinstance(iterations, int) else None,
    )
    if "[timeout]" in out:
        return ArmOutcome("onmc run timeout", cost, outcome.enforcement_mode, outcome.iterations)
    if code == 127:
        return ArmOutcome(
            f"onmc unavailable: {out[:200]}", cost, outcome.enforcement_mode, outcome.iterations
        )
    for marker in ONMC_INFRA_MARKERS:
        if marker in out:
            return ArmOutcome(
                f"onmc did not execute ({marker})",
                cost,
                outcome.enforcement_mode,
                outcome.iterations,
            )
    return outcome


def _prepare_cell(
    task: TaskSpec, dest: Path, cache_root: Path
) -> tuple[Path | None, str | None]:
    """Fresh pinned clone + in-checkout venv + BOTH validity gates + mutation.

    Returns ``(python, None)`` for a usable cell or ``(None, error)``. The order is
    load-bearing: gate 1 proves the verifier can run and the upstream suite is
    green BEFORE the mutation, which is what distinguishes "the regression broke
    it" from "the verifier cannot run at all"; gate 2 proves the mutation actually
    breaks the suite, without which the task would be vacuous.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    cache = cache_root / task.repo.name
    err = prepare_clone(task, dest, cache)
    if err:
        return None, err
    python, err = prepare_venv(dest, REPO_TEST_DEPS.get(task.repo.name, ()))
    if err or python is None:
        return None, err or "venv unavailable"
    cfg_gate = EvalConfig(workdir=dest.parent, trials=1, dry_run=True)
    err = guard_pristine_verifier(task, dest, cfg_gate, python)
    if err:
        return None, err
    err = inject_regression(task, dest)
    if err:
        return None, err
    err = guard_regression_active(task, dest, cfg_gate, python)
    if err:
        return None, err
    return python, None


def run_cell(cell: Cell, cfg: EvalConfig, cache_root: Path) -> ArmRecord:
    """Measure one (task, arm, trial) cell."""
    task, arm = cell.task, cell.arm
    dest = cfg.workdir / "runs" / cell.slug

    def _record(
        status: CellStatus,
        *,
        passed: bool = False,
        latency_ms: float = 0.0,
        infra_error: str | None = None,
        notes: str = "",
        cost_usd: float | None = None,
        diff_lines: int = 0,
        tests_touched: bool = False,
        enforcement_mode: str | None = None,
        iterations: int | None = None,
    ) -> ArmRecord:
        return ArmRecord(
            task.task_id,
            arm.condition.value,
            cell.trial,
            passed,
            latency_ms,
            infra_error=infra_error,
            notes=notes,
            cost_usd=cost_usd,
            diff_lines=diff_lines,
            tests_touched=tests_touched,
            arm=arm.name,
            factor=arm.factor,
            status=status.value,
            enforcement_mode=enforcement_mode,
            iterations=iterations,
        )

    if not arm.is_active:  # pragma: no cover - skipped arms are never scheduled
        return _record(CellStatus.SKIPPED, notes=arm.skipped_reason or "skipped")

    started = time.monotonic()
    python, err = _prepare_cell(task, dest, cache_root)
    if err or python is None:
        return _record(CellStatus.INFRA, infra_error=err or "cell unusable")

    if cfg.dry_run:
        # Zero paid calls: the gates above already ran, and no agent is invoked.
        return _record(CellStatus.DRY_RUN, notes="dry-run: agent not invoked")

    if arm.kind is ArmKind.BARE:
        outcome = run_bare_arm(task, dest, cfg, python)
    else:
        outcome = run_onmc_arm(arm, task, dest, cfg, python)

    diff_lines, tests_touched = _observed_change(dest)
    passed, out = verify(task, dest, cfg, python)
    latency = (time.monotonic() - started) * 1000.0
    note = "" if passed else out.strip().splitlines()[-1][:160] if out.strip() else ""
    if passed and tests_touched:
        # The prompt forbids editing tests. A "pass" that edited a test is a false
        # green, not a repair.
        passed = False
        note = "false green: agent modified a test file"
    status = CellStatus.INFRA if outcome.infra_error else CellStatus.MEASURED
    return _record(
        status,
        passed=passed,
        latency_ms=latency,
        infra_error=outcome.infra_error,
        notes=note,
        cost_usd=outcome.cost_usd,
        diff_lines=diff_lines,
        tests_touched=tests_touched,
        enforcement_mode=outcome.enforcement_mode,
        iterations=outcome.iterations,
    )


# --------------------------------------------------------------------------- #
# Grid planning and the budget ceiling
# --------------------------------------------------------------------------- #


def plan_cells(
    tasks: Sequence[TaskSpec], arms: Sequence[Arm], trials: int, seed: int
) -> list[Cell]:
    """The randomised (task x active arm x trial) grid for ONE pinned run.

    Order is shuffled with a seeded RNG so arm order cannot confound the result,
    and so the whole comparison is reproducible from ``seed``. Skipped arms are
    not scheduled — they consume no budget and appear in the report as SKIPPED.
    """
    cells = [
        Cell(task, arm, trial)
        for task in tasks
        for arm in arms
        if arm.is_active
        for trial in range(1, trials + 1)
    ]
    rng = random.Random(seed)  # noqa: S311 - shuffling trial order, not crypto
    rng.shuffle(cells)
    return cells


def budget_stopped_record(cell: Cell, spent: float, ceiling: float) -> ArmRecord:
    """A cell the spend ceiling prevented. Recorded, never dropped."""
    return ArmRecord(
        cell.task.task_id,
        cell.arm.condition.value,
        cell.trial,
        False,
        0.0,
        arm=cell.arm.name,
        factor=cell.arm.factor,
        status=CellStatus.BUDGET_STOPPED.value,
        notes=f"budget-stopped at ${spent:.2f} of ${ceiling:.2f}",
    )


def skipped_record(task: TaskSpec, arm: Arm, trial: int) -> ArmRecord:
    """The placeholder row for a SKIPPED arm — a valid result, not a loss."""
    return ArmRecord(
        task.task_id,
        arm.condition.value,
        trial,
        False,
        0.0,
        arm=arm.name,
        factor=arm.factor,
        status=CellStatus.SKIPPED.value,
        notes=arm.skipped_reason or "skipped",
    )


CellRunner = Callable[[Cell, EvalConfig, Path], ArmRecord]


@dataclass
class GridOutcome:
    """Accounting for one grid execution."""

    records: list[ArmRecord]
    reported_cost_usd: float | None
    cost_reported_cells: int
    budget_stopped_cells: int


def execute_grid(
    cells: Sequence[Cell],
    cfg: EvalConfig,
    cache_root: Path,
    *,
    runner: CellRunner = run_cell,
    verbose: bool = True,
) -> GridOutcome:
    """Run the grid under a hard spend ceiling.

    Once observed spend reaches ``cfg.max_total_usd`` every remaining cell is
    recorded as ``budget-stopped`` rather than dropped, so the report's cell count
    still equals the planned grid and a truncated run cannot masquerade as a
    complete one.
    """
    records: list[ArmRecord] = []
    spent = 0.0
    reported = 0
    stopped = 0
    for idx, cell in enumerate(cells, start=1):
        if spent >= cfg.max_total_usd:
            stopped += 1
            records.append(budget_stopped_record(cell, spent, cfg.max_total_usd))
            continue
        record = runner(cell, cfg, cache_root)
        records.append(record)
        if record.cost_usd is not None:
            spent += record.cost_usd
            reported += 1
        if verbose:
            print(
                f"[{idx}/{len(cells)}] {record.task_id} {record.arm} t{record.trial}: "
                f"status={record.status} passed={record.passed} "
                f"cost={'n/a' if record.cost_usd is None else f'${record.cost_usd:.3f}'} "
                f"spent=${spent:.2f} infra={record.infra_error or '-'}",
                flush=True,
            )
    return GridOutcome(records, round(spent, 4) if reported else None, reported, stopped)


# --------------------------------------------------------------------------- #
# Dry run: both validity gates and every arm's setup, with ZERO paid calls
# --------------------------------------------------------------------------- #


#: Fields whose values PROVE an ``onmc run`` invocation planned and stopped without
#: reaching an agent. Matched as substrings rather than by parsing the payload
#: because ``run_external_eval._run`` keeps only the last 4000 characters of output
#: and a plan JSON (context packet + DAG) is far larger than that — the front of the
#: object is truncated away, so the object itself will not parse. These four keys
#: are late in the sort-key order, so they survive the truncation.
_PLAN_ONLY_EVIDENCE: tuple[tuple[str, str], ...] = (
    ("status=planned", r'"status"\s*:\s*"planned"'),
    ("stop_reason=plan-only", r'"stop_reason"\s*:\s*"plan-only"'),
    ("verified=false", r'"verified"\s*:\s*false'),
    ("tokens_used=null", r'"tokens_used"\s*:\s*null'),
)


def missing_plan_only_evidence(out: str) -> list[str]:
    """Which plan-only proofs are absent from *out*. Empty means the probe was free.

    ``tokens_used=null`` is the load-bearing one: it is ONMC's own report that no
    agent tokens were consumed, which is what makes this a genuinely zero-cost
    exercise of the arm rather than an assertion that it is.
    """
    return [label for label, pattern in _PLAN_ONLY_EVIDENCE if not re.search(pattern, out)]


def probe_bare_arm(repo: Path) -> tuple[bool, str]:
    """Is the control's agent CLI resolvable? ``--version`` costs nothing."""
    code, out = _run(["claude", "--version"], repo, 120, env=cell_env(repo))
    if code != 0:
        return False, f"claude CLI not runnable (exit {code}): {out[:160]}"
    return True, out.strip().splitlines()[0][:120] if out.strip() else "ok"


def probe_onmc_arm(
    arm: Arm, task: TaskSpec, repo: Path, cfg: EvalConfig, python: Path
) -> tuple[bool, str]:
    """Exercise an ONMC arm's real setup for free via the plan-only path.

    ``onmc run`` without ``--execute`` is plan-only and, by construction, never
    launches an agent or a verifier subprocess — so this resolves the arm's budget
    profile, compiles the task, runs local retrieval, and evaluates the broker's
    capability decisions on the arm's own env, at zero cost. It is a real exercise
    of the arm's configuration path, not a syntax check.
    """
    argv = [arg for arg in onmc_argv(arm, task, cfg, python) if arg != "--execute"]
    if "--execute" in argv:  # pragma: no cover - defensive
        return False, "refusing to probe: argv still contains --execute"
    code, out = _run(argv, repo, 600, env=arm_env(arm, repo))
    if code != 0:
        return False, f"plan-only setup failed (exit {code}): {out[-200:]}"
    missing = missing_plan_only_evidence(out)
    if missing:
        return False, f"plan-only setup lacked evidence of a free plan: {', '.join(missing)}"
    for marker in ONMC_INFRA_MARKERS:
        if marker in out:
            return False, f"plan-only setup hit an instrument failure ({marker})"
    # When the emitted JSON happens to fit inside the captured tail, hold it to the
    # stronger claim as well.
    payload = _last_json_object(out)
    if payload is not None and payload.get("cost_usd") is not None:
        return False, f"plan-only reported a cost ({payload['cost_usd']}) — not a free probe"
    return True, (
        "plan-only accepted the arm configuration "
        "(status=planned, stop_reason=plan-only, verified=false, tokens_used=null)"
    )


def probe_advisory_skip_still_valid(cfg: EvalConfig, repo: Path) -> tuple[bool, str]:
    """Re-verify that the advisory-monitor skip reason has not gone stale.

    A skipped arm must not become a permanent excuse. If a future ONMC exposes an
    enforcement flag, this probe says so and the report flags the skip as stale so
    the ablation gets implemented instead of inherited.
    """
    if cfg.onmc_bin is None:  # pragma: no cover - guarded by the caller
        return True, "onmc entry point not prepared; skip reason unverified"
    code, out = _run([str(cfg.onmc_bin), "run", "--help"], repo, 120, env=cell_env(repo))
    if code != 0:
        return True, f"could not read `onmc run --help` (exit {code}); skip reason unverified"
    found = [token for token in _ADVISORY_FLAG_TOKENS if token in out]
    if found:
        return False, f"SKIP REASON STALE: `onmc run --help` now exposes {', '.join(found)}"
    return True, "confirmed: `onmc run --help` exposes no monitor-enforcement flag"


@dataclass
class DryRunOutcome:
    """What a dry run established, and what it deliberately did not."""

    records: list[ArmRecord]
    gates: dict[str, dict[str, object]]
    arm_setup: dict[str, dict[str, object]]

    @property
    def gates_failed(self) -> int:
        return sum(1 for row in self.gates.values() if not row["ok"])

    @property
    def setup_failed(self) -> int:
        return sum(1 for row in self.arm_setup.values() if not row["ok"])


def dry_run(
    tasks: Sequence[TaskSpec],
    arms: Sequence[Arm],
    cfg: EvalConfig,
    cache_root: Path,
    *,
    scope: str = "task",
    seed: int = 0,
    verbose: bool = True,
) -> DryRunOutcome:
    """Exercise both validity gates and every arm's setup without paying anything.

    ``scope="task"`` (the default) runs the gates ONCE per task: the gate result is
    a property of (repo SHA, mutation, venv recipe) and is identical across arms
    and trials by construction, so repeating it per cell would multiply cost with
    no added information. ``scope="cell"`` runs the full grid for operators who
    want the redundancy. Which one ran is recorded in the report.
    """
    records: list[ArmRecord] = []
    gates: dict[str, dict[str, object]] = {}
    probe: tuple[TaskSpec, Path, Path] | None = None
    gate_arm = Arm(
        name="<validity-gates>",
        condition=Condition.ONMC_CURRENT,
        kind=ArmKind.ONMC,
        factor="none (gate probe)",
    )
    for idx, task in enumerate(tasks, start=1):
        dest = cfg.workdir / "gates" / task.task_id
        python, err = _prepare_cell(task, dest, cache_root)
        gates[task.task_id] = {
            "ok": err is None,
            "repo": task.repo.name,
            "pinned_sha": task.repo.pinned_sha,
            "verifier_argv": list(task.verifier_argv),
            "error": err,
        }
        records.append(
            ArmRecord(
                task.task_id,
                gate_arm.condition.value,
                0,
                False,
                0.0,
                arm=gate_arm.name,
                factor=gate_arm.factor,
                status=(CellStatus.INFRA if err else CellStatus.DRY_RUN).value,
                infra_error=err,
                notes="dry-run: both validity gates exercised; agent not invoked",
            )
        )
        if err is None and probe is None and python is not None:
            probe = (task, dest, python)
        if verbose:
            print(
                f"[gate {idx}/{len(tasks)}] {task.task_id}: "
                f"{'ok' if err is None else f'FAILED: {err}'}",
                flush=True,
            )

    arm_setup = _probe_arms(arms, cfg, probe, verbose=verbose)

    if scope == "cell":
        cells = plan_cells(tasks, arms, cfg.trials, seed)
        for cell in cells:
            gate = gates.get(cell.task.task_id, {"ok": False, "error": "task not gated"})
            records.append(
                ArmRecord(
                    cell.task.task_id,
                    cell.arm.condition.value,
                    cell.trial,
                    False,
                    0.0,
                    arm=cell.arm.name,
                    factor=cell.arm.factor,
                    status=(CellStatus.DRY_RUN if gate["ok"] else CellStatus.INFRA).value,
                    infra_error=None if gate["ok"] else str(gate["error"]),
                    notes="dry-run: agent not invoked",
                )
            )
    return DryRunOutcome(records, gates, arm_setup)


def _probe_arms(
    arms: Sequence[Arm],
    cfg: EvalConfig,
    probe: tuple[TaskSpec, Path, Path] | None,
    *,
    verbose: bool,
) -> dict[str, dict[str, object]]:
    """Probe every arm's setup, including re-validating each skip reason."""
    setup: dict[str, dict[str, object]] = {}
    for arm in arms:
        if not arm.is_active:
            if arm.skipped_reason == ADVISORY_MONITOR_SKIP_REASON and probe is not None:
                ok, detail = probe_advisory_skip_still_valid(cfg, probe[1])
            else:
                ok, detail = True, f"arm skipped: {arm.skipped_reason}"
            setup[arm.name] = {
                "ok": ok,
                "status": CellStatus.SKIPPED.value,
                "skipped_reason": arm.skipped_reason,
                "detail": detail,
            }
        elif probe is None:
            setup[arm.name] = {
                "ok": False,
                "status": "unprobed",
                "skipped_reason": None,
                "detail": "no task passed the validity gates, so no checkout was available",
            }
        elif arm.kind is ArmKind.BARE:
            ok, detail = probe_bare_arm(probe[1])
            setup[arm.name] = {
                "ok": ok,
                "status": "probed",
                "skipped_reason": None,
                "detail": detail,
            }
        else:
            ok, detail = probe_onmc_arm(arm, probe[0], probe[1], cfg, probe[2])
            setup[arm.name] = {
                "ok": ok,
                "status": "probed",
                "skipped_reason": None,
                "detail": detail,
            }
        if verbose:
            row = setup[arm.name]
            print(
                f"[setup] {arm.name}: {'ok' if row['ok'] else 'PROBLEM'} — {row['detail']}",
                flush=True,
            )
    return setup


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def arm_taxonomy(rows: Sequence[ArmRecord]) -> dict[str, int]:
    """Failure taxonomy for one arm.

    Budget-stopped, skipped, and dry-run rows are counted here and everything else
    is delegated to the external benchmark's :func:`_taxonomy`, so the two reports
    share identical ``infra`` / ``no_change`` / ``wrong_change`` /
    ``false_green_test_edit`` buckets. Two benchmarks with divergent taxonomies
    cannot be read together.
    """
    counts: dict[str, int] = {}
    scored: list[TrialRecord] = []
    for row in rows:
        if row.status == CellStatus.BUDGET_STOPPED.value:
            counts["budget_stopped"] = counts.get("budget_stopped", 0) + 1
        elif row.status == CellStatus.SKIPPED.value:
            counts["skipped"] = counts.get("skipped", 0) + 1
        elif row.status == CellStatus.DRY_RUN.value:
            counts["dry_run"] = counts.get("dry_run", 0) + 1
        else:
            scored.append(row)
    for key, value in _taxonomy(scored).items():
        counts[key] = counts.get(key, 0) + value
    return counts


def _cost_stats(rows: Sequence[ArmRecord]) -> dict[str, object]:
    """Cost is ``None`` when unreported — "unknown" and "zero" are different facts."""
    costs = [row.cost_usd for row in rows if row.cost_usd is not None]
    return {
        "mean_cost_usd": round(mean(costs), 4) if costs else None,
        "median_cost_usd": round(median(costs), 4) if costs else None,
        "total_cost_usd": round(sum(costs), 4) if costs else None,
        "cost_reported_cells": len(costs),
        "cost_unreported_cells": len(rows) - len(costs),
    }


def summarize(
    records: Sequence[ArmRecord], arms: Sequence[Arm], cfg: EvalConfig, *, seed: int
) -> dict[str, object]:
    """Per-arm metrics. Only MEASURED cells enter a denominator."""
    summary: dict[str, object] = {}
    for arm in arms:
        rows = [row for row in records if row.arm == arm.name]
        usable = [row for row in rows if row.status == CellStatus.MEASURED.value]
        outcomes = [1.0 if row.passed else 0.0 for row in usable]
        latencies = [row.latency_ms for row in usable]
        ci: tuple[float, float] | None = None
        if outcomes:
            ci = bootstrap_ci(outcomes, seed=derive_seed(seed, arm.name, "pass"))
        modes = sorted({row.enforcement_mode for row in usable if row.enforcement_mode})
        entry: dict[str, object] = {
            "status": CellStatus.SKIPPED.value if not arm.is_active else "active",
            "skipped_reason": arm.skipped_reason,
            "skip_detail": arm.skip_detail,
            "condition": arm.condition.value,
            "factor": arm.factor,
            "factor_confounds": list(arm.factor_confounds),
            "config": arm.resolved_config(cfg),
            "cells": len(rows),
            "measured": len(usable),
            "infra_failures": sum(1 for r in rows if r.status == CellStatus.INFRA.value),
            "budget_stopped": sum(
                1 for r in rows if r.status == CellStatus.BUDGET_STOPPED.value
            ),
            "dry_run_cells": sum(1 for r in rows if r.status == CellStatus.DRY_RUN.value),
            "passed": int(sum(outcomes)),
            "pass_at_1": round(mean(outcomes), 4) if outcomes else None,
            "pass_at_1_ci95": None if ci is None else [round(ci[0], 4), round(ci[1], 4)],
            # ``list`` is invariant, so widen for the shared helper. ArmRecord IS a
            # TrialRecord; reimplementing pass^k here would be the real risk.
            "pass_hat_k": _pass_hat_k(list[TrialRecord](usable)) if usable else None,
            "mean_latency_ms": round(mean(latencies), 1) if latencies else None,
            "median_latency_ms": round(median(latencies), 1) if latencies else None,
            "latency_variance": round(variance(latencies), 1) if len(latencies) > 1 else None,
            "observed_enforcement_modes": modes,
            "false_greens_blocked": sum(1 for r in rows if r.tests_touched),
            "failure_taxonomy": arm_taxonomy(rows),
        }
        entry.update(_cost_stats(usable))
        summary[arm.name] = entry
    return summary


def paired_analysis(
    records: Sequence[ArmRecord], baseline_arm: str, treatment_arm: str, *, seed: int
) -> dict[str, object]:
    """Per-task paired delta (treatment - baseline) with a bootstrap CI.

    Pairing is per TASK over that task's MEASURED cells, so a task that is easy or
    hard for both arms cannot drive the delta. Deltas and CI come from
    :mod:`~.experiment.stats`; nothing here is hand-rolled.
    """

    def rates(arm_name: str) -> dict[str, float]:
        buckets: dict[str, list[float]] = {}
        for row in records:
            if row.arm != arm_name or row.status != CellStatus.MEASURED.value:
                continue
            buckets.setdefault(row.task_id, []).append(1.0 if row.passed else 0.0)
        return {task: mean(vals) for task, vals in buckets.items() if vals}

    deltas = paired_deltas(rates(baseline_arm), rates(treatment_arm))
    if not deltas:
        return {
            "baseline": baseline_arm,
            "treatment": treatment_arm,
            "paired_tasks": 0,
            "mean_delta": None,
            "delta_ci95": None,
            "significant": False,
        }
    values = [deltas[key] for key in sorted(deltas)]
    low, high = bootstrap_ci(
        values, seed=derive_seed(seed, "paired", baseline_arm, treatment_arm)
    )
    return {
        "baseline": baseline_arm,
        "treatment": treatment_arm,
        "paired_tasks": len(values),
        "per_task_delta": {key: round(deltas[key], 4) for key in sorted(deltas)},
        "mean_delta": round(mean(values), 4),
        "delta_ci95": [round(low, 4), round(high, 4)],
        "significant": bool(low > 0.0 or high < 0.0),
    }


def build_report(
    manifest: PortfolioManifest,
    arms: Sequence[Arm],
    records: Sequence[ArmRecord],
    cfg: EvalConfig,
    *,
    tasks: Sequence[TaskSpec] | None = None,
    planned_cells: int,
    reported_cost_usd: float | None,
    cost_reported_cells: int,
    budget_stopped_cells: int,
    dry: DryRunOutcome | None,
    dry_run_scope: str,
) -> dict[str, object]:
    """Assemble the ablation report.

    ``tasks`` describes what actually ran (``--task`` may narrow the corpus), so the
    report never implies coverage the run did not have.
    """
    seed = manifest.experiment.seed
    ran = list(tasks if tasks is not None else manifest.tasks)
    active = [arm.name for arm in arms if arm.is_active]
    report: dict[str, object] = {
        "experiment_id": manifest.experiment.experiment_id.value,
        "task_set_revision": manifest.experiment.task_set_revision,
        "audit_status": manifest.audit_status.value,
        "code_sha": manifest.experiment.environment.code_sha,
        "code_sha_under_test": code_sha(),
        "seed": seed,
        "trials_per_cell": cfg.trials,
        "metric_label": MetricLabel.MEASURED.value,
        "reference_arm": REFERENCE_ARM,
        "repos": sorted({task.repo.name for task in ran}),
        "tasks": len(ran),
        "task_ids": [task.task_id for task in ran],
        "manifest_tasks": len(manifest.tasks),
        "arms": [
            {
                "name": arm.name,
                "condition": arm.condition.value,
                "kind": arm.kind.value,
                "factor": arm.factor,
                "factor_confounds": list(arm.factor_confounds),
                "status": "active" if arm.is_active else CellStatus.SKIPPED.value,
                "skipped_reason": arm.skipped_reason,
                "skip_detail": arm.skip_detail,
                "config": arm.resolved_config(cfg),
            }
            for arm in arms
        ],
        "active_arms": active,
        "skipped_arms": {
            arm.name: arm.skipped_reason for arm in arms if not arm.is_active
        },
        "planned_cells": planned_cells,
        "recorded_cells": len(records),
        "infra_failure_cells": sum(
            1 for row in records if row.status == CellStatus.INFRA.value
        ),
        "budget_ceiling_usd": cfg.max_total_usd,
        "budget_stopped_cells": budget_stopped_cells,
        "total_reported_cost_usd": reported_cost_usd,
        "cost_reported_cells": cost_reported_cells,
        "summary": summarize(records, arms, cfg, seed=seed),
        "paired": {
            arm.name: paired_analysis(records, REFERENCE_ARM, arm.name, seed=seed)
            for arm in arms
            if arm.name != REFERENCE_ARM
        },
        "records": [row.to_dict() for row in records],
    }
    if dry is not None:
        report["dry_run"] = {
            "enabled": True,
            "scope": dry_run_scope,
            "paid_calls": 0,
            "tasks_gated": len(dry.gates),
            "gates_failed": dry.gates_failed,
            "arm_setups_probed": len(dry.arm_setup),
            "arm_setups_failed": dry.setup_failed,
            "validity_gates": dry.gates,
            "arm_setup": dry.arm_setup,
        }
    else:
        report["dry_run"] = {"enabled": False}
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_env_pairs(pairs: Sequence[str]) -> dict[str, str]:
    """Parse ``KEY=VALUE`` strings into a mapping, rejecting malformed input."""
    out: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"--candidate-env expects KEY=VALUE, got {pair!r}")
        out[key.strip()] = value
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trials", type=int, default=None)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Exercise both validity gates and every arm's setup with ZERO paid calls.",
    )
    ap.add_argument(
        "--dry-run-scope",
        choices=("task", "cell"),
        default="task",
        help="Gate once per task (default) or once per grid cell.",
    )
    ap.add_argument(
        "--max-total-usd",
        type=float,
        default=10.0,
        help="Hard spend ceiling. Remaining cells are recorded as budget-stopped, never dropped.",
    )
    ap.add_argument("--max-cost-usd", type=float, default=1.0, help="Per-run agent cost cap.")
    ap.add_argument(
        "--max-iterations", type=int, default=4, help="Loop iterations N for ONMC arms."
    )
    ap.add_argument(
        "--task",
        action="append",
        default=[],
        metavar="TASK_ID",
        help="Restrict the run to these task ids (repeatable).",
    )
    ap.add_argument(
        "--only-arm",
        action="append",
        default=[],
        metavar="ARM",
        help="Restrict the run to these arm names (repeatable).",
    )
    ap.add_argument(
        "--candidate-budget-mode",
        choices=tuple(mode.value for mode in BudgetMode),
        default=None,
        help="Candidate-arm delta: ONMC budget/retrieval profile.",
    )
    ap.add_argument("--candidate-context-budget", type=int, default=None)
    ap.add_argument("--candidate-max-iterations", type=int, default=None)
    ap.add_argument(
        "--candidate-env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Candidate-arm env delta (repeatable).",
    )
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    manifest = PortfolioManifest.from_dict(json.loads(Path(args.manifest).read_text()))
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    cache_root = workdir / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)

    trials = args.trials or manifest.experiment.trials
    cfg = EvalConfig(
        workdir=workdir,
        trials=trials,
        dry_run=args.dry_run,
        max_iterations=args.max_iterations,
        max_cost_usd=args.max_cost_usd,
        max_total_usd=args.max_total_usd,
    )

    candidate = CandidateSpec(
        budget_mode=args.candidate_budget_mode,
        context_budget=args.candidate_context_budget,
        max_iterations=args.candidate_max_iterations,
        env=parse_env_pairs(args.candidate_env),
    )
    arms = build_arms(cfg, candidate)
    if args.only_arm:
        wanted = set(args.only_arm)
        unknown = wanted - {arm.name for arm in arms}
        if unknown:
            print(f"FATAL: unknown arm(s): {sorted(unknown)}", file=sys.stderr)
            return 2
        arms = [arm for arm in arms if arm.name in wanted]

    tasks = list(manifest.tasks)
    if args.task:
        wanted_tasks = set(args.task)
        unknown_tasks = wanted_tasks - {task.task_id for task in tasks}
        if unknown_tasks:
            print(f"FATAL: unknown task(s): {sorted(unknown_tasks)}", file=sys.stderr)
            return 2
        tasks = [task for task in tasks if task.task_id in wanted_tasks]

    onmc_bin, onmc_err = prepare_onmc_venv(workdir)
    if onmc_err:
        print(f"FATAL: {onmc_err}", file=sys.stderr)
        return 1
    cfg.onmc_bin = onmc_bin

    planned = plan_cells(tasks, arms, trials, manifest.experiment.seed)
    dry: DryRunOutcome | None = None
    if args.dry_run:
        dry = dry_run(
            tasks,
            arms,
            cfg,
            cache_root,
            scope=args.dry_run_scope,
            seed=manifest.experiment.seed,
        )
        records = list(dry.records)
        reported_cost: float | None = None
        cost_cells = 0
        stopped = 0
    else:
        outcome = execute_grid(planned, cfg, cache_root)
        records = outcome.records
        reported_cost = outcome.reported_cost_usd
        cost_cells = outcome.cost_reported_cells
        stopped = outcome.budget_stopped_cells

    # Skipped arms are a valid result: they get a placeholder row per (task, trial)
    # so the report's cell count still equals the planned full grid.
    for arm in arms:
        if arm.is_active:
            continue
        for task in tasks:
            for trial in range(1, trials + 1):
                records.append(skipped_record(task, arm, trial))

    report = build_report(
        manifest,
        arms,
        records,
        cfg,
        tasks=tasks,
        planned_cells=len(planned),
        reported_cost_usd=reported_cost,
        cost_reported_cells=cost_cells,
        budget_stopped_cells=stopped,
        dry=dry,
        dry_run_scope=args.dry_run_scope,
    )
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    headline = {
        "arms": report["arms"],
        "skipped_arms": report["skipped_arms"],
        "infra_failure_cells": report["infra_failure_cells"],
        "budget_stopped_cells": report["budget_stopped_cells"],
        "dry_run": (
            {
                key: value
                for key, value in dict(report["dry_run"]).items()  # type: ignore[call-overload]
                if key not in {"validity_gates", "arm_setup"}
            }
            if args.dry_run
            else report["dry_run"]
        ),
    }
    print(json.dumps(headline, indent=2, sort_keys=True))
    if dry is not None and (dry.gates_failed or dry.setup_failed):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
