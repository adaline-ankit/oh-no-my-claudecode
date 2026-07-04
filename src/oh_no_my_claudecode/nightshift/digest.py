"""Morning digest rendering for a nightshift run.

Reuses the digest feature's rendering conventions (a Rich console with a plain
markdown-ish body, section headers, and graceful empty-state placeholders — see
:mod:`oh_no_my_claudecode.digest`).  Two shapes render through one entry point:

- A :class:`~oh_no_my_claudecode.nightshift.runner.NightshiftPlan` — the
  "here's what will run tonight" preview (used in dry-run).
- A :class:`~oh_no_my_claudecode.nightshift.runner.NightshiftSummary` — the
  "here's what actually shipped and verified" morning report.

``render_morning_digest`` is side-effect free apart from writing to the supplied
console, and its text is a deterministic function of its input, so it is trivial
to assert against a ``Console(file=StringIO, force_terminal=False)`` in tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from oh_no_my_claudecode.nightshift.runner import NightshiftPlan, NightshiftSummary

if TYPE_CHECKING:
    from rich.console import Console


def _build_console() -> Console:
    """Construct a default Rich console (lazy import keeps this module light)."""
    from rich.console import Console

    return Console()


def _render_plan_lines(plan: NightshiftPlan) -> list[str]:
    """The morning-report body for a *planned* (not-yet-run) nightshift."""
    lines = [
        "🌙 onmc nightshift — morning report (plan)",
        "",
        f"Planned: {plan.scheduled_count} unit(s)  "
        f"budget: {plan.budget}  "
        f"deferred: {plan.deferred_count}",
        "",
        "Units to run:",
    ]
    if plan.units:
        for unit in plan.units:
            lines.append(f"  {unit.index + 1}. {unit.goal}")
    else:
        lines.append("  (none — empty backlog)")
    if plan.deferred_count:
        lines.append("")
        lines.append(
            f"{plan.deferred_count} goal(s) deferred beyond the budget cap of {plan.budget}."
        )
    lines.append("")
    lines.append("No agents spawned (dry-run): drive the fan-out from this plan.")
    return lines


def _render_summary_lines(summary: NightshiftSummary) -> list[str]:
    """The morning-report body for a *completed* nightshift run."""
    lines = [
        "🌙 onmc nightshift — morning report",
        "",
        f"Shipped: {summary.total} unit(s)  "
        f"verified: {summary.verified}  "
        f"failed: {summary.failed}",
        "",
    ]
    if summary.total == 0:
        lines.append("Nothing ran overnight.")
        return lines

    lines.append("Results:")
    for row in summary.results:
        mark = "✓" if row.get("verified") else "✗"
        goal = row.get("goal") or "(unknown)"
        pr_url = row.get("pr_url")
        suffix = f"  → {pr_url}" if pr_url else ""
        lines.append(f"  {mark} {goal}{suffix}")

    lines.append("")
    if summary.all_verified:
        lines.append("All units verified. Clean night. ✓")
    else:
        lines.append(f"{summary.failed} unit(s) did not verify — review before merging.")
    return lines


def render_morning_digest(
    plan_or_results: NightshiftPlan | NightshiftSummary,
    console: Console | None = None,
) -> None:
    """Render a nightshift morning report to *console*.

    Accepts either a :class:`NightshiftPlan` (preview of what would run) or a
    :class:`NightshiftSummary` (what actually verified).  When *console* is
    ``None`` a default Rich console is created.  Output is a deterministic
    function of the input.
    """
    out = console if console is not None else _build_console()
    if isinstance(plan_or_results, NightshiftSummary):
        lines = _render_summary_lines(plan_or_results)
    else:
        lines = _render_plan_lines(plan_or_results)
    for line in lines:
        out.print(line)
