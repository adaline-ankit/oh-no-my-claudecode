"""Tamper-evident run receipt uniting stages, policy, and proof.

The receipt is the single artifact a caller can trust: its ``verified`` flag is
computed, not asserted, and can be recomputed from the embedded evidence. The
invariant is deliberately strict:

    verified  ==  status == "completed"
              and proof_complete
              and policy_outcome == "allow"

so a failed proof or a denied/approval-pending policy can never surface as
verified, no matter what an upstream stage claims.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

_SCHEMA_VERSION = "1"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def compute_verified(
    *,
    status: str,
    proof_complete: bool,
    policy_outcome: str,
) -> bool:
    """The one place ``verified`` is decided — never trust a caller's boolean."""
    return status == "completed" and proof_complete and policy_outcome == "allow"


@dataclass(frozen=True, slots=True)
class RunReceipt:
    """Canonical run receipt whose hash covers every field except itself."""

    schema_version: str
    run_id: str
    status: str
    verified: bool
    stages: tuple[dict[str, object], ...]
    policy: dict[str, object]
    capability_decisions: tuple[dict[str, object], ...]
    proof: dict[str, object]
    receipt_hash: str

    @classmethod
    def build(
        cls,
        *,
        run_id: str,
        status: str,
        proof_complete: bool,
        policy_outcome: str,
        stages: tuple[dict[str, object], ...],
        policy: dict[str, object],
        capability_decisions: tuple[dict[str, object], ...],
        proof: dict[str, object],
    ) -> RunReceipt:
        verified = compute_verified(
            status=status, proof_complete=proof_complete, policy_outcome=policy_outcome
        )
        payload: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "run_id": run_id,
            "status": status,
            "verified": verified,
            "stages": list(stages),
            "policy": policy,
            "capability_decisions": list(capability_decisions),
            "proof": proof,
        }
        return cls(
            schema_version=_SCHEMA_VERSION,
            run_id=run_id,
            status=status,
            verified=verified,
            stages=tuple(stages),
            policy=policy,
            capability_decisions=tuple(capability_decisions),
            proof=proof,
            receipt_hash=_digest(payload),
        )

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "status": self.status,
            "verified": self.verified,
            "stages": list(self.stages),
            "policy": self.policy,
            "capability_decisions": list(self.capability_decisions),
            "proof": self.proof,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_payload(), "receipt_hash": self.receipt_hash}

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, serialized: str) -> RunReceipt:
        if not verify_receipt(serialized):
            raise ValueError("run receipt integrity check failed")
        raw: Any = json.loads(serialized)
        return cls(
            schema_version=str(raw["schema_version"]),
            run_id=str(raw["run_id"]),
            status=str(raw["status"]),
            verified=bool(raw["verified"]),
            stages=tuple(raw["stages"]),
            policy=raw["policy"],
            capability_decisions=tuple(raw["capability_decisions"]),
            proof=raw["proof"],
            receipt_hash=str(raw["receipt_hash"]),
        )


_ENVELOPE_FIELDS = {
    "schema_version",
    "run_id",
    "status",
    "verified",
    "stages",
    "policy",
    "capability_decisions",
    "proof",
}


def verify_receipt(serialized: str) -> bool:
    """Return whether canonical receipt content matches its embedded SHA-256.

    Also re-derives ``verified`` from the embedded status/proof/policy so a
    hand-edited receipt that flips ``verified`` to true fails the check even if
    its author recomputed the hash.
    """
    try:
        raw: Any = json.loads(serialized)
        if not isinstance(raw, dict):
            return False
        claimed = raw.pop("receipt_hash", None)
        if not isinstance(claimed, str) or len(claimed) != 64:
            return False
        if set(raw) != _ENVELOPE_FIELDS or raw["schema_version"] != _SCHEMA_VERSION:
            return False
        proof = raw.get("proof")
        proof_complete = bool(proof.get("complete")) if isinstance(proof, dict) else False
        policy = raw.get("policy")
        policy_outcome = str(policy.get("outcome")) if isinstance(policy, dict) else ""
        expected_verified = compute_verified(
            status=str(raw.get("status")),
            proof_complete=proof_complete,
            policy_outcome=policy_outcome,
        )
        if bool(raw.get("verified")) != expected_verified:
            return False
        return _digest(raw) == claimed
    except (AttributeError, TypeError, ValueError):
        return False


__all__ = ["RunReceipt", "compute_verified", "verify_receipt"]
