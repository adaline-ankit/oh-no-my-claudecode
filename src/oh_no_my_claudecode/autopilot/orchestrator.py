"""Autopilot orchestrator: KNOW→ACT→PROVE→LEARN in one verb.

Architecture
-----------
run_autopilot() wraps the existing loop (service.loop) with:

  KNOW  — snapshot brain_before; compile_brief + guard + user_profile into context.
  ACT   — if dry_run → return early; else call service.loop().
  PROVE — read verified/tokens/cost from loop_result + receipt.
  LEARN — on WIN: add_memory + skill_promote (best-effort) + consolidate (best-effort).
          on LOSS: loop already recorded FAILED_APPROACH dead-ends automatically.
          Always: snapshot brain_after; compute delta.

All LEARN steps are individually exception-safe — a LEARN failure never fails the run.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import TYPE_CHECKING

from oh_no_my_claudecode.autopilot.models import AutopilotResult, BrainCounts

if TYPE_CHECKING:
    from oh_no_my_claudecode.core.service import OnmcService
    from oh_no_my_claudecode.loop.models import AgentRunner, LoopResult, VerifyRunner


def _snap_brain(service: OnmcService) -> BrainCounts:
    """Snapshot current brain counts; return zeros on any error."""
    try:
        _, _, storage = service._load_context()  # noqa: SLF001
        memories = storage.list_memories()
        skills = storage.list_skills()
        dead_ends = sum(
            1 for m in memories if m.kind.value == "failed_approach"
        )
        return BrainCounts(
            memories=len(memories),
            skills=len(skills),
            dead_ends=dead_ends,
        )
    except Exception:  # noqa: BLE001
        return BrainCounts(memories=0, skills=0, dead_ends=0)


def _build_know_context(
    service: OnmcService,
    goal: str,
) -> tuple[str, str, int, bool]:
    """Run the KNOW phase: brief + guard + profile.

    Returns
    -------
    tuple[context_text, brief_summary, dead_ends_count, profile_applied]
    """
    parts: list[str] = []
    brief_summary = ""
    dead_ends_count = 0
    profile_applied = False

    # 1. compile_brief — rich task context
    with contextlib.suppress(Exception):
        _, artifact = service.compile_brief(goal)
        brief_md = artifact.to_markdown()
        if brief_md:
            parts.append(brief_md)
        # Extract a one-line summary from the task field or first line.
        brief_summary = (artifact.task or goal)[:120]

    # 2. guard — surface recorded dead-ends
    with contextlib.suppress(Exception):
        _, guard_result = service.guard(goal)
        dead_ends_count = len(guard_result.entries)
        if guard_result.has_dead_ends:
            parts.append(guard_result.to_markdown())

    # 3. user_profile — inject preferences / known mistakes
    with contextlib.suppress(Exception):
        profile = service.user_profile()
        if not profile.is_empty:
            profile_applied = True
            pref_lines: list[str] = []
            for _title, summary in profile.preferences[:3]:
                pref_lines.append(f"- {summary}")
            for _title, summary in profile.frequent_mistakes[:3]:
                pref_lines.append(f"- AVOID: {summary}")
            if pref_lines:
                parts.append("## User profile\n\n" + "\n".join(pref_lines))

    context_text = "\n\n".join(parts)
    return context_text, brief_summary, dead_ends_count, profile_applied


def _run_learn(
    service: OnmcService,
    goal: str,
    loop_result: LoopResult,
) -> tuple[str | None, int, int]:
    """Run the LEARN phase after a real (non-dry-run) loop.

    On WIN: capture a memory + attempt skill_promote + consolidate.
    On LOSS: loop already recorded FAILED_APPROACH dead-ends automatically;
             we just snapshot for delta counting.

    All operations are individually exception-safe.

    Returns
    -------
    tuple[skill_promoted_name | None, captured_count, consolidated_count]
    """
    skill_promoted_name: str | None = None
    captured_count: int = 0
    consolidated_count: int = 0

    if loop_result.converged:
        # WIN path — record the successful approach, promote skill, consolidate.
        with contextlib.suppress(Exception):
            last_contract = loop_result.iterations[-1]
            action_text = last_contract.action_summary if loop_result.iterations else ""
            service.add_memory(
                kind="decision",
                title=f"Autopilot win: {goal[:80]}",
                summary=(
                    f"Autopilot converged on goal: {goal[:200]}. "
                    f"Winning action: {action_text[:300]}."
                ),
                source_type="session",
                source_ref="autopilot:engine",
                confidence=0.85,
            )
            captured_count = 1

        with contextlib.suppress(Exception):
            new_skills = service.skill_promote(auto=True)
            if new_skills:
                first = new_skills[0]
                skill_promoted_name = getattr(first, "name", None) or getattr(
                    first, "id", None
                )

        with contextlib.suppress(Exception):
            _, consol_result = service.consolidate(dry_run=False)
            consolidated_count = getattr(consol_result, "merged", 0) + getattr(
                consol_result, "promoted", 0
            )

    return skill_promoted_name, captured_count, consolidated_count


def run_autopilot(
    service: OnmcService,
    goal: str,
    *,
    agent: str = "claude",
    dry_run: bool = False,
    max_iterations: int = 10,
    budget_tokens: int | None = None,
    max_cost_usd: float | None = None,
    max_wall_seconds: int | None = None,
    verify_command: str = "pytest",
    agent_runner: AgentRunner | None = None,
    verify_runner: VerifyRunner | None = None,
    now: datetime | None = None,  # injectable for tests
) -> AutopilotResult:
    """Run the full KNOW→ACT→PROVE→LEARN autopilot cycle.

    Parameters
    ----------
    service:
        Initialised :class:`~oh_no_my_claudecode.core.service.OnmcService`.
    goal:
        The task/goal to work on.
    agent:
        Which CLI agent to use (``"claude"`` or ``"codex"``).  Ignored when
        *dry_run* is True or *agent_runner* is injected.
    dry_run:
        When True, only run KNOW (compute context) and return without invoking
        any agent or verify subprocess.  No memory writes, no cost.
    max_iterations, budget_tokens, max_cost_usd, max_wall_seconds, verify_command:
        Forwarded to :meth:`~oh_no_my_claudecode.core.service.OnmcService.loop`.
    agent_runner:
        Optional injectable :class:`~oh_no_my_claudecode.loop.models.AgentRunner`
        for testing.  When ``None``, the real CLI runner is built from *agent*.
    verify_runner:
        Optional injectable :class:`~oh_no_my_claudecode.loop.models.VerifyRunner`
        for testing.
    now:
        Injectable reference timestamp (unused currently; reserved for deterministic
        testing of time-dependent logic).

    Returns
    -------
    AutopilotResult
        Full structured result including brain delta and LEARN outcomes.
    """
    del now  # reserved; not currently used in this layer

    # ── KNOW ──────────────────────────────────────────────────────────────────
    brain_before = _snap_brain(service)
    know_context, brief_summary, dead_ends_count, profile_applied = _build_know_context(
        service, goal
    )

    if dry_run:
        # No ACT, no LEARN — return early with KNOW context only.
        return AutopilotResult(
            goal=goal,
            know_brief_summary=brief_summary,
            know_dead_ends_count=dead_ends_count,
            know_profile_applied=profile_applied,
            loop_result=_dry_run_loop_result(goal, know_context),
            receipt_path=None,
            verified=False,
            tokens=0,
            cost_usd=None,
            brain_before=brain_before,
            brain_after=brain_before,  # no change in dry-run
            memories_added=0,
            skills_added=0,
            dead_ends_recorded=0,
            skill_promoted_name=None,
            captured_count=0,
            consolidated_count=0,
            stop_reason="dry-run",
            know_context=know_context,
        )

    # ── ACT ───────────────────────────────────────────────────────────────────
    loop_result, receipt_path = service.loop(
        goal,
        agent=agent,
        max_iterations=max_iterations,
        budget_tokens=budget_tokens,
        verify_command=verify_command,
        dry_run=False,
        max_cost_usd=max_cost_usd,
        max_wall_seconds=max_wall_seconds,
        agent_runner=agent_runner,
        verify_runner=verify_runner,
    )

    # ── PROVE ─────────────────────────────────────────────────────────────────
    verified = loop_result.converged and bool(
        loop_result.iterations and loop_result.iterations[-1].verify_passed
    )
    tokens = loop_result.total_tokens
    cost_usd = loop_result.total_cost_usd

    # Count dead-ends recorded by the loop (LOSS iterations each write one).
    dead_ends_recorded = sum(
        1 for c in loop_result.iterations if c.outcome == "loss" and c.iteration > 0
    )

    # ── LEARN ─────────────────────────────────────────────────────────────────
    brain_mid = _snap_brain(service)  # after loop wrote its own memories
    skill_promoted_name, captured_count, consolidated_count = _run_learn(
        service, goal, loop_result
    )
    brain_after = _snap_brain(service)

    memories_added = max(0, brain_after.memories - brain_before.memories)
    skills_added = max(0, brain_after.skills - brain_before.skills)
    del brain_mid  # used only to detect loop-written memories vs LEARN-written

    return AutopilotResult(
        goal=goal,
        know_brief_summary=brief_summary,
        know_dead_ends_count=dead_ends_count,
        know_profile_applied=profile_applied,
        loop_result=loop_result,
        receipt_path=receipt_path,
        verified=verified,
        tokens=tokens,
        cost_usd=cost_usd,
        brain_before=brain_before,
        brain_after=brain_after,
        memories_added=memories_added,
        skills_added=skills_added,
        dead_ends_recorded=dead_ends_recorded,
        skill_promoted_name=skill_promoted_name,
        captured_count=captured_count,
        consolidated_count=consolidated_count,
        stop_reason=loop_result.stop_reason,
        know_context=know_context,
    )


def _dry_run_loop_result(goal: str, know_context: str) -> object:
    """Build a minimal LoopResult stub for a dry-run autopilot."""
    from oh_no_my_claudecode.loop.models import IterationContract, LoopResult

    dry_contract = IterationContract(
        iteration=0,
        prediction="[dry-run: no agent invoked]",
        action_summary=(
            f"## Goal\n\n{goal}\n\n## KNOW context\n\n{know_context or '(empty)'}"
        ),
        files_touched=[],
        verify_passed=False,
        verify_output="[dry-run: no verify invoked]",
        outcome="loss",
        tokens=None,
    )
    return LoopResult(
        iterations=[dry_contract],
        converged=False,
        stop_reason="dry-run",
        recorded_memory_ids=[],
        total_tokens=0,
    )
