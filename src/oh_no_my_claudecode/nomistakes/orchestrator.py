"""No-Mistakes gate: deterministic preflight + accountable autopilot.

This layer does not create a second agent runtime. It composes the existing
audit, eval, autopilot, verifier, receipt, circuit-breaker, and isolation
primitives into one PR-ready gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from oh_no_my_claudecode.audit.scanner import AuditSeverity
from oh_no_my_claudecode.autopilot.models import AutopilotResult
from oh_no_my_claudecode.nomistakes.models import (
    AutonomyLevel,
    GateCheck,
    NoMistakesResult,
)

if TYPE_CHECKING:
    from oh_no_my_claudecode.core.service import OnmcService
    from oh_no_my_claudecode.loop.models import AgentRunner, ChangeProbe, VerifyRunner

_AUDIT_ORDER: list[AuditSeverity] = ["critical", "high", "medium", "low", "info"]
_AUTONOMY_LEVELS: set[str] = {"L0", "L1", "L2", "L3", "L4"}


def run_nomistakes(
    service: OnmcService,
    goal: str,
    *,
    agent: str = "claude",
    autonomy: AutonomyLevel = "L2",
    dry_run: bool = False,
    max_iterations: int = 6,
    budget_tokens: int | None = 80_000,
    max_cost_usd: float | None = 3.0,
    max_wall_seconds: int | None = 900,
    verify_command: str = "pytest",
    audit_fail_on: AuditSeverity = "high",
    eval_fail_under: float | None = None,
    plan_model: str | None = None,
    execute_model: str | None = None,
    isolate: bool = True,
    agent_runner: AgentRunner | None = None,
    verify_runner: VerifyRunner | None = None,
    plan_runner: AgentRunner | None = None,
    change_probe: ChangeProbe | None = None,
) -> NoMistakesResult:
    """Run a PR-ready No-Mistakes gate.

    L0/L1 are observe/advice modes and never invoke the agent. L2+ can act.
    Approval requires no blocking preflight gates and a verified autopilot
    receipt. Dry-runs never approve because no verifier ran.
    """
    if autonomy not in _AUTONOMY_LEVELS:
        msg = f"Unknown autonomy {autonomy!r}. Choose L0, L1, L2, L3, or L4."
        raise ValueError(msg)

    gates: list[GateCheck] = []

    audit_report = service.audit()
    audit_blockers = audit_report.findings_at_or_above(audit_fail_on)
    gates.append(
        GateCheck(
            name="audit",
            status="fail" if audit_blockers else "pass",
            detail=(
                f"{len(audit_blockers)} finding(s) at or above {audit_fail_on}; "
                f"grade {audit_report.grade}, score {audit_report.score}/100"
            ),
            blocking=bool(audit_blockers),
        )
    )

    if eval_fail_under is not None:
        _, eval_report = service.eval_run(with_memory=True)
        if eval_report.total_cases == 0:
            gates.append(
                GateCheck(
                    name="eval",
                    status="skip",
                    detail="no eval cases configured",
                    blocking=False,
                )
            )
        else:
            eval_blocking = eval_report.score < eval_fail_under
            gates.append(
                GateCheck(
                    name="eval",
                    status="fail" if eval_blocking else "pass",
                    detail=(
                        f"score {eval_report.score:.2f}/100 "
                        f"({eval_report.passed_cases}/{eval_report.total_cases} cases)"
                    ),
                    blocking=eval_blocking,
                )
            )
    else:
        gates.append(
            GateCheck(
                name="eval",
                status="skip",
                detail="no --eval-fail-under threshold set",
                blocking=False,
            )
        )

    act_dry_run = dry_run or autonomy in {"L0", "L1"}
    act_goal = _gate_goal(goal, autonomy=autonomy, verify_command=verify_command)
    autopilot_result = service.autopilot(
        act_goal,
        agent=agent,
        dry_run=act_dry_run,
        max_iterations=max_iterations,
        budget_tokens=budget_tokens,
        max_cost_usd=max_cost_usd,
        max_wall_seconds=max_wall_seconds,
        verify_command=verify_command,
        agent_runner=agent_runner,
        verify_runner=verify_runner,
        plan_model=plan_model,
        execute_model=execute_model,
        plan_runner=plan_runner,
        isolate=isolate,
        change_probe=change_probe,
    )
    verified = isinstance(autopilot_result, AutopilotResult) and autopilot_result.verified
    gates.append(
        GateCheck(
            name="receipt",
            status="pass" if verified else "fail",
            detail=(
                "verified receipt"
                if verified
                else f"not verified ({getattr(autopilot_result, 'stop_reason', 'unknown')})"
            ),
            blocking=not verified,
        )
    )

    blockers = [gate for gate in gates if gate.blocking]
    approved = not blockers and not act_dry_run
    receipt = getattr(autopilot_result, "receipt_path", None)
    return NoMistakesResult(
        goal=goal,
        autonomy=autonomy,
        approved=approved,
        dry_run=act_dry_run,
        agent=agent,
        verify_command=verify_command,
        gates=gates,
        autopilot_result=autopilot_result,
        receipt_path=str(receipt) if receipt else None,
    )


def _gate_goal(goal: str, *, autonomy: str, verify_command: str) -> str:
    return (
        "No-Mistakes PR gate.\n\n"
        f"Goal: {goal}\n\n"
        "Rules:\n"
        "- Make the smallest correct change.\n"
        "- Use repository memory and avoid recorded dead-ends.\n"
        "- Keep public behavior stable unless goal requires otherwise.\n"
        f"- Pass verifier exactly: {verify_command}\n"
        "- Treat model claims as untrusted until verifier passes.\n"
        "- Leave evidence in the ONMC receipt.\n\n"
        f"Autonomy: {autonomy}"
    )
