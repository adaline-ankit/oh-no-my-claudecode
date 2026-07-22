"""Stable, tamper-evident serialization for proof-graph assessments."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from oh_no_my_claudecode.proof_graph.models import (
    Evidence,
    ProofAssessment,
    ProofGraph,
    VerifierResult,
)

_SCHEMA_VERSION = "1"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _valid_envelope(payload: dict[str, object]) -> bool:
    """Validate the fixed schema before treating a matching digest as a receipt."""
    if set(payload) != {"schema_version", "graph", "assessment", "results", "evidence"}:
        return False
    if payload["schema_version"] != _SCHEMA_VERSION:
        return False
    if not isinstance(payload["graph"], dict) or not isinstance(payload["assessment"], dict):
        return False
    if not isinstance(payload["results"], list) or not isinstance(payload["evidence"], list):
        return False
    assessment = payload["assessment"]
    return set(assessment) == {"complete", "false_green", "reasons"} and isinstance(
        assessment["reasons"], list
    )


def _graph_payload(graph: ProofGraph) -> dict[str, object]:
    return {
        "task": {
            "task_id": graph.task.task_id,
            "summary": graph.task.summary,
            "kind": graph.task.kind.value,
            "claims": [
                {
                    "claim_id": claim.claim_id,
                    "statement": claim.statement,
                    "kind": claim.kind.value,
                }
                for claim in sorted(graph.claims, key=lambda item: item.claim_id)
            ],
        },
        "risk": {
            "security": graph.risk.security,
            "browser": graph.risk.browser,
            "performance": graph.risk.performance,
        },
        "diff": {
            "changed_files": sorted(graph.diff.changed_files),
            "languages": sorted(graph.diff.languages),
        },
        "verifiers": [
            {
                "verifier_id": node.verifier_id,
                "kind": node.kind.value,
                "argv": list(node.argv),
                "expected_outcome": node.expected_outcome.value,
                "dependencies": list(node.dependencies),
            }
            for node in graph.verifiers
        ],
    }


def _assessment_payload(assessment: ProofAssessment) -> dict[str, object]:
    return {
        "complete": assessment.complete,
        "false_green": assessment.false_green,
        "reasons": list(assessment.reasons),
    }


def _result_payload(result: VerifierResult) -> dict[str, object]:
    return {
        "verifier_id": result.verifier_id,
        "outcome": result.outcome.value,
        "evidence_ids": sorted(result.evidence_ids),
    }


def _evidence_payload(evidence: Evidence) -> dict[str, object]:
    return {
        "evidence_id": evidence.evidence_id,
        "verifier_id": evidence.verifier_id,
        "outcome": evidence.outcome.value,
        "artifact_digest": evidence.artifact_digest,
        "claim_ids": sorted(evidence.claim_ids),
        "source": evidence.source.value,
    }


@dataclass(frozen=True, slots=True)
class ProofReceipt:
    """Canonical proof receipt whose hash covers every field except itself."""

    schema_version: str
    graph: dict[str, object]
    assessment: dict[str, object]
    results: tuple[dict[str, object], ...]
    evidence: tuple[dict[str, object], ...]
    receipt_hash: str

    @classmethod
    def build(
        cls,
        graph: ProofGraph,
        assessment: ProofAssessment,
        results: tuple[VerifierResult, ...],
        evidence: tuple[Evidence, ...],
    ) -> ProofReceipt:
        """Build a receipt deterministically, independent of result input order."""
        payload: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "graph": _graph_payload(graph),
            "assessment": _assessment_payload(assessment),
            "results": [
                _result_payload(result)
                for result in sorted(results, key=lambda item: item.verifier_id)
            ],
            "evidence": [
                _evidence_payload(item)
                for item in sorted(evidence, key=lambda item: item.evidence_id)
            ],
        }
        return cls(
            schema_version=_SCHEMA_VERSION,
            graph=payload["graph"],  # type: ignore[arg-type]
            assessment=payload["assessment"],  # type: ignore[arg-type]
            results=tuple(payload["results"]),  # type: ignore[arg-type]
            evidence=tuple(payload["evidence"]),  # type: ignore[arg-type]
            receipt_hash=_digest(payload),
        )

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "graph": self.graph,
            "assessment": self.assessment,
            "results": list(self.results),
            "evidence": list(self.evidence),
        }

    def to_json(self) -> str:
        """Serialize to byte-stable canonical JSON."""
        return _canonical_json({**self._unsigned_payload(), "receipt_hash": self.receipt_hash})

    @classmethod
    def from_json(cls, serialized: str) -> ProofReceipt:
        """Parse a receipt and reject malformed or tampered content."""
        if not verify_receipt(serialized):
            raise ValueError("proof receipt integrity check failed")
        raw: Any = json.loads(serialized)
        return cls(
            schema_version=str(raw["schema_version"]),
            graph=raw["graph"],
            assessment=raw["assessment"],
            results=tuple(raw["results"]),
            evidence=tuple(raw["evidence"]),
            receipt_hash=str(raw["receipt_hash"]),
        )


def verify_receipt(serialized: str) -> bool:
    """Return whether canonical receipt content matches its embedded SHA-256."""
    try:
        raw: Any = json.loads(serialized)
        if not isinstance(raw, dict):
            return False
        claimed = raw.pop("receipt_hash", None)
        if not isinstance(claimed, str) or len(claimed) != 64:
            return False
        return _valid_envelope(raw) and _digest(raw) == claimed
    except (TypeError, ValueError, KeyError):
        return False
