"""Tests for ``onmc explain`` — plain-English verdict of a run receipt.

Coverage (≥6 tests as required)
--------------------------------
1. Pure ``explain_receipt`` — verified receipt: correct verdict + explanation.
2. Pure ``explain_receipt`` — no-changes receipt: vacuous-pass explanation text.
3. Pure ``explain_receipt`` — max-iterations receipt: correct explanation.
4. Pure ``explain_receipt`` — agent-error receipt: correct explanation.
5. Pure ``explain_receipt`` — missing keys default sensibly (never crash).
6. CLI ``--json`` envelope shape: verified field, kind, all expected keys.
7. CLI "no receipts" path: friendly message, exit 0.
8. CLI "latest is picked": seed 2 receipts with different mtimes, verify newest chosen.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.explain.analyze import ExplainResult, explain_receipt

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_receipt(
    *,
    verified: bool = True,
    stop_reason: str = "converged",
    goal: str = "fix the bug",
    iterations: int = 3,
    tokens_used: int = 12000,
    cost_usd: float | None = 0.05,
    agent: str = "claude",
    ended_at: str = "2026-07-08T12:00:00Z",
    receipt_hash: str = "abcdef12" + "0" * 56,
) -> dict[str, Any]:
    """Build a minimal receipt dict for testing."""
    return {
        "schema_version": "2",
        "goal": goal,
        "agent": agent,
        "verified": verified,
        "stop_reason": stop_reason,
        "iterations": iterations,
        "tokens_used": tokens_used,
        "cost_usd": cost_usd,
        "wall_seconds": 42.5,
        "verifier_command": "make test",
        "ended_at": ended_at,
        "receipt_hash": receipt_hash,
    }


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


# ---------------------------------------------------------------------------
# Test 1: Verified receipt
# ---------------------------------------------------------------------------


def test_explain_receipt_verified() -> None:
    """explain_receipt on a converged receipt should return verified=True, VERIFIED verdict."""
    receipt = _make_receipt(verified=True, stop_reason="converged", iterations=2)
    result: ExplainResult = explain_receipt(receipt)

    assert result.verified is True
    assert result.verdict == "VERIFIED"
    assert "2 iteration" in result.explanation
    assert result.stop_reason == "converged"
    assert result.goal == "fix the bug"
    assert result.iterations == 2
    assert result.tokens == 12000  # noqa: PLR2004
    assert result.cost_usd == pytest.approx(0.05)
    assert result.receipt_hash_short == "abcdef12"


# ---------------------------------------------------------------------------
# Test 2: no-changes receipt — vacuous pass
# ---------------------------------------------------------------------------


def test_explain_receipt_no_changes_is_not_verified() -> None:
    """no-changes stop_reason must be NOT VERIFIED with vacuous-pass explanation."""
    receipt = _make_receipt(
        verified=True,  # receipt itself says True (verifier exit 0)
        stop_reason="no-changes",
        iterations=1,
    )
    result: ExplainResult = explain_receipt(receipt)

    assert result.verified is False, "no-changes should NOT count as verified"
    assert result.verdict == "NOT VERIFIED"
    # Must mention vacuous pass
    assert "vacuous pass" in result.explanation.lower()
    # Must mention "no changes" concept
    assert "no changes" in result.explanation.lower() or "no change" in result.explanation.lower()
    assert result.stop_reason == "no-changes"


# ---------------------------------------------------------------------------
# Test 3: max-iterations
# ---------------------------------------------------------------------------


def test_explain_receipt_max_iterations() -> None:
    """max-iterations stop_reason should produce NOT VERIFIED with iteration-cap explanation."""
    receipt = _make_receipt(verified=False, stop_reason="max-iterations", iterations=10)
    result: ExplainResult = explain_receipt(receipt)

    assert result.verified is False
    assert result.verdict == "NOT VERIFIED"
    # Explanation should mention the cap / max / ran out of attempts
    expl_lower = result.explanation.lower()
    assert any(kw in expl_lower for kw in ("maximum", "iteration", "limit", "attempts"))


# ---------------------------------------------------------------------------
# Test 4: agent-error
# ---------------------------------------------------------------------------


def test_explain_receipt_agent_error() -> None:
    """agent-error stop_reason should produce NOT VERIFIED with adapter/API explanation."""
    receipt = _make_receipt(verified=False, stop_reason="agent-error", iterations=0)
    result: ExplainResult = explain_receipt(receipt)

    assert result.verified is False
    assert result.verdict == "NOT VERIFIED"
    expl_lower = result.explanation.lower()
    # Should mention adapter / API / authentication or error
    assert any(kw in expl_lower for kw in ("adapter", "api", "authentication", "error"))


# ---------------------------------------------------------------------------
# Test 5: missing keys default sensibly
# ---------------------------------------------------------------------------


def test_explain_receipt_missing_keys_never_crash() -> None:
    """explain_receipt on an empty dict must not raise; must return safe defaults."""
    result: ExplainResult = explain_receipt({})

    assert isinstance(result, ExplainResult)
    assert result.verified is False
    assert result.stop_reason == ""
    assert result.verdict == "NOT VERIFIED"
    assert isinstance(result.explanation, str)
    assert len(result.explanation) > 0
    assert result.iterations == 0
    assert result.tokens == 0
    assert result.cost_usd is None
    assert result.agent == "unknown"
    assert result.receipt_hash == ""
    assert result.receipt_hash_short == ""


# ---------------------------------------------------------------------------
# Test 6: CLI --json envelope shape
# ---------------------------------------------------------------------------


def test_cli_json_envelope_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``onmc explain --json`` must emit the correct JSON envelope for a verified receipt."""
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    receipts_dir.mkdir(parents=True)
    receipt_data = _make_receipt(verified=True, stop_reason="converged", cost_usd=0.012)
    receipt_file = receipts_dir / "run-aabbccdd-11223344.json"
    receipt_file.write_text(json.dumps(receipt_data), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    with patch(
        "oh_no_my_claudecode.explain.commands.discover_repo_root",
        return_value=tmp_path,
    ):
        runner = _cli_runner()
        inv = runner.invoke(app, ["explain", "--json"])

    assert inv.exit_code == 0, inv.output
    payload = json.loads(inv.output)

    assert payload["kind"] == "explain"
    assert payload["verified"] is True
    assert payload["stop_reason"] == "converged"
    assert isinstance(payload["verdict"], str)
    assert isinstance(payload["explanation"], str)
    assert payload["goal"] == "fix the bug"
    assert isinstance(payload["iterations"], int)
    assert payload["cost_usd"] == pytest.approx(0.012)
    assert isinstance(payload["tokens"], int)
    assert isinstance(payload["receipt"], str)


# ---------------------------------------------------------------------------
# Test 7: No receipts → friendly message, exit 0
# ---------------------------------------------------------------------------


def test_cli_no_receipts_friendly_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When no receipts exist, print a friendly hint and exit 0."""
    monkeypatch.chdir(tmp_path)
    with patch(
        "oh_no_my_claudecode.explain.commands.discover_repo_root",
        return_value=tmp_path,
    ):
        runner = _cli_runner()
        inv = runner.invoke(app, ["explain"])

    assert inv.exit_code == 0, inv.output
    assert "No run receipts yet" in inv.output
    assert "onmc autopilot" in inv.output


# ---------------------------------------------------------------------------
# Test 8: Latest is picked (two receipts with different mtimes)
# ---------------------------------------------------------------------------


def test_cli_latest_receipt_is_picked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When two receipts exist, the one with the most recent mtime is explained."""
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    receipts_dir.mkdir(parents=True)

    older_data = _make_receipt(
        verified=False,
        stop_reason="max-iterations",
        goal="older goal",
        receipt_hash="11111111" + "0" * 56,
    )
    newer_data = _make_receipt(
        verified=True,
        stop_reason="converged",
        goal="newer goal",
        receipt_hash="22222222" + "0" * 56,
    )

    older_file = receipts_dir / "run-aaaaaaaa-11111111.json"
    older_file.write_text(json.dumps(older_data), encoding="utf-8")

    # Ensure the newer file has a strictly later mtime.
    time.sleep(0.05)
    newer_file = receipts_dir / "run-bbbbbbbb-22222222.json"
    newer_file.write_text(json.dumps(newer_data), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    with patch(
        "oh_no_my_claudecode.explain.commands.discover_repo_root",
        return_value=tmp_path,
    ):
        runner = _cli_runner()
        inv = runner.invoke(app, ["explain", "--json"])

    assert inv.exit_code == 0, inv.output
    payload = json.loads(inv.output)
    # The newer receipt (converged, newer goal) should have been selected.
    assert payload["goal"] == "newer goal", (
        f"Expected 'newer goal' but got {payload['goal']!r}. "
        "Likely the oldest receipt was picked instead of the newest."
    )
    assert payload["verified"] is True
