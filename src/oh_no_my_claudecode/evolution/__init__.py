"""Evolution compiler — compounding-proof feature for onmc.

Reads the run-receipt chain written by ``onmc loop`` / ``onmc autopilot``
and proves the agent gets cheaper / smarter across runs.

Entry points:
- ``onmc evolution [--json]``
- :meth:`~oh_no_my_claudecode.core.service.OnmcService.evolution`
"""

from __future__ import annotations

from oh_no_my_claudecode.evolution.compiler import (
    EvolutionReport,
    RunPoint,
    compile_evolution,
)

__all__ = ["EvolutionReport", "RunPoint", "compile_evolution"]
