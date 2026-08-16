"""CLI tests for the research-layer read-only commands.

Covers ``onmc ledger workflows`` (procedural distillation over receipts),
``onmc corpus-health`` (A/B report hygiene audit), and ``onmc attest-verify``
(DSSE envelope ↔ receipt-hash binding). All offline — no LLM calls, no
network. Exercised through the Typer app via CliRunner, matching the repo's
existing CLI-test pattern.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.harness_run.attestation import attest_receipt

_RUNNER = CliRunner()

_WORKFLOW = [
    "reproduce the bug with a failing test in tests/test_auth.py",
    "trace the root cause in src/auth.py",
    "apply the fix and rerun pytest 3 times",
]
_WORKFLOW_VARIANT = [
    "reproduce the bug with a failing test in tests/test_billing.py",
    "trace the root cause in lib/billing.py",
    "apply the fix and rerun pytest 12 times",
]


def _write_receipt(tmp_path: Path, name: str, actions: list[str], *, verified: bool) -> None:
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    (receipts_dir / name).write_text(
        json.dumps(
            {
                "receipt_hash": name,
                "verified": verified,
                "iterations": [{"action_summary": action} for action in actions],
            }
        ),
        encoding="utf-8",
    )


def _write_report(tmp_path: Path) -> Path:
    """A minimal ABReport.to_dict()-shaped JSON with one task per verdict."""
    report: dict[str, Any] = {
        "comparisons": [
            {"task_id": "sat-task", "alone": {"passed": True}, "onmc": {"passed": True}},
            {"task_id": "dead-task", "alone": {"passed": False}, "onmc": {"passed": False}},
            {"task_id": "disc-task", "alone": {"passed": False}, "onmc": {"passed": True}},
        ]
    }
    path = tmp_path / "ab-report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _write_envelope(tmp_path: Path, receipt_hash: str) -> Path:
    envelope = attest_receipt(
        {"receipt_hash": receipt_hash, "verified": True},
        repo="acme/api",
        tree_sha256="a" * 64,
    )
    path = tmp_path / "envelope.json"
    path.write_text(json.dumps(envelope.to_dict()), encoding="utf-8")
    return path


def test_ledger_workflows_mines_verified_receipts_only(tmp_path: Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    _write_receipt(tmp_path, "run-a.json", _WORKFLOW, verified=True)
    _write_receipt(tmp_path, "run-b.json", _WORKFLOW_VARIANT, verified=True)
    _write_receipt(tmp_path, "run-c.json", _WORKFLOW, verified=False)  # never teaches

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["ledger", "workflows", "--json"], catch_exceptions=False)
    finally:
        os.chdir(orig)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["support"] == 2  # the unverified receipt is excluded
    assert len(payload[0]["steps"]) == 3
    assert payload[0]["id"]


def test_ledger_workflows_empty_state_exits_zero(tmp_path: Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["ledger", "workflows"], catch_exceptions=False)
    finally:
        os.chdir(orig)

    assert result.exit_code == 0, result.output
    assert "No recurring workflows" in result.output


def test_corpus_health_flags_saturated_dead_discriminating(tmp_path: Path) -> None:
    path = _write_report(tmp_path)

    result = _RUNNER.invoke(app, ["corpus-health", str(path), "--json"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["saturated"] == ["sat-task"]
    assert payload["dead"] == ["dead-task"]
    assert payload["discriminating_ratio"] == 0.333

    text = _RUNNER.invoke(app, ["corpus-health", str(path)], catch_exceptions=False)
    assert text.exit_code == 0, text.output
    assert "sat-task" in text.output
    assert "dead-task" in text.output

    missing = _RUNNER.invoke(app, ["corpus-health", str(tmp_path / "nope.json")])
    assert missing.exit_code == 1


def test_attest_verify_passes_on_matching_hash(tmp_path: Path) -> None:
    path = _write_envelope(tmp_path, "deadbeef")
    result = _RUNNER.invoke(app, ["attest-verify", str(path), "deadbeef"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "verified: true" in result.output


def test_attest_verify_fails_closed(tmp_path: Path) -> None:
    path = _write_envelope(tmp_path, "deadbeef")
    mismatch = _RUNNER.invoke(app, ["attest-verify", str(path), "wrong-hash"])
    assert mismatch.exit_code == 1
    assert "verified: false" in mismatch.output

    garbage = tmp_path / "garbage.json"
    garbage.write_text(
        json.dumps({"payload": "!!!not-base64", "payloadType": "x", "signatures": []}),
        encoding="utf-8",
    )
    broken = _RUNNER.invoke(app, ["attest-verify", str(garbage), "deadbeef"])
    assert broken.exit_code == 1
    assert "verified: false" in broken.output
