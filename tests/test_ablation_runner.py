"""Tests for ``scripts/run_ablations.py`` — the three-condition + ablation runner.

These tests pin the properties that make an ablation *trustworthy* rather than
merely runnable. Each one corresponds to a way a benchmark can be silently wrong:

- an arm that claims to vary one factor but varies several,
- an arm that was faked because it could not be measured honestly,
- a verifier argv rewritten so ONMC's reference monitor denies it (which zeroes
  the treatment arm while the control runs unimpeded),
- an interpreter bound so the verifier resolves back to ONMC's own venv,
- an infra or budget-stopped cell scored as an agent loss instead of excluded,
- a fabricated ``0`` cost where the provider reported nothing,
- a ``--dry-run`` that quietly makes a paid call.

Nothing here spawns a subprocess, clones a repository, or contacts a provider.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_ablations.py"
EXTERNAL_EVAL_PATH = REPO_ROOT / "scripts" / "run_external_eval.py"
CONTROLLER_PATH = REPO_ROOT / "src" / "oh_no_my_claudecode" / "harness_run" / "controller.py"
RUN_COMMANDS_PATH = REPO_ROOT / "src" / "oh_no_my_claudecode" / "harness_run" / "commands.py"


def _load() -> ModuleType:
    """Import the runner script as a module by file path."""
    module_name = "_run_ablations_under_test"
    cached = sys.modules.get(module_name)
    if isinstance(cached, ModuleType):
        return cached
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


abl = _load()


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def cfg(tmp_path: Path) -> Any:
    return abl.EvalConfig(
        workdir=tmp_path,
        trials=2,
        dry_run=False,
        max_iterations=4,
        max_cost_usd=1.0,
        max_total_usd=1.0,
        onmc_bin=tmp_path / "onmc-venv" / "bin" / "onmc",
    )


@pytest.fixture
def task() -> Any:
    from oh_no_my_claudecode.experiment.portfolio import RepoRef, TaskKind, TaskSpec

    return TaskSpec(
        task_id="six-bugfix-integer-types",
        repo=RepoRef(name="six", url="https://example.invalid/six.git", pinned_sha="c8e3940"),
        prompt="Fix six.py so the upstream suite passes. Do not edit any test.",
        verifier_argv=("python", "-m", "pytest", "-q", "test_six.py"),
        task_kind=TaskKind.BUGFIX,
        expected_outcome="test_six.py passes",
    )


@pytest.fixture
def arms(cfg: Any) -> list[Any]:
    return abl.build_arms(cfg, abl.CandidateSpec())


def _arm(arms: list[Any], name: str) -> Any:
    match = [arm for arm in arms if arm.name == name]
    assert match, f"no arm named {name!r} (have {[a.name for a in arms]})"
    return match[0]


def _record(arm: Any, task_id: str, trial: int, **kwargs: Any) -> Any:
    return abl.ArmRecord(
        task_id,
        arm.condition.value,
        trial,
        bool(kwargs.pop("passed", False)),
        float(kwargs.pop("latency_ms", 0.0)),
        arm=arm.name,
        factor=arm.factor,
        status=kwargs.pop("status", abl.CellStatus.MEASURED.value),
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Arm design: three conditions, one factor each
# --------------------------------------------------------------------------- #


def test_all_three_protocol_conditions_are_present(arms: list[Any]) -> None:
    from oh_no_my_claudecode.experiment.contracts import Condition

    conditions = {arm.condition for arm in arms}
    assert conditions == {
        Condition.BARE_AGENT,
        Condition.ONMC_CURRENT,
        Condition.ONMC_CANDIDATE,
    }
    assert _arm(arms, "bare-agent").condition is Condition.BARE_AGENT
    assert _arm(arms, "onmc-current").condition is Condition.ONMC_CURRENT
    assert _arm(arms, "onmc-candidate").condition is Condition.ONMC_CANDIDATE


def test_every_expected_ablation_arm_exists(arms: list[Any]) -> None:
    names = {arm.name for arm in arms}
    assert {
        "bare-agent",
        "onmc-current",
        "onmc-candidate",
        "abl-retrieval-hybrid",
        "abl-memory-off",
        "abl-monitor-advisory",
        "abl-single-iteration",
    } <= names


@pytest.mark.parametrize(
    ("arm_name", "expected_diff"),
    [
        ("abl-retrieval-hybrid", {"budget_mode", "retrieval_mode", "top_k"}),
        ("abl-memory-off", {"env_delta"}),
        ("abl-single-iteration", {"max_iterations"}),
    ],
)
def test_each_ablation_arm_differs_from_reference_by_exactly_one_factor(
    arms: list[Any], cfg: Any, arm_name: str, expected_diff: set[str]
) -> None:
    reference = _arm(arms, abl.REFERENCE_ARM).resolved_config(cfg)
    candidate = _arm(arms, arm_name).resolved_config(cfg)
    assert reference.keys() == candidate.keys()
    differing = {key for key in reference if reference[key] != candidate[key]}
    assert differing == expected_diff


def test_retrieval_arm_holds_the_token_budget_equal_to_isolate_retrieval_mode(
    arms: list[Any], cfg: Any
) -> None:
    """``--budget-mode deep`` bundles a token-budget jump; the arm neutralises it.

    Without pinning ``--context-budget`` back to standard's ceiling, a measured
    difference could be a bigger context rather than hybrid retrieval.
    """
    reference = _arm(arms, abl.REFERENCE_ARM).resolved_config(cfg)
    retrieval = _arm(arms, "abl-retrieval-hybrid").resolved_config(cfg)
    assert retrieval["context_budget"] == reference["context_budget"]
    assert reference["retrieval_mode"] != retrieval["retrieval_mode"]


def test_retrieval_arm_reads_modes_from_onmc_own_profile_table(arms: list[Any], cfg: Any) -> None:
    """The retrieval knob is ONMC's, not invented here."""
    from oh_no_my_claudecode.harness_run.budget_modes import BudgetMode, resolve_budget_profile

    assert resolve_budget_profile(BudgetMode.STANDARD).retrieval_mode == "bm25"
    assert resolve_budget_profile(BudgetMode.DEEP).retrieval_mode == "hybrid"
    config = _arm(arms, "abl-retrieval-hybrid").resolved_config(cfg)
    assert config["retrieval_mode"] == "hybrid"
    assert config["budget_mode"] == "deep"


