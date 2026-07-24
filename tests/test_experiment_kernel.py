"""Tests for the experiment kernel and its statistics helpers."""

from __future__ import annotations

import pytest

from oh_no_my_claudecode.experiment import stats
from oh_no_my_claudecode.experiment.contracts import (
    Condition,
    Environment,
    ExperimentId,
    ExperimentManifest,
    MetricLabel,
    RunId,
    TrialResult,
)
from oh_no_my_claudecode.experiment.kernel import (
    ExperimentReport,
    ExperimentRunner,
    FixtureAdapter,
    TrialAdapter,
)


def make_manifest(
    *,
    trials: int = 3,
    seed: int = 1234,
    conditions: tuple[Condition, ...] = (Condition.BARE_AGENT, Condition.ONMC_CURRENT),
) -> ExperimentManifest:
    return ExperimentManifest(
        experiment_id=ExperimentId("exp-kernel-test"),
        task_set_revision="rev-1",
        conditions=conditions,
        trials=trials,
        seed=seed,
        environment=Environment(
            code_sha="abc123",
            config_hash="cfg1",
            model="test-model",
            provider="test",
        ),
    )


class ScriptedAdapter:
    """A hand-built adapter returning exact, table-driven outcomes."""

    def __init__(self, table: dict[tuple[Condition, str], tuple[bool, float, float, int, int]]):
        self._table = table

    def run(self, run_id: RunId) -> TrialResult:
        passed, cost, latency, turns, tokens = self._table[(run_id.condition, run_id.task_id)]
        return TrialResult(
            run_id=run_id,
            passed=passed,
            cost_usd=cost,
            latency_ms=latency,
            turns=turns,
            tool_calls=turns,
            context_tokens=tokens,
        )


# --------------------------------------------------------------------------- #
# stats
# --------------------------------------------------------------------------- #


def test_mean_median_variance_basics() -> None:
    assert stats.mean([1.0, 2.0, 3.0]) == pytest.approx(2.0)
    assert stats.median([3.0, 1.0, 2.0]) == pytest.approx(2.0)
    assert stats.median([1.0, 2.0, 3.0, 4.0]) == pytest.approx(2.5)
    # unbiased (ddof=1) variance of 1..5 is 2.5
    assert stats.variance([1.0, 2.0, 3.0, 4.0, 5.0]) == pytest.approx(2.5)
    assert stats.variance([7.0]) == 0.0


def test_stats_reject_empty() -> None:
    for fn in (stats.mean, stats.median, stats.variance):
        with pytest.raises(ValueError):
            fn([])
    with pytest.raises(ValueError):
        stats.bootstrap_ci([], seed=1)


def test_bootstrap_ci_brackets_the_mean() -> None:
    samples = [float(x) for x in range(1, 21)]
    m = stats.mean(samples)
    low, high = stats.bootstrap_ci(samples, seed=7, iterations=2000)
    assert low <= m <= high
    assert low < high


def test_bootstrap_ci_is_seed_deterministic() -> None:
    samples = [1.0, 5.0, 2.0, 8.0, 3.0]
    first = stats.bootstrap_ci(samples, seed=99, iterations=500)
    second = stats.bootstrap_ci(samples, seed=99, iterations=500)
    assert first == second


def test_bootstrap_ci_single_sample_collapses() -> None:
    assert stats.bootstrap_ci([4.2], seed=1) == (4.2, 4.2)


def test_paired_deltas_intersects_keys() -> None:
    base = {"a": 1.0, "b": 2.0, "c": 9.0}
    treat = {"a": 1.5, "b": 5.0, "d": 0.0}
    assert stats.paired_deltas(base, treat) == {"a": 0.5, "b": 3.0}


# --------------------------------------------------------------------------- #
# kernel
# --------------------------------------------------------------------------- #


def test_fixture_adapter_satisfies_protocol() -> None:
    assert isinstance(FixtureAdapter(), TrialAdapter)


def test_report_is_deterministic_for_same_seed() -> None:
    manifest = make_manifest(trials=4, seed=2024)
    tasks = ["task-a", "task-b", "task-c"]
    adapter = FixtureAdapter(seed=5, cost_scale={Condition.ONMC_CURRENT: 2.0})

    report_a = ExperimentRunner(manifest, tasks, adapter).run()
    report_b = ExperimentRunner(manifest, tasks, adapter).run()

    assert isinstance(report_a, ExperimentReport)
    assert report_a.to_json() == report_b.to_json()


def test_randomized_order_is_seed_stable_and_a_permutation() -> None:
    manifest = make_manifest(trials=3, seed=42)
    tasks = ["t1", "t2", "t3"]
    runner = ExperimentRunner(manifest, tasks, FixtureAdapter())

    order_one = [r.slug for r in runner.plan()]
    order_two = [r.slug for r in runner.plan()]
    assert order_one == order_two  # seed-stable

    canonical = sorted(r.slug for r in runner._grid())
    assert sorted(order_one) == canonical  # same multiset — a true permutation
    assert order_one != canonical  # and actually shuffled, not identity


