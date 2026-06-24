"""Data models for the onmc autopilot orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BrainCounts:
    """Snapshot of the brain size at a point in time."""

    memories: int
    skills: int
    dead_ends: int


@dataclass
class AutopilotResult:
    """Aggregated result from a completed autopilot run (KNOW→ACT→PROVE→LEARN).

    Fields
    ------
    goal:
        The goal string passed to autopilot.
    know_brief_summary:
        One-line summary of what compile_brief produced (the task brief title
        or first line of context compiled in KNOW phase).
    know_dead_ends_count:
        Number of recorded dead-ends surfaced by guard() during KNOW.
    know_profile_applied:
        True when user_profile() returned a non-empty profile that was included
        in the context.
    loop_result:
        The :class:`~oh_no_my_claudecode.loop.models.LoopResult` from ACT (or a
        dry-run stub when ``dry_run=True``).
    receipt_path:
        Path to the tamper-evident run receipt written by the loop, or ``None``
        for dry-runs.
    verified:
        True iff the loop converged AND the final verify passed.
    tokens:
        Total tokens consumed during ACT (0 for dry-runs).
    cost_usd:
        Total USD cost reported by the agent adapter, or ``None`` when not
        available.
    brain_before:
        Brain counts snapshot taken before KNOW phase.
    brain_after:
        Brain counts snapshot taken after LEARN phase.
    memories_added:
        Number of new memories added by LEARN (WIN path) or loop dead-ends
        recorded (LOSS path).
    skills_added:
        Number of new skills promoted during LEARN.
    dead_ends_recorded:
        Number of FAILED_APPROACH dead-ends the loop recorded (LOSS iterations).
    skill_promoted_name:
        Name of the skill promoted during LEARN, or ``None`` when no skill was
        promoted.
    captured_count:
        Number of memories captured via capture_session() during LEARN.
    consolidated_count:
        Number of memory changes written by consolidate() during LEARN.
    stop_reason:
        The stop_reason from the underlying LoopResult (or ``"dry-run"``).
    """

    goal: str
    know_brief_summary: str
    know_dead_ends_count: int
    know_profile_applied: bool
    loop_result: object  # LoopResult (avoiding circular import at model level)
    receipt_path: Path | None
    verified: bool
    tokens: int
    cost_usd: float | None
    brain_before: BrainCounts
    brain_after: BrainCounts
    memories_added: int
    skills_added: int
    dead_ends_recorded: int
    skill_promoted_name: str | None
    captured_count: int
    consolidated_count: int
    stop_reason: str
    # KNOW context text (for --dry-run inspection and narration)
    know_context: str = field(default="")