def test_memory_arm_uses_the_real_learning_kill_switch(arms: list[Any]) -> None:
    from oh_no_my_claudecode.learning.activation import (
        LEARNING_ENABLED_ENV,
        is_learning_enabled,
    )

    delta = dict(_arm(arms, "abl-memory-off").env_delta)
    assert delta == {LEARNING_ENABLED_ENV: "0"}
    # The value really does disable learning, per ONMC's own predicate.
    assert is_learning_enabled(delta) is False
    assert is_learning_enabled({}) is True


def test_single_iteration_arm_sets_one_shot_against_the_reference_n(
    arms: list[Any], cfg: Any
) -> None:
    assert _arm(arms, "abl-single-iteration").resolved_config(cfg)["max_iterations"] == 1
    assert _arm(arms, abl.REFERENCE_ARM).resolved_config(cfg)["max_iterations"] == 4


def test_every_arm_declares_a_factor(arms: list[Any]) -> None:
    for arm in arms:
        assert arm.factor.strip(), f"arm {arm.name} has no declared factor"


# --------------------------------------------------------------------------- #
# The arm that cannot be measured honestly
# --------------------------------------------------------------------------- #


def test_advisory_monitor_arm_is_skipped_with_a_machine_readable_reason(
    arms: list[Any],
) -> None:
    arm = _arm(arms, "abl-monitor-advisory")
    assert arm.is_active is False
    assert arm.skipped_reason == abl.ADVISORY_MONITOR_SKIP_REASON
    assert arm.skipped_reason == "advisory-monitor-not-reachable-from-cli"
    assert "enforced=True" in arm.skip_detail


def test_advisory_skip_reason_is_still_true_of_the_shipped_source() -> None:
    """Guard the *finding*, not just the skip.

    If ONMC ever exposes an advisory/enforcement knob, this test fails and the
    ablation must be implemented for real instead of inheriting the skip.
    """
    controller = CONTROLLER_PATH.read_text(encoding="utf-8")
    assert "enforced=True" in controller
    assert "enforced=False" not in controller
    command_surface = RUN_COMMANDS_PATH.read_text(encoding="utf-8")
    for token in abl._ADVISORY_FLAG_TOKENS:
        assert token not in command_surface, f"{token} now exists — implement the arm"


def test_skipped_arm_is_never_scheduled_and_costs_nothing(
    arms: list[Any], task: Any
) -> None:
    cells = abl.plan_cells([task], arms, trials=3, seed=7)
    assert {cell.arm.name for cell in cells}.isdisjoint({"abl-monitor-advisory"})
    assert all(cell.arm.is_active for cell in cells)


def test_skipped_arm_still_appears_in_the_report(arms: list[Any], cfg: Any, task: Any) -> None:
    arm = _arm(arms, "abl-monitor-advisory")
    records = [abl.skipped_record(task, arm, trial) for trial in (1, 2)]
    summary = abl.summarize(records, [arm], cfg, seed=1)
    entry = summary["abl-monitor-advisory"]
    assert entry["status"] == "skipped"
    assert entry["skipped_reason"] == abl.ADVISORY_MONITOR_SKIP_REASON
    # A skipped arm reports no metrics — it must never look like a zero score.
    assert entry["pass_at_1"] is None
    assert entry["pass_at_1_ci95"] is None
    assert entry["measured"] == 0
    assert entry["failure_taxonomy"] == {"skipped": 2}


# --------------------------------------------------------------------------- #
# Candidate condition (condition 3)
# --------------------------------------------------------------------------- #


