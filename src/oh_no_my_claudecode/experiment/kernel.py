"""The experiment kernel — turn a frozen manifest into a reproducible report.

The kernel is deliberately ignorant of *how* a trial runs. It only knows how to
enumerate the ``condition x task x trial`` grid described by an
:class:`~.contracts.ExperimentManifest`, execute each cell through an injected
:class:`TrialAdapter`, and aggregate the paired :class:`~.contracts.TrialResult`
outcomes into a typed, JSON-serialisable :class:`ExperimentReport`.

Design commitments (blueprint truth rules):

- **Real control, real adapter.** The kernel never fabricates an outcome; it
  drives whatever adapter is injected and nothing else. ``BARE_AGENT`` is a
  genuine arm supplied by the caller, not a simulated empty condition.
- **Seeded everything.** Execution order is a seeded shuffle of the grid and
  every bootstrap CI draws from a seed derived from the manifest seed, so the
  same inputs produce byte-identical report JSON.
- **Labelled numbers.** Every aggregate carries a :class:`~.contracts.MetricLabel`
  (``measured`` only when *every* contributing trial was measured).
- **Honest uncertainty.** Multi-trial comparisons report bootstrap CIs;
  degenerate one-sample cases collapse to a point instead of inventing spread.

The kernel does not touch the network, a subprocess, or the filesystem — those
belong to concrete adapters. :class:`FixtureAdapter` is the in-process,
deterministic adapter used by the tests.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from . import stats
from .contracts import (
    Condition,
    ExperimentManifest,
    MetricLabel,
    RunId,
    TrialResult,
)

__all__ = [
    "ConditionAggregate",
    "ExperimentReport",
    "ExperimentRunner",
    "FixtureAdapter",
    "MetricSummary",
    "TaskDelta",
    "TrialAdapter",
]

#: Numeric per-trial metrics the kernel summarises, in stable report order.
#: Each entry maps a report key to the ``TrialResult`` attribute it reads.
_METRICS: tuple[tuple[str, str], ...] = (
    ("cost_usd", "cost_usd"),
    ("latency_ms", "latency_ms"),
    ("turns", "turns"),
    ("context_tokens", "context_tokens"),
)

_BOOTSTRAP_ITERATIONS = 1000
_BOOTSTRAP_ALPHA = 0.05


@runtime_checkable
class TrialAdapter(Protocol):
    """The one thing the kernel needs from the outside world.

    An adapter turns a :class:`~.contracts.RunId` into a verified
    :class:`~.contracts.TrialResult`. Implementations may shell out to a real
    coding agent, replay a recording, or (in tests) compute deterministically —
    the kernel does not care, and must never assume.
    """

    def run(self, run_id: RunId) -> TrialResult: ...


def _metric_value(result: TrialResult, attr: str) -> float:
    return float(getattr(result, attr))


def _combine_labels(results: Sequence[TrialResult]) -> MetricLabel:
    """Measured only if every contributing trial was measured."""
    if results and all(r.metric_label is MetricLabel.MEASURED for r in results):
        return MetricLabel.MEASURED
    return MetricLabel.ESTIMATED


@dataclass(frozen=True, slots=True)
class MetricSummary:
    """Point estimate + median + bootstrap CI for one numeric metric."""

    metric: str
    label: MetricLabel
    n: int
    mean: float
    median: float
    ci_low: float
    ci_high: float

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "label": self.label.value,
            "n": self.n,
            "mean": self.mean,
            "median": self.median,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
        }


@dataclass(frozen=True, slots=True)
class ConditionAggregate:
    """Everything the report says about a single condition arm."""

    condition: Condition
    label: MetricLabel
    trials: int
    pass_at_1: float
    metrics: tuple[MetricSummary, ...]

    def metric(self, name: str) -> MetricSummary:
        for summary in self.metrics:
            if summary.metric == name:
                return summary
        raise KeyError(name)

    def to_dict(self) -> dict[str, object]:
        return {
            "condition": self.condition.value,
            "label": self.label.value,
            "trials": self.trials,
            "pass_at_1": self.pass_at_1,
            "metrics": [m.to_dict() for m in self.metrics],
        }


@dataclass(frozen=True, slots=True)
class TaskDelta:
    """Paired ``treatment - baseline`` differences for one task."""

    task_id: str
    condition: Condition
    label: MetricLabel
    pass_delta: float
    metric_deltas: tuple[tuple[str, float], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "condition": self.condition.value,
            "label": self.label.value,
            "pass_delta": self.pass_delta,
            "metric_deltas": dict(self.metric_deltas),
        }


@dataclass(frozen=True, slots=True)
class ExperimentReport:
    """The typed, deterministic outcome of one experiment run."""

    experiment_id: str
    baseline: Condition
    task_ids: tuple[str, ...]
    conditions: tuple[ConditionAggregate, ...]
    task_deltas: tuple[TaskDelta, ...]
    manifest: Mapping[str, object]

    def condition(self, condition: Condition) -> ConditionAggregate:
        for aggregate in self.conditions:
            if aggregate.condition is condition:
                return aggregate
        raise KeyError(condition)

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "baseline": self.baseline.value,
            "task_ids": list(self.task_ids),
            "conditions": [c.to_dict() for c in self.conditions],
            "task_deltas": [d.to_dict() for d in self.task_deltas],
            "manifest": dict(self.manifest),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )


class ExperimentRunner:
    """Drive a manifest + task set through an adapter into a report."""

    def __init__(
        self,
        manifest: ExperimentManifest,
        task_ids: Sequence[str],
        adapter: TrialAdapter,
        *,
        baseline: Condition = Condition.BARE_AGENT,
    ) -> None:
        if baseline not in manifest.conditions:
            raise ValueError("baseline condition must be one of the manifest conditions")
        deduped = list(dict.fromkeys(task_ids))
        if len(deduped) != len(list(task_ids)):
            raise ValueError("task_ids must be unique")
        self._manifest = manifest
        self._task_ids: tuple[str, ...] = tuple(deduped)
        self._adapter = adapter
        self._baseline = baseline

    @property
    def manifest(self) -> ExperimentManifest:
        return self._manifest

    def _grid(self) -> list[RunId]:
        """Canonical (unshuffled) enumeration of every cell to execute."""
        cells: list[RunId] = []
        for condition in self._manifest.conditions:
            for task_id in self._task_ids:
                for trial in range(self._manifest.trials):
                    cells.append(
                        RunId(
                            experiment_id=self._manifest.experiment_id.value,
                            condition=condition,
                            task_id=task_id,
                            trial=trial,
                        )
                    )
        return cells

    def plan(self) -> list[RunId]:
        """Seeded randomized execution order — stable for a fixed manifest seed.

        The grid is built in a canonical order first, then shuffled with a
        dedicated ``Random(seed)`` so ordering never depends on dict/iteration
        quirks and two runners with the same seed execute identically.
        """
        cells = self._grid()
        rng = random.Random(  # noqa: S311 - seeded ordering, not crypto
            stats.derive_seed(self._manifest.seed, "execution-order")
        )
        rng.shuffle(cells)
        return cells

    def run(self) -> ExperimentReport:
        results = [self._adapter.run(run_id) for run_id in self.plan()]
        return self._aggregate(results)

    def _summarize(
        self, metric: str, values: Sequence[float], label: MetricLabel, seed_parts: Sequence[str]
    ) -> MetricSummary:
        if not values:
            return MetricSummary(metric, label, 0, 0.0, 0.0, 0.0, 0.0)
        seed = stats.derive_seed(self._manifest.seed, metric, *seed_parts)
        low, high = stats.bootstrap_ci(
            values, seed=seed, iterations=_BOOTSTRAP_ITERATIONS, alpha=_BOOTSTRAP_ALPHA
        )
        return MetricSummary(
            metric=metric,
            label=label,
            n=len(values),
            mean=stats.mean(values),
            median=stats.median(values),
            ci_low=low,
            ci_high=high,
        )

    def _aggregate(self, results: Sequence[TrialResult]) -> ExperimentReport:
        by_condition: dict[Condition, list[TrialResult]] = {
            c: [] for c in self._manifest.conditions
        }
        for result in results:
            by_condition[result.run_id.condition].append(result)

        aggregates = tuple(
            self._aggregate_condition(condition, by_condition[condition])
            for condition in self._manifest.conditions
        )
        task_deltas = self._task_deltas(by_condition)
        return ExperimentReport(
            experiment_id=self._manifest.experiment_id.value,
            baseline=self._baseline,
            task_ids=self._task_ids,
            conditions=aggregates,
            task_deltas=task_deltas,
            manifest=self._manifest.to_dict(),
        )

    def _aggregate_condition(
        self, condition: Condition, results: Sequence[TrialResult]
    ) -> ConditionAggregate:
        label = _combine_labels(results)
        pass_values = [1.0 if r.passed else 0.0 for r in results]
        pass_at_1 = stats.mean(pass_values) if pass_values else 0.0
        summaries = tuple(
            self._summarize(
                key,
                [_metric_value(r, attr) for r in results],
                label,
                (condition.value,),
            )
            for key, attr in _METRICS
        )
        return ConditionAggregate(
            condition=condition,
            label=label,
            trials=len(results),
            pass_at_1=pass_at_1,
            metrics=summaries,
        )

    def _per_task_means(
        self, results: Sequence[TrialResult]
    ) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
        """Collapse each task's trials to a single mean per metric (and pass)."""
        pass_by_task: dict[str, list[float]] = {}
        metric_by_task: dict[str, dict[str, list[float]]] = {}
        for result in results:
            task = result.run_id.task_id
            pass_by_task.setdefault(task, []).append(1.0 if result.passed else 0.0)
            bucket = metric_by_task.setdefault(task, {key: [] for key, _ in _METRICS})
            for key, attr in _METRICS:
                bucket[key].append(_metric_value(result, attr))
        pass_means = {task: stats.mean(vals) for task, vals in pass_by_task.items()}
        metric_means = {
            task: {key: stats.mean(vals) for key, vals in buckets.items()}
            for task, buckets in metric_by_task.items()
        }
        return pass_means, metric_means

    def _task_deltas(
        self, by_condition: Mapping[Condition, Sequence[TrialResult]]
    ) -> tuple[TaskDelta, ...]:
        base_pass, base_metrics = self._per_task_means(by_condition[self._baseline])
        base_label = _combine_labels(list(by_condition[self._baseline]))
        deltas: list[TaskDelta] = []
        for condition in self._manifest.conditions:
            if condition is self._baseline:
                continue
            treat_pass, treat_metrics = self._per_task_means(by_condition[condition])
            label = (
                MetricLabel.MEASURED
                if base_label is MetricLabel.MEASURED
                and _combine_labels(list(by_condition[condition])) is MetricLabel.MEASURED
                else MetricLabel.ESTIMATED
            )
            pass_deltas = stats.paired_deltas(base_pass, treat_pass)
            for task_id in self._task_ids:
                if task_id not in pass_deltas:
                    continue
                metric_deltas = tuple(
                    (key, treat_metrics[task_id][key] - base_metrics[task_id][key])
                    for key, _ in _METRICS
                )
                deltas.append(
                    TaskDelta(
                        task_id=task_id,
                        condition=condition,
                        label=label,
                        pass_delta=pass_deltas[task_id],
                        metric_deltas=metric_deltas,
                    )
                )
        return tuple(deltas)


