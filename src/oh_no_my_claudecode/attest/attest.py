"""Pure attestation + reputation core — stdlib only, no I/O.

An onmc *receipt* already proves work is real and verified (``git_tree_sha``,
``diff_sha``, ``receipt_hash``, ``verified``).  The emerging agent economy
(ERC-8004 identity/reputation/validation registries, WorkProtocol) needs that
proof in a **portable, signed** shape a third party can verify without trusting
onmc.  This module does exactly that, off-chain and dependency-free:

- :func:`canonical_claim` distils a receipt into the minimal verifiable claim.
- :func:`sign_claim` signs (HMAC-SHA256) or digests (SHA256) the canonical JSON.
- :class:`Attestation` is the ERC-8004-shaped envelope (subject + claim + alg +
  signature + ``signed`` flag) with ``to_dict``/``from_dict`` round-tripping.
- :func:`verify_attestation` recomputes and compares in constant time.
- :func:`build_reputation` folds a list of receipts into a track record.

Design constraints (honesty + safety):

- **Deterministic** — canonical JSON uses sorted keys and no whitespace, so the
  same claim always hashes identically across machines and processes.
- **Constant-time** — all signature comparisons go through
  :func:`hmac.compare_digest`; no early-return string equality that could leak.
- **No regex** — every field is read via ``dict.get``; there is no pattern
  matching anywhere, so there is no ReDoS surface.
- **Honest on missing data** — a receipt missing a field surfaces ``None``/``""``
  rather than a fabricated value, and an empty receipt list yields an all-zero
  :class:`ReputationSummary` with no division by zero.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from typing import Any

_ALG_HMAC = "HMAC-SHA256"
"""Algorithm label when a shared secret signs the claim."""

_ALG_SHA256 = "SHA256"
"""Algorithm label for an unsigned (digest-only) attestation."""

_SECRET_ENV = "ONMC_ATTEST_SECRET"  # noqa: S105 - env var NAME, not a secret value
"""Environment variable consulted when no explicit secret is passed."""


# ---------------------------------------------------------------------------
# Canonical claim + signing
# ---------------------------------------------------------------------------


def canonical_claim(receipt: dict[str, Any]) -> dict[str, Any]:
    """Distil *receipt* into the minimal verifiable claim.

    The claim is the portable subset a third party needs to trust the work: who
    did it (``subject``), what for (``goal``), the tamper-evidence hashes
    (``git_tree_sha``, ``diff_sha``, ``receipt_hash``), the honest ``verified``
    flag, and a timestamp.  Fields absent from the receipt surface as ``None``
    (or ``""`` for the goal) rather than being invented.

    The returned dict has a fixed, documented set of keys; the canonical JSON
    encoding (see :func:`_canonical_json`) sorts them, so key insertion order
    here is irrelevant to the signature.

    Parameters
    ----------
    receipt:
        A receipt dict as parsed from ``.agent-memory/receipts/run-*.json``.

    Returns
    -------
    dict[str, Any]
        The minimal claim.  ``subject`` falls back to ``"onmc"`` when the
        receipt names no agent; ``ts`` prefers ``ended_at`` then ``started_at``.
    """
    subject = _first_nonempty(receipt.get("agent")) or "onmc"
    ts = _first_nonempty(receipt.get("ended_at")) or _first_nonempty(
        receipt.get("started_at")
    )
    return {
        "subject": subject,
        "goal": str(receipt.get("goal") or ""),
        "git_tree_sha": _opt_str(receipt.get("git_tree_sha")),
        "diff_sha": _opt_str(receipt.get("diff_sha")),
        "receipt_hash": _opt_str(receipt.get("receipt_hash")),
        "verified": bool(receipt.get("verified", False)),
        "ts": ts,
    }


def _first_nonempty(value: Any) -> str | None:
    """Return ``str(value)`` when *value* is truthy and non-empty, else ``None``."""
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _opt_str(value: Any) -> str | None:
    """Coerce a hash-like field to ``str`` or ``None`` (never fabricate)."""
    return None if value is None else str(value)


def _canonical_json(claim: dict[str, Any]) -> str:
    """Serialise *claim* deterministically (sorted keys, no whitespace).

    This exact byte string is what gets signed and verified, so it must be
    stable across machines: ``sort_keys`` removes insertion-order sensitivity
    and the tight separators remove whitespace ambiguity.
    """
    return json.dumps(claim, sort_keys=True, separators=(",", ":"))


def _resolve_secret(secret: str | None) -> str | None:
    """Return the effective secret: explicit arg wins, else the env var.

    An empty string is treated as *no secret* so an accidentally-blank
    ``ONMC_ATTEST_SECRET`` does not silently produce a keyed-but-empty HMAC.
    """
    if secret:
        return secret
    env = os.environ.get(_SECRET_ENV)
    return env if env else None


def sign_claim(claim: dict[str, Any], secret: str | None) -> tuple[str, bool]:
    """Sign or digest *claim*; return ``(signature_hex, signed)``.

    When a secret is available (the *secret* argument, else the
    ``ONMC_ATTEST_SECRET`` environment variable), the signature is an
    HMAC-SHA256 hex digest over the canonical JSON and ``signed`` is ``True``.
    Otherwise the signature is a plain SHA256 hex digest of the same canonical
    JSON and ``signed`` is ``False`` — a tamper-evident fingerprint that is
    clearly *not* an authenticity proof.

    Parameters
    ----------
    claim:
        The minimal claim (typically from :func:`canonical_claim`).
    secret:
        Shared secret, or ``None`` to fall back to the environment.

    Returns
    -------
    tuple[str, bool]
        ``(hex_signature, signed)`` where ``signed`` distinguishes a keyed HMAC
        from an unsigned digest.
    """
    payload = _canonical_json(claim).encode("utf-8")
    resolved = _resolve_secret(secret)
    if resolved is not None:
        sig = hmac.new(resolved.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return sig, True
    return hashlib.sha256(payload).hexdigest(), False


# ---------------------------------------------------------------------------
# Attestation envelope (ERC-8004-shaped)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Attestation:
    """A portable, signed attestation of one unit of agent work.

    Shaped to slot into ERC-8004-style reputation/validation flows: a
    ``subject`` (the agent identity being credited), the verifiable ``claim``,
    the signing ``alg``, the ``signature`` hex, and a ``signed`` flag separating
    an authenticity proof (keyed HMAC) from a mere integrity digest.

    Attributes
    ----------
    subject:
        Agent identity the work is credited to (or ``"onmc"``).
    claim:
        The minimal verifiable claim (see :func:`canonical_claim`).
    alg:
        ``"HMAC-SHA256"`` when signed, ``"SHA256"`` when digest-only.
    signature:
        Hex digest — a keyed HMAC or a bare SHA256 depending on ``signed``.
    signed:
        ``True`` iff a shared secret produced an authenticity signature.
    """

    subject: str
    claim: dict[str, Any]
    alg: str
    signature: str
    signed: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view (claim is copied, not aliased)."""
        return {
            "subject": self.subject,
            "claim": dict(self.claim),
            "alg": self.alg,
            "signature": self.signature,
            "signed": self.signed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Attestation:
        """Rebuild an :class:`Attestation` from its :meth:`to_dict` form.

        Defensive: missing fields fall back to safe defaults (empty claim, empty
        signature, ``signed=False``) so a malformed file yields a verifiable-as-
        false attestation rather than raising.
        """
        claim = data.get("claim")
        claim_dict: dict[str, Any] = dict(claim) if isinstance(claim, dict) else {}
        signed = bool(data.get("signed", False))
        alg = str(data.get("alg") or (_ALG_HMAC if signed else _ALG_SHA256))
        return cls(
            subject=str(data.get("subject") or "onmc"),
            claim=claim_dict,
            alg=alg,
            signature=str(data.get("signature") or ""),
            signed=signed,
        )


def build_attestation(receipt: dict[str, Any], secret: str | None = None) -> Attestation:
    """Build a signed (or digest-only) :class:`Attestation` from *receipt*.

    Convenience composition of :func:`canonical_claim` + :func:`sign_claim`.
    The ``alg`` is chosen from whether a secret was available.

    Parameters
    ----------
    receipt:
        A receipt dict.
    secret:
        Optional shared secret; falls back to ``ONMC_ATTEST_SECRET``.

    Returns
    -------
    Attestation
        The portable attestation envelope.
    """
    claim = canonical_claim(receipt)
    signature, signed = sign_claim(claim, secret)
    return Attestation(
        subject=str(claim["subject"]),
        claim=claim,
        alg=_ALG_HMAC if signed else _ALG_SHA256,
        signature=signature,
        signed=signed,
    )


def verify_attestation(att: Attestation | dict[str, Any], secret: str | None) -> bool:
    """Verify *att* by recomputing its signature over the embedded claim.

    Recomputes the expected signature from ``att.claim`` and compares it to the
    stored ``att.signature`` with :func:`hmac.compare_digest` (constant-time, no
    early-out leak).  A *signed* attestation only verifies when the correct
    secret is supplied — a missing or wrong secret yields ``False``.  An
    *unsigned* attestation verifies its SHA256 digest regardless of secret,
    proving integrity (not authenticity).

    Parameters
    ----------
    att:
        An :class:`Attestation` or its dict form.
    secret:
        Shared secret for HMAC verification; falls back to
        ``ONMC_ATTEST_SECRET``.  Ignored for unsigned attestations.

    Returns
    -------
    bool
        ``True`` iff the recomputed signature matches in constant time.
    """
    attestation = att if isinstance(att, Attestation) else Attestation.from_dict(att)

    if attestation.signed:
        resolved = _resolve_secret(secret)
        if resolved is None:
            # A signed attestation with no key on hand cannot be authenticated.
            return False
        expected = hmac.new(
            resolved.encode("utf-8"),
            _canonical_json(attestation.claim).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    else:
        expected = hashlib.sha256(
            _canonical_json(attestation.claim).encode("utf-8")
        ).hexdigest()

    return hmac.compare_digest(expected, attestation.signature)


# ---------------------------------------------------------------------------
# Reputation summary
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ReputationSummary:
    """An agent's track record folded from a set of receipts.

    Attributes
    ----------
    total:
        Number of valid receipts considered.
    attested:
        Number of receipts that carry the tamper-evidence hashes needed to
        produce a meaningful attestation (a non-empty ``receipt_hash``).
    verified:
        Number of receipts with ``verified=True``.
    verified_rate:
        ``verified / total`` rounded to 4 dp (0.0 when ``total == 0``).
    distinct_goals:
        Count of unique non-empty ``goal`` strings.
    first_ts / last_ts:
        Earliest / latest receipt timestamp (ISO-8601 strings), or ``None`` when
        no receipt carried a timestamp.
    """

    total: int
    attested: int
    verified: int
    verified_rate: float
    distinct_goals: int
    first_ts: str | None = None
    last_ts: str | None = None
    subjects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of the summary."""
        return {
            "total": self.total,
            "attested": self.attested,
            "verified": self.verified,
            "verified_rate": self.verified_rate,
            "distinct_goals": self.distinct_goals,
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "subjects": list(self.subjects),
        }


def build_reputation(receipts: list[dict[str, Any]]) -> ReputationSummary:
    """Fold *receipts* into a :class:`ReputationSummary`.

    Pure and deterministic.  Honest on empty input: zero receipts yields an
    all-zero summary with ``verified_rate == 0.0`` and no division by zero.
    Non-dict entries are skipped rather than crashing.

    Parameters
    ----------
    receipts:
        A list of receipt dicts (already loaded by the caller).

    Returns
    -------
    ReputationSummary
        The aggregated track record.
    """
    total = 0
    attested = 0
    verified = 0
    goals: set[str] = set()
    subjects: set[str] = set()
    timestamps: list[str] = []

    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        total += 1
        if bool(receipt.get("verified", False)):
            verified += 1
        if _first_nonempty(receipt.get("receipt_hash")):
            attested += 1
        goal = str(receipt.get("goal") or "")
        if goal:
            goals.add(goal)
        claim = canonical_claim(receipt)
        subjects.add(str(claim["subject"]))
        ts = claim["ts"]
        if isinstance(ts, str) and ts:
            timestamps.append(ts)

    verified_rate = round(verified / total, 4) if total > 0 else 0.0
    # ISO-8601 UTC strings sort lexicographically in chronological order.
    ordered_ts = sorted(timestamps)
    first_ts = ordered_ts[0] if ordered_ts else None
    last_ts = ordered_ts[-1] if ordered_ts else None

    return ReputationSummary(
        total=total,
        attested=attested,
        verified=verified,
        verified_rate=verified_rate,
        distinct_goals=len(goals),
        first_ts=first_ts,
        last_ts=last_ts,
        subjects=sorted(subjects),
    )


__all__ = [
    "Attestation",
    "ReputationSummary",
    "build_attestation",
    "build_reputation",
    "canonical_claim",
    "sign_claim",
    "verify_attestation",
]
