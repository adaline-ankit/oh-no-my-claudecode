"""H9 demo — the full self-improvement loop is provable, deterministic, sealed."""

from __future__ import annotations

import hashlib

import pytest

from oh_no_my_claudecode.demo.self_improvement import run_demo
from oh_no_my_claudecode.harness_run.attestation import Envelope, verify_envelope_payload


@pytest.fixture(autouse=True)
def _learning_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The demo requires the learning kill switch in its default ON state."""
    monkeypatch.delenv("ONMC_LEARNING", raising=False)


def test_full_loop_promotes_workflow_and_blocks_poison() -> None:
    result = run_demo()

    assert result["workflows_mined"] == 1
    assert result["promoted"] is True
    assert result["poison_admitted"] is False

    verdicts = {entry["memory_id"]: entry["verdict"] for entry in result["ledger"]}
    assert verdicts == {"workflow": "earning", "poison": "harmful"}
    # Poison was measured harmful but never admitted, so nothing was retired.
    assert result["retired"] == []

    evolution = result["evolution"]
    assert evolution["promoted"] is True
    assert evolution["winner_id"] == "challenger-workflow"
    assert evolution["delta_ci95"][0] > 0

    assert result["attested"] is True
    narrative = result["narrative"]
    assert narrative and all(isinstance(line, str) and "\n" not in line for line in narrative)


def test_demo_is_deterministic() -> None:
    first, second = run_demo(seed=7), run_demo(seed=7)
    assert first["narrative"] == second["narrative"]
    assert first == second  # the whole outcome, envelope included, is byte-identical


def test_attestation_binding_verifies() -> None:
    result = run_demo()
    summary_hash = hashlib.sha256(result["evolution"]["record_hash"].encode()).hexdigest()
    envelope_dict = result["envelope"]
    envelope = Envelope(
        payload_b64=envelope_dict["payload"],
        payload_type=envelope_dict["payloadType"],
        signatures=tuple(envelope_dict["signatures"]),
    )
    assert verify_envelope_payload(envelope, expected_receipt_hash=summary_hash)
    assert not verify_envelope_payload(envelope, expected_receipt_hash="0" * 64)
