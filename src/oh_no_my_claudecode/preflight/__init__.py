"""Run the exact CI quality gate locally.

This package mirrors the steps in ``.github/workflows/ci.yml`` so any agent
or human can validate a change the same way CI will — before pushing.

The core is deterministic and side-effect free: :func:`run_preflight` takes an
injectable ``executor`` callable so callers (and tests) can run the gate
offline without spawning real subprocesses.
"""

from __future__ import annotations

from oh_no_my_claudecode.preflight.runner import (
    PREFLIGHT_STEPS,
    ExactReport,
    Executor,
    FixStep,
    PreflightReport,
    StepResult,
    run_preflight,
    run_preflight_exact,
    run_preflight_fix,
)

__all__ = [
    "PREFLIGHT_STEPS",
    "Executor",
    "ExactReport",
    "FixStep",
    "PreflightReport",
    "StepResult",
    "run_preflight",
    "run_preflight_exact",
    "run_preflight_fix",
]