def test_candidate_arm_is_skipped_when_no_delta_is_declared(cfg: Any) -> None:
    arm = abl.build_candidate_arm(abl.CandidateSpec(), cfg)
    assert arm.is_active is False
    assert arm.skipped_reason == "candidate-delta-undeclared"


def test_candidate_arm_is_skipped_when_the_declared_delta_is_empty(cfg: Any) -> None:
    """A candidate identical to current ONMC is not a third condition."""
    arm = abl.build_candidate_arm(abl.CandidateSpec(budget_mode="standard"), cfg)
    assert arm.is_active is False
    assert arm.skipped_reason == "candidate-delta-empty"


@pytest.mark.parametrize(
    "spec_kwargs",
    [
        {"budget_mode": "deep"},
        {"max_iterations": 9},
        {"env": {"ONMC_EMBEDDER": "fastembed"}},
        {"context_budget": 9000},
    ],
)
def test_candidate_arm_is_active_for_any_real_declared_delta(
    cfg: Any, spec_kwargs: dict[str, Any]
) -> None:
    from oh_no_my_claudecode.experiment.contracts import Condition

    arm = abl.build_candidate_arm(abl.CandidateSpec(**spec_kwargs), cfg)
    assert arm.is_active is True
    assert arm.condition is Condition.ONMC_CANDIDATE
    assert arm.resolved_config(cfg) != abl.Arm(
        name=abl.REFERENCE_ARM,
        condition=Condition.ONMC_CURRENT,
        kind=abl.ArmKind.ONMC,
        factor="none",
    ).resolved_config(cfg)


def test_bare_current_and_candidate_run_in_one_randomised_grid(cfg: Any, task: Any) -> None:
    built = abl.build_arms(cfg, abl.CandidateSpec(budget_mode="deep"))
    cells = abl.plan_cells([task], built, trials=2, seed=20260724)
    scheduled = {cell.arm.name for cell in cells}
    assert {"bare-agent", "onmc-current", "onmc-candidate"} <= scheduled


def test_parse_env_pairs_rejects_malformed_input() -> None:
    assert abl.parse_env_pairs(["A=1", "B="]) == {"A": "1", "B": ""}
    with pytest.raises(ValueError, match="KEY=VALUE"):
        abl.parse_env_pairs(["nope"])


# --------------------------------------------------------------------------- #
# Hard-won invariants inherited from the external benchmark
# --------------------------------------------------------------------------- #


def test_verifier_argv_stays_literally_python_m_pytest(
    arms: list[Any], cfg: Any, task: Any, tmp_path: Path
) -> None:
    """ONMC's monitor allowlists verifier commands by ARGV PREFIX.

    Rewriting argv[0] to an interpreter path makes the monitor DENY the verifier,
    aborting ``onmc run`` before it executes while the bare arm runs unimpeded —
    which silently zeroes every ONMC arm.
    """
    interpreter = tmp_path / ".eval-venv" / "bin" / "python"
    for arm in arms:
        if arm.kind is not abl.ArmKind.ONMC or not arm.is_active:
            continue
        argv = abl.onmc_argv(arm, task, cfg, interpreter)
        verifier = argv[argv.index("--verifier") + 1]
        assert verifier == "python -m pytest -q test_six.py"
        assert verifier.startswith("python -m pytest")
        assert str(interpreter) not in verifier


def test_onmc_arm_argv_never_launches_through_uv_run_project(
    arms: list[Any], cfg: Any, task: Any, tmp_path: Path
) -> None:
    """``uv run --project`` re-points the verifier's ``python`` at ONMC's venv."""
    argv = abl.onmc_argv(_arm(arms, abl.REFERENCE_ARM), task, cfg, tmp_path / "python")
    assert argv[0] == str(cfg.onmc_bin)
    assert "uv" not in argv
    assert "--project" not in argv


def test_onmc_arm_argv_carries_the_arms_own_knobs(
    arms: list[Any], cfg: Any, task: Any, tmp_path: Path
) -> None:
    argv = abl.onmc_argv(_arm(arms, "abl-retrieval-hybrid"), task, cfg, tmp_path / "python")
    assert argv[argv.index("--budget-mode") + 1] == "deep"
    assert argv[argv.index("--context-budget") + 1] == "4000"
    argv = abl.onmc_argv(_arm(arms, "abl-single-iteration"), task, cfg, tmp_path / "python")
    assert argv[argv.index("--max-iterations") + 1] == "1"


