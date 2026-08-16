"""Receipts as standards-grade provenance: in-toto Statements in DSSE envelopes.

The supply-chain world already built the attestation rails (in-toto v1
Statements, DSSE envelopes, Sigstore identities, SLSA policy engines). Instead
of inventing a signing scheme, ONMC receipts ride them: this module wraps a
:class:`~.receipt.HarnessRunReceipt` as an in-toto Statement whose subject is
the run's repo tree, with the full receipt as the predicate — the same shape
``cosign attest`` and ``gh attestation verify`` consume.

Positioning in one line: SLSA proves how software was *built*; ONMC
attestations prove how agent changes were *verified*.

Signing is injected (Signer protocol). Without a signer the envelope is
explicitly UNSIGNED — never silently trusted, matching the project's
fail-closed posture everywhere else.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

#: in-toto attestation framework Statement type (v1).
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"

#: DSSE payload type for in-toto payloads.
PAYLOAD_TYPE = "application/vnd.in-toto+json"

#: ONMC's predicate type — versioned, so verifiers can pin semantics.
PREDICATE_TYPE = "https://onmc.dev/attestations/run-receipt/v1"


class Signer(Protocol):
    """Detached signer over DSSE PAE bytes (e.g. sigstore, minisign, KMS)."""

    keyid: str

    def sign(self, message: bytes) -> bytes:
        """Return the raw signature over *message*."""
        ...


def _pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE Pre-Authentication Encoding — what signers actually sign."""
    return b" ".join(
        [
            b"DSSEv1",
            str(len(payload_type)).encode(),
            payload_type.encode(),
            str(len(payload)).encode(),
            payload,
        ]
    )


def build_statement(
    receipt: Mapping[str, object], *, repo: str, tree_sha256: str
) -> dict[str, object]:
    """Wrap a receipt dict as an in-toto v1 Statement.

    ``subject`` is the repository tree the run left behind (name + sha256), so
    policy engines can bind "this tree state" to "this verification evidence".
    """
    if not tree_sha256 or len(tree_sha256) != 64:
        raise ValueError("tree_sha256 must be a 64-char sha256 hex digest")
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": repo, "digest": {"sha256": tree_sha256}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": dict(receipt),
    }


@dataclass(frozen=True, slots=True)
class Envelope:
    """A DSSE envelope; ``signed`` is honest, never assumed."""

    payload_b64: str
    payload_type: str
    signatures: tuple[dict[str, str], ...]

    @property
    def signed(self) -> bool:
        return bool(self.signatures)

    def to_dict(self) -> dict[str, object]:
        return {
            "payloadType": self.payload_type,
            "payload": self.payload_b64,
            "signatures": [dict(s) for s in self.signatures],
            # Non-standard but honest: consumers must not treat an unsigned
            # envelope as attested. Standard verifiers ignore unknown keys.
            "onmcSigned": self.signed,
        }

    def statement(self) -> dict[str, object]:
        """Decode the embedded in-toto Statement."""
        decoded = json.loads(base64.b64decode(self.payload_b64))
        if not isinstance(decoded, dict):
            raise ValueError("envelope payload is not a JSON object")
        return decoded


def attest_receipt(
    receipt: Mapping[str, object],
    *,
    repo: str,
    tree_sha256: str,
    signer: Signer | None = None,
) -> Envelope:
    """Build the DSSE envelope for a run receipt; sign it when a signer exists.

    ponytail: sigstore keyless signing is the upgrade path — inject it via the
    Signer protocol rather than adding the dependency here.
    """
    statement = build_statement(receipt, repo=repo, tree_sha256=tree_sha256)
    payload = json.dumps(statement, sort_keys=True, separators=(",", ":")).encode()
    signatures: tuple[dict[str, str], ...] = ()
    if signer is not None:
        raw = signer.sign(_pae(PAYLOAD_TYPE, payload))
        signatures = ({"keyid": signer.keyid, "sig": base64.b64encode(raw).decode()},)
    return Envelope(
        payload_b64=base64.b64encode(payload).decode(),
        payload_type=PAYLOAD_TYPE,
        signatures=signatures,
    )


def verify_envelope_payload(envelope: Envelope, *, expected_receipt_hash: str) -> bool:
    """Offline structural check: the envelope really carries THIS receipt.

    Signature verification belongs to the signer's ecosystem (cosign/rekor);
    this guards the binding between envelope and receipt hash so a swapped
    payload is caught even before cryptographic verification.
    """
    try:
        statement = envelope.statement()
    except (ValueError, json.JSONDecodeError):
        return False
    if statement.get("_type") != STATEMENT_TYPE:
        return False
    if statement.get("predicateType") != PREDICATE_TYPE:
        return False
    predicate = statement.get("predicate")
    if not isinstance(predicate, dict):
        return False
    return predicate.get("receipt_hash") == expected_receipt_hash


__all__ = [
    "PAYLOAD_TYPE",
    "PREDICATE_TYPE",
    "STATEMENT_TYPE",
    "Envelope",
    "Signer",
    "attest_receipt",
    "build_statement",
    "verify_envelope_payload",
]
