"""onmc quickstart — zero-config onboarding in one command.

Composes ``onmc init``, ``onmc plug claude-code``, and ``onmc wrap
--default-active`` into a single idempotent flow.  Safe to re-run.
"""

from __future__ import annotations

from oh_no_my_claudecode.quickstart.flow import (
    DAY1_COMMANDS,
    QuickstartResult,
    StepResult,
    StepSpec,
    plan_quickstart,
    run_quickstart,
)

__all__ = [
    "DAY1_COMMANDS",
    "QuickstartResult",
    "StepResult",
    "StepSpec",
    "plan_quickstart",
    "run_quickstart",
]
