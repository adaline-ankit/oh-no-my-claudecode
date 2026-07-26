"""Composed, tamper-evident receipt for one harness run.

Where ``loop.receipt`` records the mechanical loop and ``proof_graph.receipt``
records the proof graph, this receipt binds the two together with the run's
policy verdict, the canonical runtime contract, and the six typed stage records.
Its single most important field is :attr:`HarnessRunReceipt.verified`, computed
by :func:`compute_verified` — the one place that decides whether a run may
honestly claim success.

Invariant: ``verified`` is ``True`` only when the run completed, all canonical
harness stages succeeded, the runtime contract is complete, the proof is complete
and not false-green, the policy allowed the change, and no human approval is
outstanding. A failed proof or partial stage/contract set can never report
verified.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from oh_no_my_claudecode.proof_graph import ProofAssessment
from oh_no_my_claudecode.runtime.contracts import RunSpec, RuntimeContractError

from .run_policy import RunPolicyDecision
from .stages import StageName, StageRecord, StageStatus

_SCHEMA_VERSION = "1"


def compute_verified(
    *,
    completed: bool,
    proof: ProofAssessment,
    policy: RunPolicyDecision,
    stages: tuple[StageRecord, ...] = (),
    runtime_contract: dict[str, object] | None = None,
    runtime_contract_digest: str | None = None,
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
        and stages_complete(stages)
        and runtime_contract_complete(runtime_contract, runtime_contract_digest)
    )


def stages_complete(stages: tuple[StageRecord, ...]) -> bool:
    """Return whether a receipt carries the full successful harness stage set."""
    names = tuple(stage.name for stage in stages)
    return names == tuple(StageName) and all(
        stage.status is StageStatus.SUCCEEDED for stage in stages
    )


def runtime_contract_complete(
    runtime_contract: dict[str, object] | None,
    runtime_contract_digest: str | None,
) -> bool:
    """Return whether the receipt carries a valid canonical runtime spec."""
    if runtime_contract is None or runtime_contract_digest is None:
        return False
    try:
        spec = RunSpec.from_dict(runtime_contract)
    except RuntimeContractError:
        return False
    return spec.digest == runtime_contract_digest


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
    runtime_contract: dict[str, object]
    runtime_contract_digest: str
    stages: tuple[dict[str, object], ...]
    policy: dict[str, object]
    proof: dict[str, object]
    report_coverage: dict[str, object]
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
        runtime_contract: dict[str, object],
        policy: RunPolicyDecision,
        proof: ProofAssessment,
        report_coverage: dict[str, object],
    ) -> HarnessRunReceipt:
        runtime_spec = RunSpec.from_dict(runtime_contract)
        runtime_payload = runtime_spec.to_dict()
        runtime_digest = runtime_spec.digest
        verified = compute_verified(
            completed=completed,
            proof=proof,
            policy=policy,
            stages=stages,
            runtime_contract=runtime_payload,
            runtime_contract_digest=runtime_digest,
        )
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
            "runtime_contract": runtime_payload,
            "runtime_contract_digest": runtime_digest,
            "stages": list(stage_payload),
            "policy": policy_payload,
            "proof": proof_payload,
            "report_coverage": report_coverage,
        }
        return cls(
            schema_version=_SCHEMA_VERSION,
            run_id=run_id,
            task=task,
            status=status,
            verified=verified,
            runtime_contract=runtime_payload,
            runtime_contract_digest=runtime_digest,
            stages=stage_payload,
            policy=policy_payload,
            proof=proof_payload,
            report_coverage=report_coverage,
            receipt_hash=_digest(body),
        )

    def _unsigned(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "task": self.task,
            "status": self.status,
            "verified": self.verified,
            "runtime_contract": self.runtime_contract,
            "runtime_contract_digest": self.runtime_contract_digest,
            "stages": list(self.stages),
            "policy": self.policy,
            "proof": self.proof,
            "report_coverage": self.report_coverage,
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
        "runtime_contract",
        "runtime_contract_digest",
        "stages",
        "policy",
        "proof",
        "report_coverage",
    }
    legacy_keys = expected_keys - {"report_coverage"}
    raw_keys = set(raw)
    if raw_keys != expected_keys and raw_keys != legacy_keys:
        return False
    return _digest(raw) == claimed


def harness_receipt_path(repo_root: Path, run_id: str) -> Path:
    """Return the canonical persisted harness receipt path for *run_id*."""
    return repo_root / ".agent-memory" / "receipts" / f"run-{run_id}.json"


def load_harness_receipt(repo_root: Path, run_id: str) -> HarnessRunReceipt | None:
    """Load and validate the persisted harness receipt for *run_id*.

    The on-disk file is a user-facing wrapper with the canonical harness receipt
    nested under ``harness``. A resumed completed run may trust that state only
    when the nested receipt is present, matches its hash, is for the requested
    run, and is marked verified.
    """
    path = harness_receipt_path(repo_root, run_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    nested = raw.get("harness")
    if not isinstance(nested, dict):
        return None
    serialized = _canonical_json(nested)
    if not verify_harness_receipt(serialized):
        return None
    receipt = _coerce_harness_receipt(nested)
    if (
        receipt is None
        or receipt.run_id != run_id
        or not receipt.verified
        or not _serialized_stages_complete(receipt.stages)
        or not _serialized_runtime_contract_complete(
            receipt.runtime_contract,
            receipt.runtime_contract_digest,
            run_id=receipt.run_id,
            task=receipt.task,
        )
    ):
        return None
    return receipt


def _coerce_harness_receipt(raw: dict[str, object]) -> HarnessRunReceipt | None:
    try:
        schema_version = raw["schema_version"]
        run_id = raw["run_id"]
        task = raw["task"]
        status = raw["status"]
        verified = raw["verified"]
        runtime_contract = raw["runtime_contract"]
        runtime_contract_digest = raw["runtime_contract_digest"]
        stages = raw["stages"]
        policy = raw["policy"]
        proof = raw["proof"]
        report_coverage = raw.get("report_coverage", _legacy_report_coverage())
        receipt_hash = raw["receipt_hash"]
    except KeyError:
        return None
    if not (
        isinstance(schema_version, str)
        and isinstance(run_id, str)
        and isinstance(task, str)
        and isinstance(status, str)
        and isinstance(verified, bool)
        and isinstance(runtime_contract, dict)
        and isinstance(runtime_contract_digest, str)
        and isinstance(stages, list)
        and isinstance(policy, dict)
        and isinstance(proof, dict)
        and isinstance(report_coverage, dict)
        and isinstance(receipt_hash, str)
    ):
        return None
    stage_payload: list[dict[str, object]] = []
    for stage in stages:
        if not isinstance(stage, dict):
            return None
        stage_payload.append(stage)
    return HarnessRunReceipt(
        schema_version=schema_version,
        run_id=run_id,
        task=task,
        status=status,
        verified=verified,
        runtime_contract=runtime_contract,
        runtime_contract_digest=runtime_contract_digest,
        stages=tuple(stage_payload),
        policy=policy,
        proof=proof,
        report_coverage=report_coverage,
        receipt_hash=receipt_hash,
    )


def _legacy_report_coverage() -> dict[str, object]:
    return {
        "schema_version": "1",
        "covered_count": 0,
        "missing_count": 1,
        "claim_ready": False,
        "fields": [
            {
                "name": "report_coverage",
                "covered": False,
                "source": "legacy receipt",
                "reason": "receipt predates report coverage manifests",
            }
        ],
    }


def _serialized_stages_complete(stages: tuple[dict[str, object], ...]) -> bool:
    names = tuple(stage.get("name") for stage in stages)
    expected = tuple(stage.value for stage in StageName)
    return names == expected and all(
        stage.get("status") == StageStatus.SUCCEEDED.value for stage in stages
    )


def _serialized_runtime_contract_complete(
    runtime_contract: dict[str, object],
    runtime_contract_digest: str,
    *,
    run_id: str,
    task: str,
) -> bool:
    try:
        spec = RunSpec.from_dict(runtime_contract)
    except RuntimeContractError:
        return False
    return (
        spec.digest == runtime_contract_digest
        and spec.run_id == run_id
        and spec.task == task
    )


__all__ = [
    "HarnessRunReceipt",
    "compute_verified",
    "harness_receipt_path",
    "load_harness_receipt",
    "runtime_contract_complete",
    "stages_complete",
    "verify_harness_receipt",
]
