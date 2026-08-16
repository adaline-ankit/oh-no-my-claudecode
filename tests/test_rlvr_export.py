"""RLVR export: gate verdicts become rewards, ambiguity is excluded, provenance seals."""

from __future__ import annotations

import json

from oh_no_my_claudecode.evals.rlvr_export import attest_dataset, export_rlvr
from oh_no_my_claudecode.harness_run.attestation import verify_envelope_payload


def _receipt(rid: str, verified: object, goal: str = "fix the webhook") -> dict[str, object]:
    return {
        "receipt_hash": rid,
        "verified": verified,
        "goal": goal,
        "iterations": [{"action_summary": "reproduce"}, {"action_summary": "fix"}],
    }


def test_rewards_come_from_the_gate_and_ambiguity_is_excluded() -> None:
    dataset = export_rlvr(
        [
            _receipt("r1", True),
            _receipt("r2", False),  # honest failure -> reward 0.0, kept
            _receipt("r3", "yes"),  # non-boolean verdict -> excluded, never guessed
            _receipt("r4", True, goal=""),  # no prompt -> excluded
        ],
        repo="acme/api",
    )
    assert len(dataset.records) == 2 and dataset.excluded == 2
    rewards = {r["source_receipt"]: r["reward"] for r in dataset.records}
    assert rewards == {"r1": 1.0, "r2": 0.0}
    assert dataset.n_positive == 1


def test_jsonl_round_trips_and_digest_is_deterministic() -> None:
    receipts = [_receipt("r1", True), _receipt("r2", False)]
    a = export_rlvr(receipts, repo="acme/api")
    b = export_rlvr(receipts, repo="acme/api")
    assert a.digest == b.digest and len(a.digest) == 64
    lines = [json.loads(line) for line in a.to_jsonl().splitlines()]
    assert lines[0]["trajectory"] == ["reproduce", "fix"]


def test_dataset_attestation_binds_the_digest() -> None:
    dataset = export_rlvr([_receipt("r1", True)], repo="acme/api")
    envelope = attest_dataset(dataset, repo="acme/api")
    assert verify_envelope_payload(envelope, expected_receipt_hash=dataset.digest)
    assert envelope.signed is False  # honest until a signer is injected
