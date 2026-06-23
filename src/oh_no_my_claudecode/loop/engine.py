"""Loop engine: memory-grounded iteration with falsifiable prediction-outcome contracts.

Each iteration:
1. RECALL: compile_guard (dead-ends) + prompt_recall (relevant memories) → brief.
2. PROMPT: goal + brief injected into agent prompt.
3. ACT: agent_runner(prompt, escalation_level) → AgentRunResult.
4. VERIFY: verify_runner(command) → VerifyOutcome.
5. CONTRACT: WIN → DECISION memory; LOSS → FAILED_APPROACH memory (blocks next iter).
6. ESCALATE: consecutive_losses >= escalation_threshold → escalation_level++.
7. NO-PROGRESS: same (files, verify_output) signature repeats no_progress_window times → stop.
"""

from __future__ import annotations

import hashlib
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from oh_no_my_claudecode.guard.compiler import compile_guard
from oh_no_my_claudecode.hooks.prompt_recall import compile_prompt_recall
from oh_no_my_claudecode.loop.models import (
    AgentRunner,
    AgentRunResult,
    IterationContract,
    LoopConfig,
    LoopResult,
    LoopSpec,
    VerifyOutcome,
    VerifyRunner,
)
from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now

_VERIFY_TIMEOUT = 120  # seconds; subprocess guard
_MAX_VERIFY_OUTPUT = 2000  # chars stored per contract


def _default_verify_runner(command: str) -> VerifyOutcome:
    """Real verify runner — runs command via subprocess with a timeout.

    This is the default used in production.  Tests must inject a fake runner
    instead of calling this function.
    """
    try:
        result = subprocess.run(  # noqa: S602, S603
            command,
            shell=True,  # noqa: S602
            capture_output=True,
            text=True,
            timeout=_VERIFY_TIMEOUT,
        )
        output = (result.stdout + result.stderr)[:_MAX_VERIFY_OUTPUT]
        return VerifyOutcome(passed=result.returncode == 0, output=output)
    except subprocess.TimeoutExpired:
        return VerifyOutcome(passed=False, output="[verify timed out]")
    except Exception as exc:  # noqa: BLE001
        return VerifyOutcome(passed=False, output=f"[verify error: {exc}]")


def _default_agent_runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
    """Stub real agent runner.

    A real implementation would shell out to an agent CLI (e.g. ``claude --print``).
    This stub is the default so that callers who inject their own runner can rely on
    the correct protocol signature.  Tests must inject a fake runner.
    """
    del prompt, escalation_level
    return AgentRunResult(
        output="[no agent configured — inject an AgentRunner]",
        prediction="",
        files_touched=[],
        tokens=None,
    )


def _iteration_signature(contract: IterationContract) -> str:
    """Deterministic fingerprint of (files_touched, verify_output_head).

    Used for no-progress detection.
    """
    files_str = ",".join(sorted(contract.files_touched))
    output_head = contract.verify_output[:200]
    return hashlib.sha256(f"{files_str}||{output_head}".encode()).hexdigest()[:16]


def _build_brief(
    storage: SQLiteStorage,
    goal: str,
    last_loss: IterationContract | None,
    escalation_level: int,
) -> str:
    """Build the memory-grounded brief injected into each iteration's prompt.

    Combines:
    - Relevant memories via prompt_recall (signal for what to try).
    - Dead-ends via compile_guard (signal for what NOT to try).
    - Last failure summary (concrete feedback from the previous iteration).
    - Escalation hint (when consecutive losses exceed threshold).
    """
    parts: list[str] = []

    # 1. Relevant memories via prompt recall.
    try:
        recall_md, _ = compile_prompt_recall(storage, goal)
        if recall_md:
            parts.append(recall_md)
    except Exception:  # noqa: BLE001, S110
        pass  # best-effort; never fail the loop because recall is unavailable

    # 2. Dead-ends — the DON'T-REPEAT section (the memory-grounded core property).
    try:
        guard = compile_guard(storage, goal)
        if guard.has_dead_ends:
            parts.append(guard.to_markdown())
    except Exception:  # noqa: BLE001, S110
        pass  # best-effort; never fail the loop because guard is unavailable

    # 3. Last failure summary — concrete context from the immediately prior loss.
    if last_loss is not None:
        parts.append(
            "## Last attempt failed\n\n"
            f"**What was tried:** {last_loss.action_summary}\n\n"
            f"**Prediction that failed:** {last_loss.prediction}\n\n"
            "**Verify output (truncated):**\n"
            f"```\n{last_loss.verify_output[:500]}\n```\n"
        )

    # 4. Escalation hint — surface after repeated failures.
    if escalation_level > 0:
        parts.append(
            f"## Escalation level {escalation_level}\n\n"
            "Previous strategies failed multiple times in a row. "
            "Try a fundamentally different approach — do not repeat the pattern of prior attempts."
        )

    return "\n\n".join(parts)


