"""Dependency-free statistics for the experiment kernel.

Every function here is a pure, deterministic transform over plain numbers — no
numpy, no global RNG. Randomness (the bootstrap resampler) is fully seeded via
:class:`random.Random`, so the same inputs and seed always yield byte-identical
output. This is what lets an :class:`~.kernel.ExperimentReport` be reproducible
and content-addressable.

The vocabulary intentionally mirrors what an honest comparison needs:

- point estimates (``mean``, ``median``) and dispersion (``variance``),
- a seeded percentile ``bootstrap_ci`` for uncertainty on nondeterministic
  comparisons (blueprint truth rule 5), and
- ``paired_deltas`` for the per-task, baseline-vs-treatment differences that are
  the whole point of a paired experiment.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Mapping, Sequence

__all__ = [
    "bootstrap_ci",
    "derive_seed",
    "mean",
    "median",
    "paired_deltas",
    "percentile",
    "variance",
]


def mean(samples: Sequence[float]) -> float:
    """Arithmetic mean. Raises ``ValueError`` on an empty sample."""
    data = list(samples)
    if not data:
        raise ValueError("mean requires at least one sample")
    return math.fsum(data) / len(data)


def median(samples: Sequence[float]) -> float:
    """Middle value (mean of the two middle values for even counts)."""
    data = sorted(samples)
    n = len(data)
    if n == 0:
        raise ValueError("median requires at least one sample")
    mid = n // 2
    if n % 2 == 1:
        return float(data[mid])
    return (data[mid - 1] + data[mid]) / 2.0


def variance(samples: Sequence[float]) -> float:
    """Unbiased (Bessel-corrected, ddof=1) sample variance.

    Returns ``0.0`` for a single sample — a degenerate but well-defined case
    that callers hit on one-trial experiments.
    """
    data = list(samples)
    n = len(data)
    if n == 0:
        raise ValueError("variance requires at least one sample")
    if n == 1:
        return 0.0
    m = mean(data)
    return math.fsum((x - m) ** 2 for x in data) / (n - 1)


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted sequence.

    ``q`` is in ``[0, 100]``. Matches the common "linear" interpolation method
    so CI bounds are stable and explainable.
    """
    if not sorted_values:
        raise ValueError("percentile requires at least one value")
    if not 0.0 <= q <= 100.0:
        raise ValueError("q must be in [0, 100]")
    n = len(sorted_values)
    if n == 1:
        return float(sorted_values[0])
    rank = (q / 100.0) * (n - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(sorted_values[low])
    frac = rank - low
    return sorted_values[low] * (1.0 - frac) + sorted_values[high] * frac


def bootstrap_ci(
    samples: Sequence[float],
    *,
    seed: int,
    iterations: int = 1000,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Seeded percentile bootstrap confidence interval for the mean.

    Resamples ``samples`` with replacement ``iterations`` times, takes the mean
    of each resample, and returns the ``(alpha/2, 1 - alpha/2)`` percentiles of
    that distribution. Deterministic for a fixed ``seed``.

    A single-sample input collapses to ``(x, x)`` — honest: there is no spread
    to estimate from one observation.
    """
    data = list(samples)
    if not data:
        raise ValueError("bootstrap_ci requires at least one sample")
    if iterations < 1:
        raise ValueError("iterations must be a positive integer")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    n = len(data)
    if n == 1:
        return (data[0], data[0])
    rng = random.Random(seed)  # noqa: S311 - statistical resampling, not crypto
    resample_means: list[float] = []
    for _ in range(iterations):
        total = 0.0
        for _ in range(n):
            total += data[rng.randrange(n)]
        resample_means.append(total / n)
    resample_means.sort()
    low = percentile(resample_means, (alpha / 2.0) * 100.0)
    high = percentile(resample_means, (1.0 - alpha / 2.0) * 100.0)
    return (low, high)


def paired_deltas(
    baseline: Mapping[str, float],
    treatment: Mapping[str, float],
) -> dict[str, float]:
    """Per-key ``treatment - baseline`` over the keys present in both maps.

    Keys are intersected (an unpaired task contributes no delta) and the result
    is ordered by sorted key so the aggregation is deterministic.
    """
    shared = sorted(set(baseline) & set(treatment))
    return {key: treatment[key] - baseline[key] for key in shared}


def derive_seed(base: int, *parts: str) -> int:
    """Deterministically fold a base seed and string parts into a 64-bit seed.

    Used to give every (condition, metric) bootstrap its own stable stream so
    reports are reproducible without any shared mutable RNG state.
    """
    hasher = hashlib.sha256(str(int(base)).encode("utf-8"))
    for part in parts:
        hasher.update(b"\x00")
        hasher.update(part.encode("utf-8"))
    return int.from_bytes(hasher.digest()[:8], "big")
