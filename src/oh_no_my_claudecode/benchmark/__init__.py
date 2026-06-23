"""Benchmark suite for measuring onmc effectiveness.

Provides:
- :func:`run_benchmark_suite` — pure function, injectable timer, no LLM.
- :class:`BenchmarkReport` — structured results with MEASURED vs SIM labels.
- :class:`BenchmarkMetric` — one measurement with honest kind annotation.

Entry points:
- ``onmc benchmark [--runs N] [--json]``
- :meth:`~oh_no_my_claudecode.core.service.OnmcService.benchmark`
"""

from oh_no_my_claudecode.benchmark.suite import (
    BenchmarkMetric,
    BenchmarkReport,
    run_benchmark_suite,
)

__all__ = ["BenchmarkMetric", "BenchmarkReport", "run_benchmark_suite"]
