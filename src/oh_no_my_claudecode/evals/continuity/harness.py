"""Continuity eval harness — runs both policies and returns a comparison.

Entry point: ``run_continuity(tasks)`` applies both the naive and ONMC
orchestrator policies to the same task sequence and returns a
:class:`~oh_no_my_claudecode.evals.continuity.models.ContinuityComparison`
with per-orchestrator metrics and a renderable markdown table.
"""

from __future__ import annotations

from oh_no_my_claudecode.evals.continuity.models import ContinuityComparison, ContinuityTask
from oh_no_my_claudecode.evals.continuity.orchestrators import run_naive, run_onmc


def run_continuity(tasks: list[ContinuityTask]) -> ContinuityComparison:
    """Run the continuity eval SIM over *tasks*.

    Applies both the naive and ONMC orchestrator policies to the same
    immutable task sequence and returns a side-by-side comparison.

    Parameters
    ----------
    tasks:
        Ordered sequence of :class:`ContinuityTask` items.  Order matters —
        the position of the ``broken`` task determines which subsequent tasks
        cascade-fail under the naive policy.

    Returns
    -------
    ContinuityComparison
        Contains per-orchestrator reports and delta properties.  Call
        ``.to_markdown()`` to render a human-readable table, or
        ``.to_dict()`` for JSON output.
    """
    naive_report = run_naive(tasks)
    onmc_report = run_onmc(tasks)
    return ContinuityComparison(naive=naive_report, onmc=onmc_report)