def test_arm_env_binds_the_cell_venv_and_clears_virtualenv(
    arms: list[Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cell interpreter must win on PATH and no outer venv may re-point it."""
    monkeypatch.setenv("VIRTUAL_ENV", "/somewhere/else")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/somewhere/else")
    env = abl.arm_env(_arm(arms, "abl-memory-off"), tmp_path)
    assert env["PATH"].split(":")[0] == str(tmp_path / ".eval-venv" / "bin")
    assert "VIRTUAL_ENV" not in env
    assert "UV_PROJECT_ENVIRONMENT" not in env
    assert env["ONMC_LEARNING"] == "0"


def test_reference_arm_env_does_not_carry_any_ablation_delta(
    arms: list[Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ONMC_LEARNING", raising=False)
    env = abl.arm_env(_arm(arms, abl.REFERENCE_ARM), tmp_path)
    assert "ONMC_LEARNING" not in env


def test_infra_markers_are_byte_identical_to_the_external_benchmark() -> None:
    """The copied marker list must not drift from ``run_external_eval.run_onmc``.

    Those markers are what keep a provider-side stop or a denied capability from
    being banked as an agent loss.
    """
    source = EXTERNAL_EVAL_PATH.read_text(encoding="utf-8")
    block = re.search(r"for marker in \(\s*(.*?)\s*\):", source, re.DOTALL)
    assert block is not None, "could not locate the marker tuple in run_external_eval"
    upstream = tuple(re.findall(r'"([^"]+)"', block.group(1)))
    assert upstream == abl.ONMC_INFRA_MARKERS


def test_provider_side_stops_are_recorded_as_infra_not_as_losses(
    arms: list[Any], cfg: Any, task: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        abl, "_run", lambda *a, **k: (0, '{"status":"failed"}\nstop_reason=agent-credentials')
    )
    outcome = abl.run_onmc_arm(
        _arm(arms, abl.REFERENCE_ARM), task, tmp_path, cfg, tmp_path / "python"
    )
    assert outcome.infra_error is not None
    assert "agent-credentials" in outcome.infra_error


def test_cost_is_never_fabricated_when_onmc_reports_null(
    arms: list[Any], cfg: Any, task: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.dumps({"status": "completed", "cost_usd": None, "enforcement_mode": "enforced"})
    monkeypatch.setattr(abl, "_run", lambda *a, **k: (0, payload))
    outcome = abl.run_onmc_arm(
        _arm(arms, abl.REFERENCE_ARM), task, tmp_path, cfg, tmp_path / "python"
    )
    assert outcome.cost_usd is None
    assert outcome.enforcement_mode == "enforced"


# --------------------------------------------------------------------------- #
# Dry run: both gates, every arm's setup, zero paid calls
# --------------------------------------------------------------------------- #


def _stub_cell_preparation(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace every I/O boundary of ``_prepare_cell`` and record the call order."""
    calls: list[str] = []

    def _record(name: str, result: Any = None) -> Any:
        def _inner(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return result

        return _inner

    monkeypatch.setattr(abl, "prepare_clone", _record("prepare_clone", None))
    monkeypatch.setattr(
        abl, "prepare_venv", _record("prepare_venv", (Path("/cell/.eval-venv/bin/python"), None))
    )
    monkeypatch.setattr(abl, "guard_pristine_verifier", _record("guard_pristine_verifier", None))
    monkeypatch.setattr(abl, "inject_regression", _record("inject_regression", None))
    monkeypatch.setattr(abl, "guard_regression_active", _record("guard_regression_active", None))
    return calls


def test_dry_run_exercises_both_validity_gates_in_the_right_order(
    task: Any, cfg: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate 1 before the mutation, gate 2 after — neither may be skipped.

    Gate 1 is what distinguishes "the regression broke the suite" from "the
    verifier cannot run at all"; gate 2 is what stops a vacuous task.
    """
    calls = _stub_cell_preparation(monkeypatch)
    python, err = abl._prepare_cell(task, tmp_path / "cell", tmp_path / "cache")
    assert err is None and python is not None
    assert calls == [
        "prepare_clone",
        "prepare_venv",
        "guard_pristine_verifier",
        "inject_regression",
        "guard_regression_active",
    ]


def test_dry_run_makes_zero_paid_calls(
    arms: list[Any], task: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No agent runner may be reached while ``--dry-run`` is set."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a dry run must never invoke an agent")

    monkeypatch.setattr(abl, "run_bare_arm", _explode)
    monkeypatch.setattr(abl, "run_onmc_arm", _explode)
    monkeypatch.setattr(
        abl, "_prepare_cell", lambda *a, **k: (Path("/cell/.eval-venv/bin/python"), None)
    )
    dry_cfg = abl.EvalConfig(workdir=tmp_path, trials=1, dry_run=True)
    for arm in arms:
        if not arm.is_active:
            continue
        record = abl.run_cell(abl.Cell(task, arm, 1), dry_cfg, tmp_path / "cache")
        assert record.status == abl.CellStatus.DRY_RUN.value
        assert record.cost_usd is None
        assert record.infra_error is None


def test_dry_run_gates_every_task_and_probes_every_arm(
    arms: list[Any], task: Any, cfg: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_cell_preparation(monkeypatch)
    monkeypatch.setattr(abl, "probe_bare_arm", lambda repo: (True, "claude 1.0"))
    monkeypatch.setattr(abl, "probe_onmc_arm", lambda *a, **k: (True, "planned"))
    monkeypatch.setattr(abl, "probe_advisory_skip_still_valid", lambda *a, **k: (True, "confirmed"))
    outcome = abl.dry_run([task], arms, cfg, tmp_path / "cache", verbose=False)
    assert set(outcome.gates) == {task.task_id}
    assert outcome.gates_failed == 0
    assert set(outcome.arm_setup) == {arm.name for arm in arms}
    assert outcome.setup_failed == 0
    assert all(record.status == abl.CellStatus.DRY_RUN.value for record in outcome.records)


def test_dry_run_records_a_gate_failure_as_infra_never_as_a_loss(
    arms: list[Any], task: Any, cfg: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(abl, "_prepare_cell", lambda *a, **k: (None, "pristine verifier failed"))
    monkeypatch.setattr(abl, "probe_advisory_skip_still_valid", lambda *a, **k: (True, "ok"))
    outcome = abl.dry_run([task], arms, cfg, tmp_path / "cache", verbose=False)
    assert outcome.gates_failed == 1
    assert outcome.gates[task.task_id]["error"] == "pristine verifier failed"
    infra = [r for r in outcome.records if r.status == abl.CellStatus.INFRA.value]
    assert len(infra) == 1
    assert infra[0].passed is False
    # With no usable checkout, arm setup is reported unprobed — not silently ok.
    unprobed = [row for row in outcome.arm_setup.values() if row["status"] == "unprobed"]
    assert unprobed and all(row["ok"] is False for row in unprobed)


def test_advisory_skip_probe_flags_a_stale_reason(
    cfg: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(abl, "_run", lambda *a, **k: (0, "Options:\n  --monitor-mode TEXT\n"))
    ok, detail = abl.probe_advisory_skip_still_valid(cfg, tmp_path)
    assert ok is False
    assert "SKIP REASON STALE" in detail
    monkeypatch.setattr(abl, "_run", lambda *a, **k: (0, "Options:\n  --budget-mode TEXT\n"))
    ok, detail = abl.probe_advisory_skip_still_valid(cfg, tmp_path)
    assert ok is True


#: A realistic truncated ``onmc run --json`` plan-only tail. ``_run`` keeps only the
#: last 4000 characters, so the front of the object (including ``cost_usd``) is gone
#: and the payload does NOT parse — exactly the condition the probe must survive.
PLAN_ONLY_TAIL = (
    'runs/run-751dc13fd4c639f6"},"policy_decision":null,"proof_complete":false,'
    '"proof_reasons":[],"receipt":null,"resume_run_id":null,"resumed":false,'
    '"stages":[],"status":"planned","stop_reason":"plan-only","tokens_used":null,'
    '"verified":false,"worktree_path":null}'
)


def test_plan_only_evidence_survives_output_truncation() -> None:
    """The probe must not depend on parsing a payload that cannot fit in the tail."""
    assert abl._last_json_object(PLAN_ONLY_TAIL) is None
    assert abl.missing_plan_only_evidence(PLAN_ONLY_TAIL) == []


@pytest.mark.parametrize(
    ("tail", "missing"),
    [
        (PLAN_ONLY_TAIL.replace('"status":"planned"', '"status":"completed"'), "status=planned"),
        (
            PLAN_ONLY_TAIL.replace('"tokens_used":null', '"tokens_used":4210'),
            "tokens_used=null",
        ),
        (PLAN_ONLY_TAIL.replace('"verified":false', '"verified":true'), "verified=false"),
        (
            PLAN_ONLY_TAIL.replace('"stop_reason":"plan-only"', '"stop_reason":"converged"'),
            "stop_reason=plan-only",
        ),
    ],
)
def test_a_probe_that_actually_executed_is_rejected(
    arms: list[Any], cfg: Any, task: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    tail: str, missing: str,
) -> None:
    """A probe that consumed tokens or ran the loop is not a free probe."""
    monkeypatch.setattr(abl, "_run", lambda *a, **k: (0, tail))
    ok, detail = abl.probe_onmc_arm(
        _arm(arms, abl.REFERENCE_ARM), task, tmp_path, cfg, tmp_path / "python"
    )
    assert ok is False
    assert missing in detail


def test_onmc_arm_setup_probe_rejects_a_run_that_reports_a_cost(
    arms: list[Any], cfg: Any, task: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the payload does fit, hold it to the stronger zero-cost claim too."""
    paid = json.dumps(
        {
            "status": "planned",
            "stop_reason": "plan-only",
            "verified": False,
            "tokens_used": None,
            "cost_usd": 0.42,
        }
    )
    monkeypatch.setattr(abl, "_run", lambda *a, **k: (0, paid))
    ok, detail = abl.probe_onmc_arm(
        _arm(arms, abl.REFERENCE_ARM), task, tmp_path, cfg, tmp_path / "python"
    )
    assert ok is False
    assert "not a free probe" in detail


def test_onmc_arm_setup_probe_rejects_an_instrument_failure(
    arms: list[Any], cfg: Any, task: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        abl, "_run", lambda *a, **k: (0, PLAN_ONLY_TAIL + "\nverifier-unavailable")
    )
    ok, detail = abl.probe_onmc_arm(
        _arm(arms, abl.REFERENCE_ARM), task, tmp_path, cfg, tmp_path / "python"
    )
    assert ok is False
    assert "verifier-unavailable" in detail


def test_onmc_arm_setup_probe_never_passes_execute(
    arms: list[Any], cfg: Any, task: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    def _capture(argv: list[str], *a: Any, **k: Any) -> tuple[int, str]:
        seen.append(argv)
        return 0, PLAN_ONLY_TAIL

    monkeypatch.setattr(abl, "_run", _capture)
    ok, _ = abl.probe_onmc_arm(
        _arm(arms, abl.REFERENCE_ARM), task, tmp_path, cfg, tmp_path / "python"
    )
    assert ok is True
    assert seen and "--execute" not in seen[0]
    # The probe still exercises the arm's real knobs, not a stripped-down command.
    assert "--budget-mode" in seen[0] and "--verifier" in seen[0]


# --------------------------------------------------------------------------- #
# Budget ceiling
# --------------------------------------------------------------------------- #


def test_budget_ceiling_records_stopped_cells_instead_of_dropping_them(
    arms: list[Any], cfg: Any, task: Any
) -> None:
    cells = abl.plan_cells([task], arms, trials=3, seed=3)

    def _runner(cell: Any, _cfg: Any, _cache: Path) -> Any:
        return _record(cell.arm, cell.task.task_id, cell.trial, passed=True, cost_usd=0.6)

    outcome = abl.execute_grid(cells, cfg, Path("/cache"), runner=_runner, verbose=False)
    assert len(outcome.records) == len(cells), "budget stop must not drop cells"
    stopped = [r for r in outcome.records if r.status == abl.CellStatus.BUDGET_STOPPED.value]
    assert outcome.budget_stopped_cells == len(stopped) > 0
    assert all("budget-stopped at $" in r.notes for r in stopped)
    # The ceiling is a HARD stop: spend never exceeds it by more than one cell.
    assert outcome.reported_cost_usd is not None
    assert outcome.cost_reported_cells == len(cells) - len(stopped)


def test_budget_stopped_cells_are_excluded_from_the_pass_rate(
    arms: list[Any], cfg: Any, task: Any
) -> None:
    arm = _arm(arms, abl.REFERENCE_ARM)
    records = [
        _record(arm, task.task_id, 1, passed=True, cost_usd=0.1),
        abl.budget_stopped_record(abl.Cell(task, arm, 2), 1.0, 1.0),
        abl.budget_stopped_record(abl.Cell(task, arm, 3), 1.0, 1.0),
    ]
    entry = abl.summarize(records, [arm], cfg, seed=1)[abl.REFERENCE_ARM]
    assert entry["cells"] == 3
    assert entry["measured"] == 1
    assert entry["budget_stopped"] == 2
    assert entry["pass_at_1"] == 1.0, "a budget stop must not be scored as a loss"
    assert entry["failure_taxonomy"]["budget_stopped"] == 2


def test_a_run_with_no_reported_cost_reports_none_not_zero(
    arms: list[Any], cfg: Any, task: Any
) -> None:
    arm = _arm(arms, abl.REFERENCE_ARM)
    cells = [abl.Cell(task, arm, trial) for trial in (1, 2)]
    outcome = abl.execute_grid(
        cells,
        cfg,
        Path("/cache"),
        runner=lambda cell, _c, _p: _record(cell.arm, cell.task.task_id, cell.trial, passed=True),
        verbose=False,
    )
    assert outcome.reported_cost_usd is None
    assert outcome.cost_reported_cells == 0
    entry = abl.summarize(outcome.records, [arm], cfg, seed=1)[abl.REFERENCE_ARM]
    assert entry["mean_cost_usd"] is None
    assert entry["median_cost_usd"] is None
    assert entry["total_cost_usd"] is None
    assert entry["cost_unreported_cells"] == 2


# --------------------------------------------------------------------------- #
# Accounting and statistics
# --------------------------------------------------------------------------- #


def test_infra_cells_are_excluded_from_the_pass_rate_not_scored_zero(
    arms: list[Any], cfg: Any, task: Any
) -> None:
    arm = _arm(arms, abl.REFERENCE_ARM)
    records = [
        _record(arm, task.task_id, 1, passed=True),
        _record(
            arm,
            task.task_id,
            2,
            status=abl.CellStatus.INFRA.value,
            infra_error="onmc did not execute (agent-unavailable)",
        ),
    ]
    entry = abl.summarize(records, [arm], cfg, seed=1)[abl.REFERENCE_ARM]
    assert entry["measured"] == 1
    assert entry["infra_failures"] == 1
    assert entry["pass_at_1"] == 1.0
    assert entry["failure_taxonomy"]["infra"] == 1


def test_summary_carries_every_metric_the_protocol_requires(
    arms: list[Any], cfg: Any, task: Any
) -> None:
    arm = _arm(arms, abl.REFERENCE_ARM)
    records = [
        _record(arm, "t1", 1, passed=True, latency_ms=1000.0, cost_usd=0.2),
        _record(arm, "t1", 2, passed=True, latency_ms=2000.0, cost_usd=0.4),
        _record(arm, "t2", 1, passed=False, latency_ms=3000.0, diff_lines=4),
    ]
    entry = abl.summarize(records, [arm], cfg, seed=11)[abl.REFERENCE_ARM]
    for key in (
        "pass_at_1",
        "pass_at_1_ci95",
        "pass_hat_k",
        "mean_latency_ms",
        "median_latency_ms",
        "latency_variance",
        "mean_cost_usd",
        "median_cost_usd",
        "cost_reported_cells",
        "failure_taxonomy",
        "infra_failures",
        "factor",
        "config",
    ):
        assert key in entry, f"missing metric {key}"
    assert entry["pass_at_1"] == pytest.approx(2 / 3, abs=1e-4)
    low, high = entry["pass_at_1_ci95"]
    assert 0.0 <= low <= entry["pass_at_1"] <= high <= 1.0
    assert entry["pass_hat_k"] == 0.5, "one of two tasks passed on every usable trial"
    assert entry["mean_latency_ms"] == 2000.0
    assert entry["median_latency_ms"] == 2000.0
    assert entry["latency_variance"] == 1000000.0
    assert entry["mean_cost_usd"] == pytest.approx(0.3, abs=1e-6)
    assert entry["failure_taxonomy"]["wrong_change"] == 1


def test_pass_at_1_ci_is_deterministic_for_a_fixed_seed(
    arms: list[Any], cfg: Any
) -> None:
    arm = _arm(arms, abl.REFERENCE_ARM)
    records = [_record(arm, f"t{i}", 1, passed=bool(i % 2)) for i in range(8)]
    first = abl.summarize(records, [arm], cfg, seed=42)[abl.REFERENCE_ARM]
    second = abl.summarize(records, [arm], cfg, seed=42)[abl.REFERENCE_ARM]
    assert first["pass_at_1_ci95"] == second["pass_at_1_ci95"]


def test_failure_taxonomy_reuses_the_external_benchmark_buckets(
    arms: list[Any], task: Any
) -> None:
    """A drifted taxonomy would make the two reports unreadable together."""
    arm = _arm(arms, abl.REFERENCE_ARM)
    records = [
        _record(arm, "t1", 1, passed=False, diff_lines=0),
        _record(arm, "t2", 1, passed=False, diff_lines=12),
        _record(arm, "t3", 1, passed=False, diff_lines=3, tests_touched=True),
        _record(arm, "t4", 1, status=abl.CellStatus.INFRA.value, infra_error="clone failed"),
        abl.budget_stopped_record(abl.Cell(task, arm, 1), 1.0, 1.0),
    ]
    assert abl.arm_taxonomy(records) == {
        "no_change": 1,
        "wrong_change": 1,
        "false_green_test_edit": 1,
        "infra": 1,
        "budget_stopped": 1,
    }


def test_paired_deltas_are_computed_against_the_reference_arm(
    arms: list[Any]
) -> None:
    reference = _arm(arms, abl.REFERENCE_ARM)
    treatment = _arm(arms, "abl-single-iteration")
    records = [
        _record(reference, "t1", 1, passed=True),
        _record(reference, "t2", 1, passed=True),
        _record(treatment, "t1", 1, passed=True),
        _record(treatment, "t2", 1, passed=False),
    ]
    paired = abl.paired_analysis(records, abl.REFERENCE_ARM, treatment.name, seed=5)
    assert paired["baseline"] == abl.REFERENCE_ARM
    assert paired["treatment"] == treatment.name
    assert paired["paired_tasks"] == 2
    assert paired["per_task_delta"] == {"t1": 0.0, "t2": -1.0}
    assert paired["mean_delta"] == -0.5


def test_paired_analysis_pairs_only_measured_cells(arms: list[Any]) -> None:
    reference = _arm(arms, abl.REFERENCE_ARM)
    treatment = _arm(arms, "abl-memory-off")
    records = [
        _record(reference, "t1", 1, passed=True),
        _record(
            treatment, "t1", 1, status=abl.CellStatus.INFRA.value, infra_error="clone failed"
        ),
    ]
    paired = abl.paired_analysis(records, abl.REFERENCE_ARM, treatment.name, seed=5)
    assert paired["paired_tasks"] == 0
    assert paired["mean_delta"] is None
    assert paired["significant"] is False


def test_plan_cells_is_deterministic_for_a_fixed_seed_and_covers_the_grid(
    arms: list[Any], task: Any
) -> None:
    first = [cell.slug for cell in abl.plan_cells([task], arms, 3, seed=99)]
    second = [cell.slug for cell in abl.plan_cells([task], arms, 3, seed=99)]
    assert first == second
    active = [arm for arm in arms if arm.is_active]
    assert len(first) == len(active) * 3
    assert len(set(first)) == len(first)
    # Randomised order, not grouped by arm (rule 7).
    assert first != sorted(first)


# --------------------------------------------------------------------------- #
# Report shape
# --------------------------------------------------------------------------- #


def _manifest() -> Any:
    from oh_no_my_claudecode.experiment.portfolio import PortfolioManifest

    raw = json.loads(
        (REPO_ROOT / "datasets" / "experiment" / "portfolio_external_v3.json").read_text()
    )
    return PortfolioManifest.from_dict(raw)


def test_report_names_every_arm_with_its_status_and_reason(cfg: Any) -> None:
    manifest = _manifest()
    built = abl.build_arms(cfg, abl.CandidateSpec())
    report = abl.build_report(
        manifest,
        built,
        [],
        cfg,
        planned_cells=0,
        reported_cost_usd=None,
        cost_reported_cells=0,
        budget_stopped_cells=0,
        dry=None,
        dry_run_scope="task",
    )
    assert report["reference_arm"] == abl.REFERENCE_ARM
    assert report["metric_label"] == "measured"
    assert report["skipped_arms"] == {
        "onmc-candidate": "candidate-delta-undeclared",
        "abl-monitor-advisory": abl.ADVISORY_MONITOR_SKIP_REASON,
    }
    for entry in report["arms"]:
        assert entry["status"] in {"active", "skipped"}
        if entry["status"] == "skipped":
            assert entry["skipped_reason"]
            assert entry["skip_detail"]
    # Every non-reference arm gets a paired delta slot against the reference.
    assert set(report["paired"]) == {arm.name for arm in built if arm.name != abl.REFERENCE_ARM}
    assert report["total_reported_cost_usd"] is None


def test_report_is_json_serialisable_and_records_the_pinned_code_sha(cfg: Any) -> None:
    manifest = _manifest()
    built = abl.build_arms(cfg, abl.CandidateSpec(budget_mode="deep"))
    task = manifest.tasks[0]
    arm = _arm(built, abl.REFERENCE_ARM)
    records = [_record(arm, task.task_id, 1, passed=True, cost_usd=0.12, latency_ms=900.0)]
    report = abl.build_report(
        manifest,
        built,
        records,
        cfg,
        planned_cells=1,
        reported_cost_usd=0.12,
        cost_reported_cells=1,
        budget_stopped_cells=0,
        dry=None,
        dry_run_scope="task",
    )
    text = json.dumps(report, sort_keys=True)
    assert '"code_sha_under_test"' in text
    assert report["code_sha"] == manifest.experiment.environment.code_sha
    assert report["records"][0]["arm"] == abl.REFERENCE_ARM
    assert report["records"][0]["status"] == "measured"
    assert report["records"][0]["factor"]


def test_report_records_the_dry_run_provenance(cfg: Any) -> None:
    manifest = _manifest()
    built = abl.build_arms(cfg, abl.CandidateSpec())
    dry = abl.DryRunOutcome(
        records=[],
        gates={"t1": {"ok": True, "error": None}},
        arm_setup={"bare-agent": {"ok": True, "detail": "claude 1.0", "status": "probed"}},
    )
    report = abl.build_report(
        manifest,
        built,
        [],
        cfg,
        planned_cells=0,
        reported_cost_usd=None,
        cost_reported_cells=0,
        budget_stopped_cells=0,
        dry=dry,
        dry_run_scope="task",
    )
    assert report["dry_run"]["enabled"] is True
    assert report["dry_run"]["paid_calls"] == 0
    assert report["dry_run"]["scope"] == "task"
    assert report["dry_run"]["gates_failed"] == 0
    assert report["dry_run"]["validity_gates"] == dry.gates


def test_report_describes_the_tasks_that_actually_ran(cfg: Any) -> None:
    """``--task`` narrows the corpus; the report must not imply full coverage."""
    manifest = _manifest()
    built = abl.build_arms(cfg, abl.CandidateSpec())
    subset = [manifest.tasks[0]]
    report = abl.build_report(
        manifest,
        built,
        [],
        cfg,
        tasks=subset,
        planned_cells=0,
        reported_cost_usd=None,
        cost_reported_cells=0,
        budget_stopped_cells=0,
        dry=None,
        dry_run_scope="task",
    )
    assert report["tasks"] == 1
    assert report["task_ids"] == [subset[0].task_id]
    assert report["manifest_tasks"] == len(manifest.tasks) > 1
    assert report["repos"] == [subset[0].repo.name]


def test_cli_rejects_an_unknown_arm(tmp_path: Path) -> None:
    manifest_path = REPO_ROOT / "datasets" / "experiment" / "portfolio_external_v3.json"
    code = abl.main(
        [
            "--manifest",
            str(manifest_path),
            "--workdir",
            str(tmp_path),
            "--out",
            str(tmp_path / "report.json"),
            "--only-arm",
            "abl-does-not-exist",
        ]
    )
    assert code == 2
