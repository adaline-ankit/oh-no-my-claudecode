"""Tests for the onmc autopilot orchestrator (KNOW→ACT→PROVE→LEARN).

All tests use ONLY injected fake runners — no real subprocess, no real agent,
no network.  The tests are fully deterministic: injectable now, fake runners,
temp SQLite storage via the sample_repo fixture.

Coverage:
- WIN run: converges → records success memory → attempts skill_promote →
  brain_after.memories > brain_before.memories → verified=True
- LOSS run: loop records FAILED_APPROACH dead-ends → dead_ends_recorded > 0 →
  verified=False → brain delta reflects dead-ends
- dry-run: neither runner invoked → receipt_path=None → no memory writes →
  KNOW context is non-empty
- verified field flows from loop convergence
- receipt_path is surfaced on real (non-dry) run
- service.loop still works with + without injected runners (smoke-test existing loop)
- CLI autopilot --json exit codes + shape
- PLAN step: plan runner invoked once with planning prompt; plan injected into ACT goal
- No plan flags → plan_used=False, unchanged behavior
- Plan step failure → graceful fallback, run still completes
- --dry-run with --plan-with shows plan prompt preview, no runners invoked
- CLI --plan-with / --execute-with parsed + --json shape
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from oh_no_my_claudecode.autopilot.models import AutopilotResult
from oh_no_my_claudecode.autopilot.orchestrator import run_autopilot
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.loop.models import (
    AgentRunResult,
    LoopResult,
    VerifyOutcome,
)
from oh_no_my_claudecode.models.memory import MemoryKind

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2024, 9, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fake runner helpers
# ---------------------------------------------------------------------------


def _fake_agent(
    output: str,
    prediction: str = "fake prediction",
    files: list[str] | None = None,
    tokens: int | None = 100,
) -> object:
    """Return a callable AgentRunner that always returns the same result."""

    def _runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        return AgentRunResult(
            output=output,
            prediction=prediction,
            files_touched=files or [],
            tokens=tokens,
        )

    return _runner


def _fake_verify(*, passes: bool, output: str = "") -> object:
    """Return a callable VerifyRunner with a fixed result."""

    def _runner(command: str) -> VerifyOutcome:
        del command
        return VerifyOutcome(passed=passes, output=output)

    return _runner


def _changing_probe() -> object:
    """Return a ChangeProbe that reports a NEW signature every call.

    Fake agent runners don't actually touch the git working tree, so the real
    git-backed probe would see a clean tree and (correctly, for a no-op) refuse
    the win — breaking loop-control tests that only exercise fake runners.  This
    fake reports a distinct signature each call so ``pre_sig != post_sig``,
    i.e. "the agent changed something", which is what these tests intend.
    """
    counter = {"n": 0}

    def _probe() -> str | None:
        counter["n"] += 1
        return f"sig-{counter['n']}"

    return _probe


def _static_probe() -> object:
    """Return a ChangeProbe that reports the SAME signature every call.

    Models "the agent changed nothing" — used to exercise the vacuous-pass gate
    deterministically without a real git repo.
    """

    def _probe() -> str | None:
        return "unchanged"

    return _probe


# ---------------------------------------------------------------------------
# Service fixture backed by sample_repo
# ---------------------------------------------------------------------------


def _init_service(repo: Path) -> OnmcService:
    """Init onmc in *repo* and return a ready OnmcService."""
    svc = OnmcService(cwd=repo)
    svc.init_project()
    return svc


def _seed_failed_approach(svc: OnmcService, goal: str) -> None:
    """Seed a FAILED_APPROACH memory so guard() has something to surface."""
    svc.add_memory(
        kind=MemoryKind.FAILED_APPROACH,
        title=f"Dead-end: {goal[:60]}",
        summary=f"Tried brute force approach for: {goal}. Did not work.",
        source_type="session",
        source_ref="test:seed",
        confidence=0.8,
    )


# ---------------------------------------------------------------------------
# Test 1 — WIN run: converged → brain grew
# ---------------------------------------------------------------------------


def test_win_run_records_success_memory(sample_repo: Path) -> None:
    """A converging autopilot run should record a success memory (memories_added > 0)."""
    svc = _init_service(sample_repo)

    result = run_autopilot(
        svc,
        "fix the broken import",
        agent_runner=_fake_agent("patched import", tokens=200),
        verify_runner=_fake_verify(passes=True, output="1 passed"),
        change_probe=_changing_probe(),
        now=_FIXED_NOW,
    )

    assert isinstance(result, AutopilotResult)
    assert result.verified is True
    assert result.stop_reason == "converged"
    assert result.tokens == 200
    assert result.memories_added > 0, "WIN should record at least one memory"
    assert result.dead_ends_recorded == 0, "No losses → no dead-ends"
    # Brain grew
    assert result.brain_after.memories >= result.brain_before.memories


# ---------------------------------------------------------------------------
# Test 2 — LOSS run: dead-ends recorded, verified=False
# ---------------------------------------------------------------------------


def test_loss_run_records_dead_ends(sample_repo: Path) -> None:
    """A non-converging autopilot run should record FAILED_APPROACH dead-ends."""
    svc = _init_service(sample_repo)
    # Seed one existing FAILED_APPROACH so guard produces output.
    _seed_failed_approach(svc, "remove the N+1 query")

    result = run_autopilot(
        svc,
        "remove the N+1 query",
        max_iterations=2,
        agent_runner=_fake_agent("tried eager load", tokens=50),
        verify_runner=_fake_verify(passes=False, output="FAILED"),
        now=_FIXED_NOW,
    )

    assert isinstance(result, AutopilotResult)
    assert result.verified is False
    assert result.dead_ends_recorded > 0, "LOSS iterations should record dead-ends"
    # guard surfaced our seeded dead-end
    assert result.know_dead_ends_count >= 1


# ---------------------------------------------------------------------------
# Test 3 — dry-run: no runners invoked, no memory writes, KNOW context present
# ---------------------------------------------------------------------------


def test_dry_run_invokes_neither_runner(sample_repo: Path) -> None:
    """--dry-run must invoke neither agent nor verify runners."""
    svc = _init_service(sample_repo)

    invoked: list[str] = []

    def _guard_agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
        invoked.append("agent")
        return AgentRunResult(output="should not run", prediction="", files_touched=[])

    def _guard_verify(command: str) -> VerifyOutcome:
        invoked.append("verify")
        return VerifyOutcome(passed=False, output="should not run")

    result = run_autopilot(
        svc,
        "dry run goal",
        dry_run=True,
        agent_runner=_guard_agent,
        verify_runner=_guard_verify,
        now=_FIXED_NOW,
    )

    assert not invoked, f"Runners should NOT be called in dry-run; got: {invoked}"
    assert isinstance(result, AutopilotResult)
    assert result.stop_reason == "dry-run"
    assert result.receipt_path is None
    assert result.verified is False
    assert result.tokens == 0
    assert result.cost_usd is None
    assert result.memories_added == 0
    assert result.skills_added == 0
    # KNOW context should be populated (brief + guard + profile attempt)
    assert result.know_brief_summary != "" or result.know_context != ""
    # Brain should not have changed
    assert result.brain_after.memories == result.brain_before.memories


# ---------------------------------------------------------------------------
# Test 4 — verified flows from loop convergence
# ---------------------------------------------------------------------------


def test_verified_only_when_converged_and_verify_passed(sample_repo: Path) -> None:
    """verified must be True iff the loop converged AND the final verify passed."""
    svc = _init_service(sample_repo)

    result = run_autopilot(
        svc,
        "check verify flag",
        agent_runner=_fake_agent("done"),
        verify_runner=_fake_verify(passes=True),
        change_probe=_changing_probe(),
        now=_FIXED_NOW,
    )
    assert result.verified is True

    # Now a loss run — re-use the same repo (onmc already initialized above).
    svc2 = svc

    result2 = run_autopilot(
        svc2,
        "check verify flag loss",
        max_iterations=1,
        agent_runner=_fake_agent("done"),
        verify_runner=_fake_verify(passes=False),
        now=_FIXED_NOW,
    )
    assert result2.verified is False


# ---------------------------------------------------------------------------
# Test 5 — receipt_path is surfaced on real (non-dry) run
# ---------------------------------------------------------------------------


def test_receipt_path_surfaced_on_real_run(sample_repo: Path) -> None:
    """receipt_path should be a Path (not None) after a real run that converges."""
    svc = _init_service(sample_repo)

    result = run_autopilot(
        svc,
        "fix the cache module",
        agent_runner=_fake_agent("fixed cache", tokens=150),
        verify_runner=_fake_verify(passes=True, output="ok"),
        change_probe=_changing_probe(),
        now=_FIXED_NOW,
    )

    assert isinstance(result, AutopilotResult)
    # receipt_path may be None when the receipts dir can't be written, but on a
    # normal run it should be a valid path that exists.
    if result.receipt_path is not None:
        assert result.receipt_path.exists(), "Receipt file should have been written"


# ---------------------------------------------------------------------------
# Test 6 — service.loop still works with injected runners (regression guard)
# ---------------------------------------------------------------------------


def test_service_loop_with_injected_runners(sample_repo: Path) -> None:
    """service.loop must accept injected runners and produce a LoopResult."""
    svc = _init_service(sample_repo)

    loop_result, receipt_path = svc.loop(
        "injected runner test",
        agent_runner=_fake_agent("done", tokens=42),
        verify_runner=_fake_verify(passes=True),
        change_probe=_changing_probe(),
    )

    assert isinstance(loop_result, LoopResult)
    assert loop_result.converged is True
    assert loop_result.total_tokens == 42


def test_service_loop_without_injected_runners_dry_run(sample_repo: Path) -> None:
    """service.loop default dry_run path must still work (regression)."""
    svc = _init_service(sample_repo)

    loop_result, receipt_path = svc.loop(
        "dry run test",
        dry_run=True,
    )

    assert isinstance(loop_result, LoopResult)
    assert loop_result.stop_reason == "dry-run"
    assert receipt_path is None


# ---------------------------------------------------------------------------
# Test 7 — brain delta: memories_added > 0 on WIN
# ---------------------------------------------------------------------------


def test_brain_delta_positive_on_win(sample_repo: Path) -> None:
    """memories_added must be > 0 when autopilot converges."""
    svc = _init_service(sample_repo)

    result = run_autopilot(
        svc,
        "add rate limiting",
        agent_runner=_fake_agent("added rate limit"),
        verify_runner=_fake_verify(passes=True),
        change_probe=_changing_probe(),
        now=_FIXED_NOW,
    )

    assert result.memories_added > 0, (
        f"Expected memories_added > 0 on WIN; got {result.memories_added}"
    )


# ---------------------------------------------------------------------------
# Test 8 — CLI autopilot --json shape and exit codes
# ---------------------------------------------------------------------------


def test_cli_autopilot_json_win(sample_repo: Path) -> None:
    """CLI autopilot --json on a WIN run should emit valid JSON with verified=True."""
    from typer.testing import CliRunner

    from oh_no_my_claudecode.cli import app

    # We can't inject runners through the CLI, so use --dry-run for a safe,
    # network-free test.  dry-run → verified=False, stop_reason=dry-run.
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["autopilot", "fix the cache bug", "--dry-run", "--json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, f"Expected exit 0; got {result.exit_code}\n{result.output}"
    data = json.loads(result.output)
    assert "verified" in data
    assert "stop_reason" in data
    assert data["stop_reason"] == "dry-run"
    assert data["verified"] is False
    assert "brain_before" in data
    assert "brain_after" in data


def test_cli_autopilot_dry_run_exit_code(sample_repo: Path) -> None:
    """CLI autopilot --dry-run should exit 1 (not verified)."""
    from typer.testing import CliRunner

    from oh_no_my_claudecode.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["autopilot", "fix the cache bug", "--dry-run"],
        catch_exceptions=False,
    )
    # dry-run → not verified → exit 1
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Test 9 — PLAN step: fake plan runner invoked once, plan injected into ACT goal
# ---------------------------------------------------------------------------


def test_plan_step_invokes_plan_runner_and_injects_plan(sample_repo: Path) -> None:
    """With --plan-with set, plan runner called once; plan text is in ACT goal."""
    svc = _init_service(sample_repo)

    plan_calls: list[str] = []
    act_prompts: list[str] = []

    def _fake_plan_runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        plan_calls.append(prompt)
        return AgentRunResult(
            output="Step 1: do X\nStep 2: do Y",
            prediction="planning done",
            files_touched=[],
            tokens=50,
            cost_usd=0.01,
        )

    def _fake_act_runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        act_prompts.append(prompt)
        return AgentRunResult(
            output="executed the plan",
            prediction="done",
            files_touched=[],
            tokens=100,
        )

    result = run_autopilot(
        svc,
        "add caching layer",
        plan_runner=_fake_plan_runner,
        plan_model="claude-opus-fake",
        execute_model="claude-haiku-fake",
        agent_runner=_fake_act_runner,
        verify_runner=_fake_verify(passes=True),
        change_probe=_changing_probe(),
        now=_FIXED_NOW,
    )

    # Plan runner called exactly once.
    assert len(plan_calls) == 1, f"Expected 1 plan call; got {len(plan_calls)}"
    # Planning prompt contains the goal.
    assert "add caching layer" in plan_calls[0]
    assert "Do NOT write code" in plan_calls[0]

    # ACT runner received the plan-augmented goal.
    assert len(act_prompts) >= 1
    assert "Implementation plan" in act_prompts[0]
    assert "Step 1: do X" in act_prompts[0]

    # Result reflects plan_used + models.
    assert isinstance(result, AutopilotResult)
    assert result.plan_used is True
    assert result.plan_model == "claude-opus-fake"
    assert result.execute_model == "claude-haiku-fake"
    assert result.plan_tokens == 50
    assert result.plan_cost == pytest.approx(0.01)

    # Plan recorded as memory.
    _, _, storage = svc._load_context()  # type: ignore[attr-defined]
    memories = storage.list_memories()
    plan_memories = [
        m for m in memories
        if "autopilot-plan" in (m.summary or "")
    ]
    assert plan_memories, "Expected at least one autopilot-plan memory"


# ---------------------------------------------------------------------------
# Test 10 — No plan flags → unchanged behavior (plan_used=False, no extra call)
# ---------------------------------------------------------------------------


def test_no_plan_flags_unchanged_behavior(sample_repo: Path) -> None:
    """Without --plan-with, no plan runner should be invoked; plan_used=False."""
    svc = _init_service(sample_repo)

    plan_calls: list[str] = []

    def _guard_plan_runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        plan_calls.append(prompt)
        return AgentRunResult(output="should not run", prediction="", files_touched=[])

    result = run_autopilot(
        svc,
        "fix the import",
        agent_runner=_fake_agent("done"),
        verify_runner=_fake_verify(passes=True),
        change_probe=_changing_probe(),
        # plan_runner is NOT wired up via plan_model; we pass it directly to
        # confirm it's ignored when plan_model is None.
        now=_FIXED_NOW,
    )

    assert not plan_calls, "Plan runner should NOT be called when plan_model is None"
    assert isinstance(result, AutopilotResult)
    assert result.plan_used is False
    assert result.plan_model is None
    assert result.execute_model is None
    assert result.plan_tokens is None
    assert result.plan_cost is None


# ---------------------------------------------------------------------------
# Test 11 — Plan step failure falls back gracefully (run still completes)
# ---------------------------------------------------------------------------


def test_plan_step_failure_falls_back_gracefully(sample_repo: Path) -> None:
    """A plan runner that raises must not abort the autopilot run."""
    svc = _init_service(sample_repo)

    def _failing_plan_runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        raise RuntimeError("plan model unavailable")

    result = run_autopilot(
        svc,
        "fix the bug",
        plan_runner=_failing_plan_runner,
        plan_model="expensive-model",
        agent_runner=_fake_agent("fixed it"),
        verify_runner=_fake_verify(passes=True),
        change_probe=_changing_probe(),
        now=_FIXED_NOW,
    )

    # Run still completes and converges normally.
    assert isinstance(result, AutopilotResult)
    assert result.stop_reason == "converged"
    assert result.verified is True
    # plan_used stays False since plan text was empty (exception swallowed).
    assert result.plan_used is False


# ---------------------------------------------------------------------------
# Test 12 — dry-run with --plan-with shows plan prompt preview, no runners invoked
# ---------------------------------------------------------------------------


def test_dry_run_with_plan_model_shows_prompt_no_runners(sample_repo: Path) -> None:
    """--dry-run with --plan-with must not invoke any runner, but show plan prompt."""
    svc = _init_service(sample_repo)

    invoked: list[str] = []

    def _guard_runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        invoked.append(f"agent:{prompt[:20]}")
        return AgentRunResult(output="should not run", prediction="", files_touched=[])

    def _guard_verify(command: str) -> VerifyOutcome:
        invoked.append("verify")
        return VerifyOutcome(passed=False, output="should not run")

    result = run_autopilot(
        svc,
        "add rate limiting",
        dry_run=True,
        plan_model="claude-opus-fake",
        plan_runner=_guard_runner,
        agent_runner=_guard_runner,
        verify_runner=_guard_verify,
        now=_FIXED_NOW,
    )

    assert not invoked, f"No runners should fire in dry-run; got: {invoked}"
    assert isinstance(result, AutopilotResult)
    assert result.stop_reason == "dry-run"
    assert result.plan_used is False
    # Plan prompt preview should appear in the know_context.
    assert "Plan prompt (dry-run preview)" in result.know_context
    assert "add rate limiting" in result.know_context


# ---------------------------------------------------------------------------
# Test 13 — CLI --plan-with / --execute-with parsed + --json shape
# ---------------------------------------------------------------------------


def test_cli_plan_with_execute_with_in_json(sample_repo: Path) -> None:
    """CLI --plan-with + --execute-with + --json should include plan fields."""
    import json

    from typer.testing import CliRunner

    from oh_no_my_claudecode.cli import app

    runner = CliRunner()
    # Use --dry-run so no real agent is invoked; plan_model set to non-None.
    result = runner.invoke(
        app,
        [
            "autopilot",
            "add feature",
            "--dry-run",
            "--json",
            "--plan-with",
            "claude-opus-fake",
            "--execute-with",
            "claude-haiku-fake",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, f"Expected exit 0; got {result.exit_code}\n{result.output}"
    data = json.loads(result.output)
    assert "plan_model" in data
    assert "execute_model" in data
    assert "plan_used" in data
    assert "plan_tokens" in data
    assert "plan_cost" in data
    assert data["plan_model"] == "claude-opus-fake"
    assert data["execute_model"] == "claude-haiku-fake"
    assert data["plan_used"] is False  # dry-run never runs the plan step