def test_different_seeds_change_execution_order() -> None:
    tasks = ["t1", "t2", "t3", "t4"]
    runner_a = ExperimentRunner(make_manifest(seed=1), tasks, FixtureAdapter())
    runner_b = ExperimentRunner(make_manifest(seed=2), tasks, FixtureAdapter())
    order_a = [r.slug for r in runner_a.plan()]
    order_b = [r.slug for r in runner_b.plan()]
    assert order_a != order_b


def test_known_pass_mix_yields_expected_pass_at_1() -> None:
    manifest = make_manifest(trials=5, seed=3)
    tasks = ["task-a", "task-b"]
    adapter = FixtureAdapter(
        seed=11,
        pass_bias={Condition.BARE_AGENT: 0.0, Condition.ONMC_CURRENT: 1.0},
    )
    report = ExperimentRunner(manifest, tasks, adapter).run()

    assert report.condition(Condition.BARE_AGENT).pass_at_1 == 0.0
    assert report.condition(Condition.ONMC_CURRENT).pass_at_1 == 1.0
    # 2 tasks x 5 trials per condition
    assert report.condition(Condition.BARE_AGENT).trials == 10
    assert report.condition(Condition.ONMC_CURRENT).trials == 10


def test_paired_deltas_correct_on_hand_built_fixture() -> None:
    manifest = make_manifest(trials=1, seed=1)
    tasks = ["task-x", "task-y"]
    table = {
        (Condition.BARE_AGENT, "task-x"): (False, 1.00, 200.0, 3, 1000),
        (Condition.BARE_AGENT, "task-y"): (True, 2.00, 400.0, 5, 2000),
        (Condition.ONMC_CURRENT, "task-x"): (True, 1.50, 250.0, 4, 1200),
        (Condition.ONMC_CURRENT, "task-y"): (True, 2.75, 380.0, 6, 2100),
    }
    report = ExperimentRunner(manifest, tasks, ScriptedAdapter(table)).run()

    deltas = {d.task_id: d for d in report.task_deltas}
    assert set(deltas) == {"task-x", "task-y"}

    x = deltas["task-x"]
    assert x.condition is Condition.ONMC_CURRENT
    assert x.pass_delta == pytest.approx(1.0)  # False(0) -> True(1)
    x_metrics = dict(x.metric_deltas)
    assert x_metrics["cost_usd"] == pytest.approx(0.5)
    assert x_metrics["latency_ms"] == pytest.approx(50.0)
    assert x_metrics["turns"] == pytest.approx(1.0)
    assert x_metrics["context_tokens"] == pytest.approx(200.0)

    y = deltas["task-y"]
    assert y.pass_delta == pytest.approx(0.0)  # True -> True
    y_metrics = dict(y.metric_deltas)
    assert y_metrics["cost_usd"] == pytest.approx(0.75)
    assert y_metrics["latency_ms"] == pytest.approx(-20.0)


def test_one_trial_metric_ci_collapses_to_point() -> None:
    manifest = make_manifest(trials=1, seed=1)
    tasks = ["only-task"]
    adapter = FixtureAdapter(seed=8)
    report = ExperimentRunner(manifest, tasks, adapter).run()

    agg = report.condition(Condition.ONMC_CURRENT)
    assert agg.trials == 1
    cost = agg.metric("cost_usd")
    assert cost.n == 1
    assert cost.ci_low == cost.ci_high == pytest.approx(cost.mean)
    assert cost.label is MetricLabel.MEASURED


def test_empty_task_set_yields_zeroed_report() -> None:
    manifest = make_manifest(trials=2, seed=1)
    report = ExperimentRunner(manifest, [], FixtureAdapter()).run()

    assert report.task_deltas == ()
    for agg in report.conditions:
        assert agg.trials == 0
        assert agg.pass_at_1 == 0.0
        for summary in agg.metrics:
            assert summary.n == 0
            assert summary.mean == 0.0
            assert summary.ci_low == summary.ci_high == 0.0


def test_estimated_label_propagates() -> None:
    manifest = make_manifest(trials=2, seed=1)
    tasks = ["t1"]
    adapter = FixtureAdapter(seed=2, metric_label=MetricLabel.ESTIMATED)
    report = ExperimentRunner(manifest, tasks, adapter).run()

    agg = report.condition(Condition.ONMC_CURRENT)
    assert agg.label is MetricLabel.ESTIMATED
    assert all(s.label is MetricLabel.ESTIMATED for s in agg.metrics)
    assert all(d.label is MetricLabel.ESTIMATED for d in report.task_deltas)


def test_baseline_must_be_a_manifest_condition() -> None:
    manifest = make_manifest(conditions=(Condition.ONMC_CURRENT, Condition.ONMC_CANDIDATE))
    with pytest.raises(ValueError):
        ExperimentRunner(manifest, ["t1"], FixtureAdapter(), baseline=Condition.BARE_AGENT)


def test_duplicate_task_ids_rejected() -> None:
    manifest = make_manifest()
    with pytest.raises(ValueError):
        ExperimentRunner(manifest, ["t1", "t1"], FixtureAdapter())
