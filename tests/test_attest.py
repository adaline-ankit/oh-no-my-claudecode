"""Pure tests for the attestation + reputation core.

No filesystem or real environment dependency: secrets are passed explicitly (or
the ``ONMC_ATTEST_SECRET`` env var is monkeypatched), and receipts are fabricated
dicts. Covers the sign→verify roundtrip, tamper detection, the unsigned digest
path, wrong-secret rejection, and the reputation math (including empty input).
"""

from __future__ import annotations

from typing import Any

from oh_no_my_claudecode.attest.attest import (
    Attestation,
    build_attestation,
    build_reputation,
    canonical_claim,
    sign_claim,
    verify_attestation,
)

_SECRET = "topsecret"  # noqa: S105 - test fixture secret, not a real credential


def _receipt(**overrides: Any) -> dict[str, Any]:
    """A representative receipt dict; override individual fields per test."""
    base: dict[str, Any] = {
        "goal": "FIX mission greenfield-decomposition flaw",
        "agent": "claude-code-subagent",
        "verified": True,
        "git_tree_sha": "4643bb645c9f0743c88b910faf48e0d57e93bb97",
        "diff_sha": "2266318bb393432f677a7b7955389f0076fbdbe6",
        "receipt_hash": "e161389262c58e22894ce258d7b69b0c9b0291883cbea5704f95cce90823b913",
        "started_at": "2026-07-04T08:58:34.607111+00:00",
        "ended_at": "2026-07-04T08:58:34.607111+00:00",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# canonical_claim
# ---------------------------------------------------------------------------


def test_canonical_claim_shape_and_fallbacks() -> None:
    claim = canonical_claim(_receipt())
    assert claim["subject"] == "claude-code-subagent"
    assert claim["verified"] is True
    assert claim["ts"] == "2026-07-04T08:58:34.607111+00:00"  # ended_at preferred

    # No agent → subject falls back to "onmc"; missing hashes surface as None.
    sparse = canonical_claim({"goal": "x"})
    assert sparse["subject"] == "onmc"
    assert sparse["git_tree_sha"] is None
    assert sparse["verified"] is False
    assert sparse["ts"] is None


# ---------------------------------------------------------------------------
# sign → verify roundtrip (signed)
# ---------------------------------------------------------------------------


def test_sign_verify_roundtrip_true_with_secret() -> None:
    att = build_attestation(_receipt(), secret=_SECRET)
    assert att.signed is True
    assert att.alg == "HMAC-SHA256"
    assert verify_attestation(att, _SECRET) is True


def test_verify_accepts_dict_form() -> None:
    att = build_attestation(_receipt(), secret=_SECRET)
    assert verify_attestation(att.to_dict(), _SECRET) is True


def test_to_dict_from_dict_roundtrip() -> None:
    att = build_attestation(_receipt(), secret=_SECRET)
    rebuilt = Attestation.from_dict(att.to_dict())
    assert rebuilt == att
    assert verify_attestation(rebuilt, _SECRET) is True


# ---------------------------------------------------------------------------
# tamper detection
# ---------------------------------------------------------------------------


def test_tampered_claim_fails_verify() -> None:
    att = build_attestation(_receipt(), secret=_SECRET)
    tampered = att.to_dict()
    tampered["claim"]["verified"] = False  # flip an attested fact
    assert verify_attestation(tampered, _SECRET) is False


def test_tampered_hash_fails_verify() -> None:
    att = build_attestation(_receipt(), secret=_SECRET)
    tampered = att.to_dict()
    tampered["claim"]["diff_sha"] = "deadbeef"
    assert verify_attestation(tampered, _SECRET) is False


# ---------------------------------------------------------------------------
# wrong / missing secret
# ---------------------------------------------------------------------------


def test_wrong_secret_fails_verify() -> None:
    att = build_attestation(_receipt(), secret=_SECRET)
    assert verify_attestation(att, "not-the-secret") is False


def test_signed_without_secret_fails_verify(monkeypatch: Any) -> None:
    monkeypatch.delenv("ONMC_ATTEST_SECRET", raising=False)
    att = build_attestation(_receipt(), secret=_SECRET)
    assert verify_attestation(att, None) is False


# ---------------------------------------------------------------------------
# unsigned digest path
# ---------------------------------------------------------------------------


def test_no_secret_path_is_unsigned_and_digest_verifies(monkeypatch: Any) -> None:
    monkeypatch.delenv("ONMC_ATTEST_SECRET", raising=False)
    att = build_attestation(_receipt(), secret=None)
    assert att.signed is False
    assert att.alg == "SHA256"
    # An unsigned attestation verifies its integrity digest regardless of secret.
    assert verify_attestation(att, None) is True
    assert verify_attestation(att, "irrelevant") is True


def test_unsigned_digest_detects_tamper(monkeypatch: Any) -> None:
    monkeypatch.delenv("ONMC_ATTEST_SECRET", raising=False)
    att = build_attestation(_receipt(), secret=None)
    tampered = att.to_dict()
    tampered["claim"]["goal"] = "something else"
    assert verify_attestation(tampered, None) is False


def test_sign_claim_signed_flag(monkeypatch: Any) -> None:
    monkeypatch.delenv("ONMC_ATTEST_SECRET", raising=False)
    claim = canonical_claim(_receipt())
    sig_keyed, signed_keyed = sign_claim(claim, "s")
    sig_bare, signed_bare = sign_claim(claim, None)
    assert signed_keyed is True
    assert signed_bare is False
    assert sig_keyed != sig_bare  # HMAC differs from bare digest


def test_env_secret_is_used(monkeypatch: Any) -> None:
    monkeypatch.setenv("ONMC_ATTEST_SECRET", "fromenv")
    att = build_attestation(_receipt(), secret=None)
    assert att.signed is True
    assert verify_attestation(att, None) is True  # env secret resolves in verify
    monkeypatch.delenv("ONMC_ATTEST_SECRET", raising=False)
    assert verify_attestation(att, "fromenv") is True


def test_empty_env_secret_is_treated_as_unsigned(monkeypatch: Any) -> None:
    monkeypatch.setenv("ONMC_ATTEST_SECRET", "")
    att = build_attestation(_receipt(), secret=None)
    assert att.signed is False


# ---------------------------------------------------------------------------
# reputation math
# ---------------------------------------------------------------------------


def test_build_reputation_math() -> None:
    receipts = [
        _receipt(goal="a", verified=True),
        _receipt(goal="b", verified=True),
        _receipt(goal="a", verified=False),  # duplicate goal, unverified
        _receipt(goal="c", verified=False, receipt_hash=None),  # not attestable
    ]
    summary = build_reputation(receipts)
    assert summary.total == 4
    assert summary.verified == 2
    assert summary.verified_rate == 0.5
    assert summary.attested == 3  # one had no receipt_hash
    assert summary.distinct_goals == 3  # a, b, c
    assert summary.subjects == ["claude-code-subagent"]
    assert summary.first_ts == "2026-07-04T08:58:34.607111+00:00"


def test_build_reputation_empty_is_zeros() -> None:
    summary = build_reputation([])
    assert summary.total == 0
    assert summary.verified == 0
    assert summary.verified_rate == 0.0
    assert summary.distinct_goals == 0
    assert summary.first_ts is None
    assert summary.last_ts is None
    assert summary.subjects == []


def test_build_reputation_skips_non_dicts() -> None:
    summary = build_reputation([_receipt(), "garbage", 42, None])  # type: ignore[list-item]
    assert summary.total == 1


def test_build_reputation_timestamps_span() -> None:
    receipts = [
        _receipt(ended_at="2026-07-01T00:00:00+00:00"),
        _receipt(ended_at="2026-07-05T00:00:00+00:00"),
        _receipt(ended_at="2026-07-03T00:00:00+00:00"),
    ]
    summary = build_reputation(receipts)
    assert summary.first_ts == "2026-07-01T00:00:00+00:00"
    assert summary.last_ts == "2026-07-05T00:00:00+00:00"


def test_reputation_to_dict_serialisable() -> None:
    import json

    summary = build_reputation([_receipt()])
    assert json.loads(json.dumps(summary.to_dict()))["total"] == 1