@dataclass(frozen=True, slots=True)
class FixtureAdapter:
    """Deterministic, in-process adapter for tests — no subprocess, no network.

    Every field of the emitted :class:`~.contracts.TrialResult` is a pure
    function of the ``RunId`` and this adapter's ``seed``, so a run is fully
    reproducible. ``pass_bias`` sets each condition's pass probability (default
    ``0.5``); a bias of ``1.0`` always passes and ``0.0`` never does, which lets
    a test pin an exact, known pass@1. ``cost_scale`` shifts a condition's
    metric magnitudes so paired deltas are non-trivial.
    """

    seed: int = 0
    pass_bias: Mapping[Condition, float] = field(default_factory=dict)
    cost_scale: Mapping[Condition, float] = field(default_factory=dict)
    metric_label: MetricLabel = MetricLabel.MEASURED

    def _unit(self, run_id: RunId, salt: str) -> float:
        """A deterministic pseudo-uniform draw in ``[0, 1)`` for this cell."""
        rng = random.Random(  # noqa: S311 - deterministic fixture draw, not crypto
            stats.derive_seed(self.seed, salt, run_id.slug)
        )
        return rng.random()

    def run(self, run_id: RunId) -> TrialResult:
        bias = self.pass_bias.get(run_id.condition, 0.5)
        scale = self.cost_scale.get(run_id.condition, 1.0)
        passed = self._unit(run_id, "pass") < bias
        cost = round(scale * (0.10 + self._unit(run_id, "cost")), 6)
        latency = round(scale * (100.0 + 900.0 * self._unit(run_id, "latency")), 3)
        turns = 1 + int(self._unit(run_id, "turns") * 10)
        tokens = 500 + int(self._unit(run_id, "tokens") * 5000)
        return TrialResult(
            run_id=run_id,
            passed=passed,
            metric_label=self.metric_label,
            cost_usd=cost,
            latency_ms=latency,
            turns=turns,
            tool_calls=turns,
            context_tokens=tokens,
        )
