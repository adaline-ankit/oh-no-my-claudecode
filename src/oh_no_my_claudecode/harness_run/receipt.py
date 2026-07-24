"""Composed, tamper-evident receipt for one harness run.

Where ``loop.receipt`` records the mechanical loop and ``proof_graph.receipt``
records the proof graph, this receipt binds the two together with the run's
policy verdict and the six typed stage records. Its single most important field
is :attr:`HarnessRunReceipt.verified`, computed by :func:`compute_verified` — the
one place that decides whether a run may honestly claim success.

Invariant: ``verified`` is ``True`` only when the run completed, the proof is
complete and not false-green, the policy allowed the change, and no human
approval is outstanding. A failed proof can never report verified.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from oh_no_my_claudecode.proof_graph import ProofAssessment

from .run_policy import RunPolicyDecision
from .stages import StageRecord

_SCHEMA_VERSION = "1"


def compute_verified(
    *,
    completed: bool,
    proof: ProofAssessment,
    policy: RunPolicyDecision,
) -> bool:
    """The sole authority on whether a run is verified.

    Every guard must hold simultaneously; any single failure yields ``False``.
    """
    return (
        completed
        and proof.complete
        and not proof.false_green
        and policy.allowed
        and not policy.approvals_required
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class HarnessRunReceipt:
    """Canonical harness-run receipt whose hash covers every field but itself."""

    schema_version: str
    run_id: str
    task: str
    status: str
    verified: bool
    stages: tuple[dict[str, object], ...]
    policy: dict[str, object]
    proof: dict[str, object]
    receipt_hash: str

    @classmethod
    def build(
        cls,
        *,
        run_id: str,
        task: str,
        status: str,
        completed: bool,
        stages: tuple[StageRecord, ...],
        policy: RunPolicyDecision,
        proof: ProofAssessment,
    ) -> HarnessRunReceipt:
        verified = compute_verified(completed=completed, proof=proof, policy=policy)
        proof_payload: dict[str, object] = {
            "complete": proof.complete,
            "false_green": proof.false_green,
            "reasons": list(proof.reasons),
        }
        stage_payload = tuple(stage.to_dict() for stage in stages)
        policy_payload = policy.to_dict()
        body: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "run_id": run_id,
            "task": task,
            "status": status,
            "verified": verified,
            "stages": list(stage_payload),
            "policy": policy_payload,
            "proof": proof_payload,
        }
        return cls(
            schema_version=_SCHEMA_VERSION,
            run_id=run_id,
            task=task,
            status=status,
            verified=verified,
            stages=stage_payload,
            policy=policy_payload,
            proof=proof_payload,
            receipt_hash=_digest(body),
        )

    def _unsigned(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "task": self.task,
            "status": self.status,
            "verified": self.verified,
            "stages": list(self.stages),
            "policy": self.policy,
            "proof": self.proof,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned(), "receipt_hash": self.receipt_hash}

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


def verify_harness_receipt(serialized: str) -> bool:
    """Return whether a serialized harness receipt matches its embedded hash."""
    try:
        raw = json.loads(serialized)
    except (TypeError, ValueError):
        return False
    if not isinstance(raw, dict):
        return False
    claimed = raw.pop("receipt_hash", None)
    if not isinstance(claimed, str) or len(claimed) != 64:
        return False
    expected_keys = {
        "schema_version",
        "run_id",
        "task",
        "status",
        "verified",
        "stages",
        "policy",
        "proof",
    }
    if set(raw) != expected_keys:
        return False
    return _digest(raw) == claimed


__all__ = [
    "HarnessRunReceipt",
    "compute_verified",
    "verify_harness_receipt",
]
