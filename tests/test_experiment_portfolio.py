"""Tests for the M6 external-proof portfolio harness.

These exercise the fixture path only — no subprocess, no network, no paid API
calls. The whole point of M6 is that it is *runnable* and *honest* without
spending money, and the tests enforce exactly that.
"""

from __future__ import annotations

import pytest

from oh_no_my_claudecode.experiment.contracts import (
    BenchmarkAuditStatus,
    Condition,
    Environment,
    ExperimentId,
    ExperimentManifest,
    RunId,
    TrialResult,
)
from oh_no_my_claudecode.experiment.kernel import ExperimentReport
from oh_no_my_claudecode.experiment.portfolio import (
    AgentAdapter,
    ClaimLevel,
    CliAgentAdapter,
    CredentialsRequiredError,
    FixtureAgentAdapter,
    PortfolioManifest,
    PortfolioReport,
    PortfolioRunner,
    RepoRef,
    TaskKind,
    TaskSpec,
    load_portfolio,
)

CONDITIONS = (Condition.BARE_AGENT, Condition.ONMC_CURRENT, Condition.ONMC_CANDIDATE)


def make_repo(sha: str = "0" * 40) -> RepoRef:
    return RepoRef(name="toy", url="https://example.invalid/toy.git", pinned_sha=sha)


def make_task(task_id: str, kind: TaskKind = TaskKind.BUGFIX) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        repo=make_repo(),
        prompt="do the thing",
        verifier_argv=("pytest", "-q"),
        task_kind=kind,
        expected_outcome="the verifier exits 0",
    )


def make_experiment(
    *, trials: int = 2, seed: int = 7, audit: BenchmarkAuditStatus = BenchmarkAuditStatus.SUSPECT
) -> ExperimentManifest:
    return ExperimentManifest(
        experiment_id=ExperimentId("portfolio-test"),
        task_set_revision="rev-0",
        conditions=CONDITIONS,
        trials=trials,
        seed=seed,
        environment=Environment(
            code_sha="abc123", config_hash="cfg", model="m", provider="p"
        ),
        audit_status=audit,
    )


def make_manifest(
    *,
    trials: int = 2,
    audit: BenchmarkAuditStatus = BenchmarkAuditStatus.SUSPECT,
    n_tasks: int = 3,
) -> PortfolioManifest:
    tasks = tuple(make_task(f"task-{i}") for i in range(n_tasks))
    return PortfolioManifest(
        experiment=make_experiment(trials=trials, audit=audit),
        tasks=tasks,
        audit_status=audit,
        leakage_notes="test corpus",
    )


# --------------------------------------------------------------------------- #
# contracts: TaskSpec / RepoRef / PortfolioManifest validation
# --------------------------------------------------------------------------- #


def test_repo_ref_validation() -> None:
    with pytest.raises(ValueError):
        RepoRef(name="", url="https://x.invalid/x.git", pinned_sha="0" * 40)
    with pytest.raises(ValueError):
        RepoRef(name="x", url="not-a-url", pinned_sha="0" * 40)
    with pytest.raises(ValueError):
        RepoRef(name="x", url="https://x.invalid/x.git", pinned_sha="ZZZ")


def test_task_spec_validation() -> None:
    with pytest.raises(ValueError):
        TaskSpec(
            task_id="t",
            repo=make_repo(),
            prompt="p",
            verifier_argv=(),  # empty verifier is rejected
            task_kind=TaskKind.BUGFIX,
            expected_outcome="o",
        )
    with pytest.raises(ValueError):
        TaskSpec(
            task_id="t",
            repo=make_repo(),
            prompt="   ",  # blank prompt rejected
            verifier_argv=("pytest",),
            task_kind=TaskKind.BUGFIX,
            expected_outcome="o",
        )


def test_portfolio_rejects_empty_and_duplicate_tasks() -> None:
    with pytest.raises(ValueError):
        PortfolioManifest(experiment=make_experiment(), tasks=())
    dup = make_task("same")
    with pytest.raises(ValueError):
        PortfolioManifest(experiment=make_experiment(), tasks=(dup, make_task("same")))


# --------------------------------------------------------------------------- #
# starter corpus
# --------------------------------------------------------------------------- #


def test_starter_corpus_loads_and_is_suspect() -> None:
    manifest = load_portfolio()
    assert manifest.audit_status is BenchmarkAuditStatus.SUSPECT
    assert manifest.is_claim_ready is False
    assert len(manifest.tasks) == 3
    assert manifest.leakage_notes  # explicit provenance note present
    kinds = {t.task_kind for t in manifest.tasks}
    assert TaskKind.AMBIGUITY in kinds  # corpus spans more than one task shape


def test_starter_corpus_json_roundtrips() -> None:
    manifest = load_portfolio()
    rebuilt = PortfolioManifest.from_dict(manifest.to_dict())
    assert rebuilt.to_json() == manifest.to_json()


# --------------------------------------------------------------------------- #
# runner: deterministic, paired, comparative
# --------------------------------------------------------------------------- #


def test_fixture_agent_adapter_satisfies_protocol() -> None:
    assert isinstance(FixtureAgentAdapter(), AgentAdapter)


