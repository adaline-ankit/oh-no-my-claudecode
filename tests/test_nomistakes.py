"""Tests for the onmc No-Mistakes gate.

All tests use injected fake runners. No real Claude/Codex/OpenCode process runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.loop.models import AgentRunResult, VerifyOutcome
from oh_no_my_claudecode.nomistakes import run_nomistakes


def _init_service(repo: Path) -> OnmcService:
    svc = OnmcService(cwd=repo)
    svc.init_project()
    return svc


def _agent(output: str = "fixed bug") -> object:
    def _runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        return AgentRunResult(
            output=output,
            prediction="verifier will pass",
            files_touched=["src/cache.py"],
            tokens=123,
            cost_usd=0.01,
        )

    return _runner


def _verify(passes: bool) -> object:
    def _runner(command: str) -> VerifyOutcome:
        del command
        return VerifyOutcome(passed=passes, output="ok" if passes else "failed")

    return _runner


def test_nomistakes_approves_only_verified_receipt(sample_repo: Path) -> None:
    svc = _init_service(sample_repo)

    result = run_nomistakes(
        svc,
        "fix cache bug",
        agent_runner=_agent(),
        verify_runner=_verify(True),
        isolate=False,
        audit_fail_on="high",
    )

    assert result.approved is True
    assert result.receipt_path is not None
    assert [gate.name for gate in result.gates] == ["audit", "eval", "receipt"]
    assert not result.blocking_gates


def test_nomistakes_blocks_when_verify_fails(sample_repo: Path) -> None:
    svc = _init_service(sample_repo)

    result = run_nomistakes(
        svc,
        "fix cache bug",
        max_iterations=1,
        agent_runner=_agent(),
        verify_runner=_verify(False),
        isolate=False,
    )

    assert result.approved is False
    assert any(gate.name == "receipt" and gate.blocking for gate in result.gates)


def test_nomistakes_blocks_on_audit_even_if_verify_passes(sample_repo: Path) -> None:
    (sample_repo / ".claude").mkdir()
    (sample_repo / ".claude" / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(*)", "Read"]}}),
        encoding="utf-8",
    )
    svc = _init_service(sample_repo)

    result = run_nomistakes(
        svc,
        "fix cache bug",
        agent_runner=_agent(),
        verify_runner=_verify(True),
        isolate=False,
        audit_fail_on="high",
    )

    assert result.approved is False
    assert any(gate.name == "audit" and gate.blocking for gate in result.gates)
    assert any(gate.name == "receipt" and gate.status == "pass" for gate in result.gates)


def test_nomistakes_l1_is_dry_run_and_never_approves(sample_repo: Path) -> None:
    svc = _init_service(sample_repo)
    invoked: list[str] = []

    def _guard_agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
        invoked.append("agent")
        return AgentRunResult(output="nope", prediction="", files_touched=[])

    result = run_nomistakes(
        svc,
        "inspect only",
        autonomy="L1",
        agent_runner=_guard_agent,
        verify_runner=_verify(True),
        isolate=False,
    )

    assert result.dry_run is True
    assert result.approved is False
    assert invoked == []


def test_cli_nomistakes_dry_run_json_shape(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_service(sample_repo)
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["nomistakes", "fix cache bug", "--dry-run", "--json"],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["approved"] is False
    assert data["dry_run"] is True
    assert data["autonomy"] == "L2"
    assert [gate["name"] for gate in data["gates"]] == ["audit", "eval", "receipt"]
