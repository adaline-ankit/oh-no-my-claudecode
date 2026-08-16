"""Receipt attestation: in-toto shape, honest unsigned flag, tamper binding."""

from __future__ import annotations

import base64
import json

from oh_no_my_claudecode.harness_run.attestation import (
    PAYLOAD_TYPE,
    PREDICATE_TYPE,
    STATEMENT_TYPE,
    Envelope,
    attest_receipt,
    verify_envelope_payload,
)

RECEIPT = {"schema_version": "2", "verified": True, "receipt_hash": "a" * 64}
TREE = "b" * 64


class _FakeSigner:
    keyid = "test-key"

    def __init__(self) -> None:
        self.saw: bytes = b""

    def sign(self, message: bytes) -> bytes:
        self.saw = message
        return b"sig-bytes"


def test_envelope_is_intoto_dsse_shaped_and_binds_the_receipt() -> None:
    env = attest_receipt(RECEIPT, repo="acme/api", tree_sha256=TREE)
    stmt = env.statement()
    assert stmt["_type"] == STATEMENT_TYPE
    assert stmt["predicateType"] == PREDICATE_TYPE
    assert stmt["subject"] == [{"name": "acme/api", "digest": {"sha256": TREE}}]
    assert env.payload_type == PAYLOAD_TYPE
    assert env.signed is False  # no signer -> honestly unsigned
    assert env.to_dict()["onmcSigned"] is False
    assert verify_envelope_payload(env, expected_receipt_hash="a" * 64)


def test_signer_sees_dsse_pae_and_signature_lands_in_envelope() -> None:
    signer = _FakeSigner()
    env = attest_receipt(RECEIPT, repo="acme/api", tree_sha256=TREE, signer=signer)
    assert env.signed is True
    assert env.signatures[0]["keyid"] == "test-key"
    assert signer.saw.startswith(b"DSSEv1 ")  # PAE, not raw payload
    assert base64.b64decode(env.signatures[0]["sig"]) == b"sig-bytes"


def test_swapped_payload_fails_the_binding_check() -> None:
    env = attest_receipt(RECEIPT, repo="acme/api", tree_sha256=TREE)
    other = json.dumps(
        {
            "_type": STATEMENT_TYPE,
            "predicateType": PREDICATE_TYPE,
            "subject": [],
            "predicate": {"receipt_hash": "c" * 64},
        }
    ).encode()
    forged = Envelope(
        payload_b64=base64.b64encode(other).decode(),
        payload_type=PAYLOAD_TYPE,
        signatures=env.signatures,
    )
    assert verify_envelope_payload(forged, expected_receipt_hash="a" * 64) is False