def test_runner_over_starter_is_deterministic_and_paired() -> None:
    manifest = load_portfolio()
    adapter = FixtureAgentAdapter(seed=3, cost_scale={Condition.ONMC_CANDIDATE: 2.0})

    report_a = PortfolioRunner(manifest, adapter).run()
    report_b = PortfolioRunner(manifest, adapter).run()

    assert isinstance(report_a, PortfolioReport)
    assert isinstance(report_a.report, ExperimentReport)
    assert report_a.to_json() == report_b.to_json()  # byte-identical, seeded

    # paired deltas exist for every task against the baseline, per treatment arm.
    treatments = {c for c in manifest.experiment.conditions if c is not Condition.BARE_AGENT}
    for treatment in treatments:
        tasks_with_delta = {
            d.task_id for d in report_a.report.task_deltas if d.condition is treatment
        }
        assert tasks_with_delta == set(manifest.task_ids)
    assert report_a.report.baseline is Condition.BARE_AGENT


def test_known_pass_mix_reaches_report() -> None:
    manifest = make_manifest(trials=4)
    adapter = FixtureAgentAdapter(
        pass_bias={Condition.BARE_AGENT: 0.0, Condition.ONMC_CURRENT: 1.0}
    )
    report = PortfolioRunner(manifest, adapter).run()
    assert report.report.condition(Condition.BARE_AGENT).pass_at_1 == 0.0
    assert report.report.condition(Condition.ONMC_CURRENT).pass_at_1 == 1.0


# --------------------------------------------------------------------------- #
# claim gate
# --------------------------------------------------------------------------- #


def test_suspect_starter_is_internal_even_with_multiple_trials() -> None:
    manifest = load_portfolio()
    assert manifest.experiment.requires_uncertainty  # trials > 1
    report = PortfolioRunner(manifest, FixtureAgentAdapter()).run()
    assert report.claim_level is ClaimLevel.INTERNAL
    assert report.is_claim_ready is False


def test_valid_audit_multi_trial_is_external() -> None:
    manifest = make_manifest(trials=2, audit=BenchmarkAuditStatus.VALID)
    assert manifest.is_claim_ready is True
    assert manifest.claim_level() is ClaimLevel.EXTERNAL
    report = PortfolioRunner(manifest, FixtureAgentAdapter()).run()
    assert report.claim_level is ClaimLevel.EXTERNAL
    assert report.is_claim_ready is True


def test_valid_audit_single_trial_stays_internal() -> None:
    manifest = make_manifest(trials=1, audit=BenchmarkAuditStatus.VALID)
    assert manifest.is_claim_ready is True  # audit gate passes
    report = PortfolioRunner(manifest, FixtureAgentAdapter()).run()
    assert report.claim_level is ClaimLevel.INTERNAL  # but >1 trial required for external


# --------------------------------------------------------------------------- #
# real-run seam: never calls out
# --------------------------------------------------------------------------- #


def test_cli_adapter_raises_without_credentials() -> None:
    adapter = CliAgentAdapter(agent_cmd=("claude", "--dangerously-skip-permissions"))
    with pytest.raises(CredentialsRequiredError):
        adapter.run(make_task("t"), Condition.ONMC_CURRENT)


def test_cli_adapter_requires_agent_cmd() -> None:
    with pytest.raises(ValueError):
        CliAgentAdapter(agent_cmd=())


# --------------------------------------------------------------------------- #
# exclusion accounting
# --------------------------------------------------------------------------- #


class ErroringAdapter:
    """Delegates to a fixture adapter but raises for one chosen task."""

    def __init__(self, fail_task_id: str) -> None:
        self._fail = fail_task_id
        self._inner = FixtureAgentAdapter(seed=1)

    def run(self, task: TaskSpec, condition: Condition) -> TrialResult:
        if task.task_id == self._fail:
            raise RuntimeError("verifier could not run")
        return self._inner.run(task, condition)


def test_exclusion_accounting_when_task_errors() -> None:
    manifest = make_manifest(trials=2, n_tasks=3)
    report = PortfolioRunner(manifest, ErroringAdapter("task-1")).run()

    n_conditions = len(manifest.experiment.conditions)
    trials = manifest.experiment.trials
    total = n_conditions * len(manifest.tasks) * trials

    assert report.total_trials == total
    # task-1 errors under every condition and trial -> excluded from measurement.
    assert report.excluded_trials == n_conditions * trials
    assert report.executed_trials == total - report.excluded_trials
    assert {e.task_id for e in report.exclusions} == {"task-1"}
    assert all(e.reason.startswith("RuntimeError") for e in report.exclusions)
    # the run still completes and produces a comparative report.
    assert isinstance(report.report, ExperimentReport)


def test_no_exclusions_on_clean_run() -> None:
    manifest = make_manifest()
    report = PortfolioRunner(manifest, FixtureAgentAdapter()).run()
    assert report.excluded_trials == 0
    assert report.exclusions == ()
    assert report.executed_trials == report.total_trials


def test_run_id_is_stamped_by_runner_not_adapter() -> None:
    # FixtureAgentAdapter emits trial=0 placeholders; the runner must stamp the
    # canonical RunId (including the real trial index and experiment id).
    manifest = make_manifest(trials=3, n_tasks=1)
    report = PortfolioRunner(manifest, FixtureAgentAdapter()).run()
    agg = report.report.condition(Condition.ONMC_CURRENT)
    assert agg.trials == 3  # 1 task x 3 trials, distinct cells, none collapsed


def test_expected_runid_slug_is_valid() -> None:
    # guards against accidental drift in how the bridge stamps ids.
    rid = RunId(
        experiment_id="portfolio-test",
        condition=Condition.ONMC_CANDIDATE,
        task_id="task-0",
        trial=1,
    )
    assert rid.slug == "portfolio-test.onmc-candidate.task-0.t1"
