"""Autopilot orchestrator: KNOW→(PLAN)→ACT→PROVE→LEARN in one verb.

Architecture
-----------
run_autopilot() wraps the existing loop (service.loop) with:

  KNOW  — snapshot brain_before; compile_brief + guard + user_profile into context.
  PLAN  — optional; when plan_model is set, invoke the expensive model once with a
          planning prompt ("produce a step-by-step implementation plan precise enough
          that a cheaper model can execute it without re-deriving decisions").  The
          plan text is (a) injected into the ACT goal and (b) recorded as a DECISION
          memory tagged ``autopilot-plan``.  A plan failure is exception-safe: the run
          falls back to normal KNOW context and continues.
  ACT   — if dry_run → return early; else call service.loop() with execute_model
          (the cheap model) and the plan-augmented goal.
  PROVE — read verified/tokens/cost from loop_result + receipt.
  LEARN — on WIN: add_memory + skill_promote (best-effort) + consolidate (best-effort).
          on LOSS: loop already recorded FAILED_APPROACH dead-ends automatically.
          Always: snapshot brain_after; compute delta.

All LEARN steps are individually exception-safe — a LEARN failure never fails the run.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast

from oh_no_my_claudecode.autopilot.models import AutopilotResult, BrainCounts

if TYPE_CHECKING:
    from oh_no_my_claudecode.core.service import OnmcService
    from oh_no_my_claudecode.loop.models import (
        AgentRunner,
        AgentRunResult,
        LoopResult,
        VerifyRunner,
    )

#: Planning prompt template — instructs an expensive model to produce a precise plan.
_PLAN_PROMPT_TEMPLATE = (
    "Produce a precise, step-by-step implementation plan for the following goal.\n"
    "Be specific enough that a cheaper model can execute it without re-deriving decisions.\n"
    "Do NOT write code yet — only plan the approach, list the files to change, the logic\n"
    "to apply, and the order of operations.\n\n"
    "## Goal\n\n{goal}"
)


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


def _run_plan(
    service: OnmcService,
    goal: str,
    plan_runner: AgentRunner,
) -> tuple[str | None, int | None, float | None]:
    """Execute the PLAN step: invoke *plan_runner* and return the plan text.

    Parameters
    ----------
    service:
        Initialised :class:`~oh_no_my_claudecode.core.service.OnmcService`.
    goal:
        The goal to plan for.
    plan_runner:
        An :class:`~oh_no_my_claudecode.loop.models.AgentRunner` backed by the
        expensive *plan_model*.  Must accept ``(prompt, *, escalation_level)``.

    Returns
    -------
    tuple[plan_text | None, tokens | None, cost_usd | None]
        ``(None, None, None)`` when the plan step fails (exception-safe fallback).
    """
    planning_prompt = _PLAN_PROMPT_TEMPLATE.format(goal=goal)
    try:
        result: AgentRunResult = plan_runner(planning_prompt, escalation_level=0)
        plan_text = result.output.strip() or None
        if plan_text:
            # Record the plan as a DECISION memory tagged with autopilot-plan.
            with contextlib.suppress(Exception):
                service.add_memory(
                    kind="decision",
                    title=f"Autopilot plan: {goal[:80]}",
                    summary=(
                        f"[autopilot-plan] Implementation plan for: {goal[:200]}.\n\n"
                        f"{plan_text[:800]}"
                    ),
                    source_type="session",
                    source_ref="autopilot:plan",
                    confidence=0.9,
                )
        return plan_text, result.tokens, result.cost_usd
    except Exception:  # noqa: BLE001
        return None, None, None


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
    plan_model: str | None = None,
    execute_model: str | None = None,
    plan_runner: AgentRunner | None = None,
    now: datetime | None = None,  # injectable for tests
) -> AutopilotResult:
    """Run the full KNOW→(PLAN)→ACT→PROVE→LEARN autopilot cycle.

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
    plan_model:
        Optional expensive model name to use for the PLAN step.  When set, a
        planning pass is run first (or *plan_runner* is used if injected).  The
        plan text is injected into the ACT goal and recorded as a memory.  When
        ``None``, no plan step runs (current default behavior).
    execute_model:
        Optional cheap model name passed to the loop for the ACT step.  When
        ``None``, the loop uses its own default.  Ignored when *agent_runner* is
        injected.
    plan_runner:
        Optional injectable :class:`~oh_no_my_claudecode.loop.models.AgentRunner`
        for the PLAN step.  When ``None`` and *plan_model* is set, a real runner
        is built from *agent* + *plan_model*.  Intended for testing.
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

    # ── PLAN (optional) ───────────────────────────────────────────────────────
    # Enabled when plan_model is set (or plan_runner is injected for tests).
    plan_used = False
    plan_tokens: int | None = None
    plan_cost: float | None = None
    act_goal = goal  # may be augmented by the plan below

    want_plan = plan_model is not None or plan_runner is not None

    if dry_run:
        # No ACT, no LEARN — show the plan prompt it WOULD send if plan_model set.
        plan_prompt_preview = (
            _PLAN_PROMPT_TEMPLATE.format(goal=goal) if want_plan else None
        )
        dry_know_context = know_context
        if plan_prompt_preview:
            dry_know_context = (
                (dry_know_context + "\n\n" if dry_know_context else "")
                + "## Plan prompt (dry-run preview)\n\n"
                + plan_prompt_preview
            )
        return AutopilotResult(
            goal=goal,
            know_brief_summary=brief_summary,
            know_dead_ends_count=dead_ends_count,
            know_profile_applied=profile_applied,
            loop_result=_dry_run_loop_result(goal, dry_know_context),
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
            know_context=dry_know_context,
            plan_model=plan_model,
            execute_model=execute_model,
            plan_used=False,
            plan_tokens=None,
            plan_cost=None,
        )

    if want_plan:
        # Resolve the plan runner (injected takes priority over building from plan_model).
        resolved_plan_runner: AgentRunner
        if plan_runner is not None:
            resolved_plan_runner = plan_runner
        else:
            from oh_no_my_claudecode.loop.adapters import make_agent_runner

            resolved_plan_runner = make_agent_runner(
                cast("Literal['claude', 'codex', 'opencode']", agent),
                service._load_context()[0],  # noqa: SLF001
                model=plan_model,
            )

        plan_text, plan_tokens, plan_cost = _run_plan(service, goal, resolved_plan_runner)
        if plan_text:
            plan_used = True
            # Augment the goal with the plan so the loop's prompt carries it.
            act_goal = (
                f"{goal}\n\n## Implementation plan\n\n{plan_text}"
            )

    # ── ACT ───────────────────────────────────────────────────────────────────
    # Resolve the execute-step agent runner.
    resolved_agent_runner: AgentRunner | None = agent_runner
    if resolved_agent_runner is None and execute_model is not None:
        from oh_no_my_claudecode.loop.adapters import make_agent_runner as _make

        resolved_agent_runner = _make(
            cast("Literal['claude', 'codex', 'opencode']", agent),
            service._load_context()[0],  # noqa: SLF001
            model=execute_model,
        )

    loop_result, receipt_path = service.loop(
        act_goal,
        agent=agent,
        max_iterations=max_iterations,
        budget_tokens=budget_tokens,
        verify_command=verify_command,
        dry_run=False,
        max_cost_usd=max_cost_usd,
        max_wall_seconds=max_wall_seconds,
        agent_runner=resolved_agent_runner,
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
        plan_model=plan_model,
        execute_model=execute_model,
        plan_used=plan_used,
        plan_tokens=plan_tokens,
        plan_cost=plan_cost,
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