def _record_win(
    storage: SQLiteStorage,
    goal: str,
    contract: IterationContract,
    now: datetime,
) -> str:
    """Record a successful approach as a DECISION memory; return its id."""
    summary = (
        f"Approach that worked for goal: {goal[:120]}. "
        f"Action: {contract.action_summary[:200]}."
    )
    mid = stable_id(
        MemoryKind.DECISION.value,
        f"loop-win:{goal[:80]}",
        summary,
        "loop:engine",
        prefix="loop",
    )
    entry = MemoryEntry(
        id=mid,
        kind=MemoryKind.DECISION,
        title=f"Loop win: {goal[:80]}",
        summary=summary,
        details=(
            f"Prediction: {contract.prediction}\n"
            f"Files touched: {', '.join(contract.files_touched)}"
        ),
        source_type=SourceType.SESSION,
        source_ref="loop:engine",
        tags=["loop-win", "loop"],
        confidence=0.85,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return mid


def _record_loss(
    storage: SQLiteStorage,
    goal: str,
    contract: IterationContract,
    now: datetime,
) -> str:
    """Record a failed approach as FAILED_APPROACH so next iteration's guard blocks it.

    This is the core of the don't-repeat property: every loss is immediately
    written to memory tagged loop-deadend, so compile_guard() retrieves it on
    the very next iteration brief.
    """
    summary = (
        f"Failed approach for goal: {goal[:120]}. "
        f"Tried: {contract.action_summary[:200]}. "
        f"Prediction was: {contract.prediction[:100]}."
    )
    mid = stable_id(
        MemoryKind.FAILED_APPROACH.value,
        f"loop-deadend:{goal[:80]}",
        summary,
        f"loop:iter:{contract.iteration}",
        prefix="loop",
    )
    entry = MemoryEntry(
        id=mid,
        kind=MemoryKind.FAILED_APPROACH,
        title=f"Loop dead-end (iter {contract.iteration}): {goal[:60]}",
        summary=summary,
        details=(
            f"Verify output:\n{contract.verify_output[:800]}\n\n"
            f"Files touched: {', '.join(contract.files_touched)}"
        ),
        source_type=SourceType.SESSION,
        source_ref=f"loop:iter:{contract.iteration}",
        tags=["loop-deadend", "loop", "failed_approach"],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return mid


def run_loop(
    storage: SQLiteStorage,
    repo_root: Path,
    spec: LoopSpec,
    config: LoopConfig,
    *,
    agent_runner: AgentRunner,
    verify_runner: VerifyRunner,
    now: datetime | None = None,
    clock: Callable[[], float] | None = None,
) -> LoopResult:
    """Run a memory-grounded loop until convergence, budget, or max iterations.

    Parameters
    ----------
    storage:
        Initialised SQLiteStorage instance.  Dead-ends are written here and
        recalled here on the next iteration — this is the memory substrate.
    repo_root:
        Absolute path to the repo root.  Reserved for future path-relative
        operations; passed through but not used internally.
    spec:
        Loop goal and optional success criteria.
    config:
        Runtime knobs: max_iterations, budget_tokens, verify_command,
        escalation_threshold, no_progress_window, max_cost_usd,
        max_wall_seconds.
    agent_runner:
        Injectable callable matching the AgentRunner protocol.  The default
        _default_agent_runner is a no-op stub; real runs inject a CLI agent.
        Tests MUST inject a fake — never the real subprocess runner.
    verify_runner:
        Injectable callable matching the VerifyRunner protocol.  The default
        _default_verify_runner shells out.  Tests MUST inject a fake.
    now:
        Reference timestamp for memory records (injectable for deterministic tests).
    clock:
        Injectable monotonic clock (``Callable[[], float]``).  Defaults to
        ``time.monotonic``.  Tests inject a fake for deterministic wall-time
        limit testing.

    Returns
    -------
    LoopResult
        stop_reason is one of:
        'converged' | 'max-iterations' | 'budget' | 'no-progress' | 'cost' | 'wall-time'.
    """
    del repo_root  # reserved for future path-relative operations

    ref_now: datetime = now if now is not None else datetime.now(UTC)
    _clock: Callable[[], float] = clock if clock is not None else time.monotonic

    iterations: list[IterationContract] = []
    recorded_memory_ids: list[str] = []
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    consecutive_losses: int = 0
    escalation_level: int = 0
    last_loss: IterationContract | None = None
    signature_counts: dict[str, int] = {}
    wall_start: float = _clock()

    for i in range(1, config.max_iterations + 1):
        # Budget check before spending more tokens.
        if config.budget_tokens is not None and total_tokens >= config.budget_tokens:
            return LoopResult(
                iterations=iterations,
                converged=False,
                stop_reason="budget",
                recorded_memory_ids=recorded_memory_ids,
                total_tokens=total_tokens,
                total_cost_usd=total_cost_usd if total_cost_usd > 0 else None,
            )

        # Cost limit check before each iteration.
        if config.max_cost_usd is not None and total_cost_usd >= config.max_cost_usd:
            return LoopResult(
                iterations=iterations,
                converged=False,
                stop_reason="cost",
                recorded_memory_ids=recorded_memory_ids,
                total_tokens=total_tokens,
                total_cost_usd=total_cost_usd if total_cost_usd > 0 else None,
            )

        # Wall-time limit check before each iteration.
        if config.max_wall_seconds is not None:
            elapsed = _clock() - wall_start
            if elapsed >= config.max_wall_seconds:
                return LoopResult(
                    iterations=iterations,
                    converged=False,
                    stop_reason="wall-time",
                    recorded_memory_ids=recorded_memory_ids,
                    total_tokens=total_tokens,
                    total_cost_usd=total_cost_usd if total_cost_usd > 0 else None,
                )

        # Build the memory-grounded prompt.
        brief = _build_brief(storage, spec.goal, last_loss, escalation_level)
        prompt = (
            f"## Goal\n\n{spec.goal}\n\n"
            + (
                f"## Success criteria\n\n{spec.success_criteria}\n\n"
                if spec.success_criteria
                else ""
            )
            + brief
        )

        # Agent acts.
        agent_result: AgentRunResult = agent_runner(prompt, escalation_level=escalation_level)
        if agent_result.tokens is not None:
            total_tokens += agent_result.tokens
        if agent_result.cost_usd is not None:
            total_cost_usd += agent_result.cost_usd

        # Verify.
        verify_outcome: VerifyOutcome = verify_runner(config.verify_command)
        outcome: str = "win" if verify_outcome.passed else "loss"

        contract = IterationContract(
            iteration=i,
            prediction=agent_result.prediction,
            action_summary=agent_result.output[:400],
            files_touched=list(agent_result.files_touched),
            verify_passed=verify_outcome.passed,
            verify_output=verify_outcome.output[:_MAX_VERIFY_OUTPUT],
            outcome=outcome,  # type: ignore[arg-type]
            tokens=agent_result.tokens,
        )
        iterations.append(contract)

        if outcome == "win":
            # WIN: record success, return immediately.
            mid = _record_win(storage, spec.goal, contract, ref_now)
            recorded_memory_ids.append(mid)
            return LoopResult(
                iterations=iterations,
                converged=True,
                stop_reason="converged",
                recorded_memory_ids=recorded_memory_ids,
                total_tokens=total_tokens,
                total_cost_usd=total_cost_usd if total_cost_usd > 0 else None,
            )
        else:
            # LOSS: record dead-end so next iteration's guard blocks it.
            mid = _record_loss(storage, spec.goal, contract, ref_now)
            recorded_memory_ids.append(mid)
            consecutive_losses += 1
            last_loss = contract

            # Escalate after threshold consecutive losses.
            if consecutive_losses >= config.escalation_threshold:
                escalation_level += 1
                consecutive_losses = 0

            # No-progress detection.
            sig = _iteration_signature(contract)
            signature_counts[sig] = signature_counts.get(sig, 0) + 1
            if signature_counts[sig] >= config.no_progress_window:
                return LoopResult(
                    iterations=iterations,
                    converged=False,
                    stop_reason="no-progress",
                    recorded_memory_ids=recorded_memory_ids,
                    total_tokens=total_tokens,
                    total_cost_usd=total_cost_usd if total_cost_usd > 0 else None,
                )

    return LoopResult(
        iterations=iterations,
        converged=False,
        stop_reason="max-iterations",
        recorded_memory_ids=recorded_memory_ids,
        total_tokens=total_tokens,
        total_cost_usd=total_cost_usd if total_cost_usd > 0 else None,
    )


# Keep utc_now import for callers who might use it.
__all__ = [
    "_build_brief",
    "_default_agent_runner",
    "_default_verify_runner",
    "run_loop",
]

_ = utc_now  # referenced above; suppress unused-import
