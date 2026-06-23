"""Memory evaluation and regression-gate harness for onmc.

Provides deterministic, offline measurement of how much the brain actually
helps — precision@k on recall, dead-end avoidance on guard — with a
with-memory vs without-memory delta and a ``--fail-under`` / ``--baseline``
CI regression gate.
"""

from __future__ import annotations

from oh_no_my_claudecode.evals.models import (
    EvalCase,
    EvalCaseResult,
    EvalComparison,
    EvalReport,
)

__all__ = [
    "EvalCase",
    "EvalCaseResult",
    "EvalComparison",
    "EvalReport",
]
