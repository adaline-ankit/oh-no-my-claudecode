"""Pure agent-reputation registry — stdlib only, offline, deterministic.

``onmc attest`` turns one receipt into a portable, signed proof-of-work
:class:`~oh_no_my_claudecode.attest.attest.Attestation`.  This module is the
layer *above* that: it aggregates **many** attestations — across many agents —
into a queryable, rankable **trust ledger**.  It is the reputation surface the
agent economy needs: given a pile of signed claims, who has actually done
verifiable work, and how much?

Design constraints (identical spirit to :mod:`attest`):

- **Pure / deterministic** — no I/O in the reputation math; the same set of
  attestations always folds to the same registry, byte-for-byte.
- **Offline, stdlib only** — the only import is :mod:`attest` (itself stdlib).
- **Honest** — an agent with zero *signature-verified* work has a
  ``trust_score`` of exactly ``0.0``.  Unverifiable attestations are *recorded*
  (so tampering is visible) but never counted toward reputation.
- **No regex / no ReDoS** — every field is read via ``dict.get``; signature
  comparison is delegated to :func:`attest.verify_attestation` (constant-time
  :func:`hmac.compare_digest`), never reimplemented here.

Trust-score formula (documented, deterministic)
------------------------------------------------
For an agent with ``verified`` signature-verified attestations out of
``attestations`` total::

    verified_rate = verified / attestations          # 0.0 when none
    volume_factor = min(1.0, verified / VOLUME_THRESHOLD)
    trust_score   = round(verified_rate * volume_factor, 4)

``verified_rate`` rewards *reliability* (what fraction of an agent's claims
actually verify); ``volume_factor`` rewards *track record* (a single verified
run is worth less than a sustained one), saturating at
:data:`VOLUME_THRESHOLD` verified runs.  The product is in ``[0, 1]`` and is
``0.0`` whenever there is no verified work — trust is earned, never assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from oh_no_my_claudecode.attest.attest import Attestation, verify_attestation

VOLUME_THRESHOLD = 10
"""Verified-run count at which the volume factor saturates to ``1.0``.

Ten verified units of work is treated as a "full" track record: beyond it,
additional volume no longer raises the score (reliability then dominates).  A
documented constant so the formula is auditable and stable across runs.
"""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AgentReputation:
    """One agent's folded track record across many attestations.

    Attributes
    ----------
    subject:
        The agent identity the attestations credit (``Attestation.subject``).
    attestations:
        Total attestations seen for this subject (verified *and* invalid).
    verified:
        Attestations whose signature verified **and** whose claim carried
        ``verified=True`` — i.e. genuine, authenticated proof-of-work.
    verified_rate:
        ``verified / attestations`` rounded to 4 dp (``0.0`` when none).
    distinct_goals:
        Count of unique non-empty ``goal`` strings across verified work.
    first_seen / last_seen:
        Earliest / latest claim timestamp (ISO-8601 strings) over verified
        work, or ``None`` when no verified attestation carried a timestamp.
    trust_score:
        Deterministic ``[0, 1]`` score (see module docstring).  ``0.0`` when the
        agent has no verified work.
    invalid:
        Attestations that failed signature verification — recorded so tampering
        is visible, never counted toward reputation.
    """

    subject: str
    attestations: int = 0
    verified: int = 0
    verified_rate: float = 0.0
    distinct_goals: int = 0
    first_seen: str | None = None
    last_seen: str | None = None
    trust_score: float = 0.0
    invalid: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of this reputation."""
        return {
            "subject": self.subject,
            "attestations": self.attestations,
            "verified": self.verified,
            "verified_rate": self.verified_rate,
            "distinct_goals": self.distinct_goals,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "trust_score": self.trust_score,
            "invalid": self.invalid,
        }


@dataclass(slots=True)
class Registry:
    """A trust ledger: subject → :class:`AgentReputation`.

    Also retains the *goal set* and *timestamp list* per subject as private
    accumulators so :func:`ingest` can update tallies incrementally and
    deterministically without re-reading prior attestations.
    """

    agents: dict[str, AgentReputation] = field(default_factory=dict)
    # Per-subject accumulators (not serialised): goals seen and timestamps.
    _goals: dict[str, set[str]] = field(default_factory=dict, repr=False)
    _timestamps: dict[str, list[str]] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view (accumulators are not exported)."""
        return {
            "agents": {
                subject: rep.to_dict()
                for subject, rep in sorted(self.agents.items())
            }
        }


# ---------------------------------------------------------------------------
# Loading (tolerant I/O boundary)
# ---------------------------------------------------------------------------


def load_attestation(path: Any) -> dict[str, Any]:
    """Tolerantly read an attestation JSON file into a dict.

    Any read/parse failure — missing file, bad JSON, or a non-object payload —
    yields an empty dict rather than raising, so a single corrupt file can never
    abort a bulk ingest.  The caller (or :func:`ingest`) treats an empty/invalid
    dict as an unverifiable attestation.

    Parameters
    ----------
    path:
        A path-like to an attestation JSON produced by ``attest sign --json``.

    Returns
    -------
    dict[str, Any]
        The parsed object, or ``{}`` on any failure.
    """
    import json  # noqa: PLC0415 - local: keep the module's import surface minimal
    from pathlib import Path  # noqa: PLC0415

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


# ---------------------------------------------------------------------------
# Reputation math (pure)
# ---------------------------------------------------------------------------


def _trust_score(verified: int, attestations: int) -> float:
    """Compute the deterministic trust score (see module docstring).

    ``0.0`` when there is no verified work or no attestations at all.
    """
    if verified <= 0 or attestations <= 0:
        return 0.0
    verified_rate = verified / attestations
    volume_factor = min(1.0, verified / VOLUME_THRESHOLD)
    return round(verified_rate * volume_factor, 4)


def _recompute(rep: AgentReputation, goals: set[str], timestamps: list[str]) -> None:
    """Refresh *rep*'s derived fields from its raw tallies + accumulators.

    Mutates ``rep`` in place.  Idempotent: derived purely from ``rep.verified``,
    ``rep.attestations`` and the passed accumulators, so calling it repeatedly
    with the same inputs yields the same result.
    """
    rep.verified_rate = (
        round(rep.verified / rep.attestations, 4) if rep.attestations > 0 else 0.0
    )
    rep.distinct_goals = len(goals)
    ordered = sorted(timestamps)  # ISO-8601 sorts chronologically
    rep.first_seen = ordered[0] if ordered else None
    rep.last_seen = ordered[-1] if ordered else None
    rep.trust_score = _trust_score(rep.verified, rep.attestations)


def ingest(
    ledger: Registry, attestation: dict[str, Any], secret: str | None
) -> Registry:
    """Fold one *attestation* dict into *ledger*, in place; return it.

    Verifies the attestation's signature via
    :func:`attest.verify_attestation` (constant-time).  Every attestation
    increments the subject's ``attestations`` count.  Only a *signature-valid*
    attestation whose claim also carries ``verified=True`` increments the
    ``verified`` tally and contributes its goal + timestamp — this is the
    honesty guarantee: unauthenticated or unverified work is recorded (and, when
    the signature is invalid, flagged via ``invalid``) but never earns trust.

    Deterministic: the same attestation folded into the same ledger state always
    produces the same result.

    Parameters
    ----------
    ledger:
        The :class:`Registry` to update in place.
    attestation:
        An attestation dict (from :func:`load_attestation` or
        ``Attestation.to_dict``).  An empty/invalid dict is treated as an
        unverifiable attestation credited to the defensive ``"onmc"`` subject.
    secret:
        Shared secret for HMAC verification; ``None`` falls back to
        ``ONMC_ATTEST_SECRET`` (see :func:`attest.verify_attestation`).

    Returns
    -------
    Registry
        The same ledger instance, updated.
    """
    att = Attestation.from_dict(attestation)
    subject = att.subject

    rep = ledger.agents.get(subject)
    if rep is None:
        rep = AgentReputation(subject=subject)
        ledger.agents[subject] = rep
        ledger._goals[subject] = set()
        ledger._timestamps[subject] = []

    rep.attestations += 1

    signature_ok = verify_attestation(att, secret)
    # A claim is genuine proof-of-work only when its signature verifies AND the
    # embedded claim asserts the work itself was verified.
    claim_verified = bool(att.claim.get("verified", False))

    if not signature_ok:
        rep.invalid += 1
    elif claim_verified:
        rep.verified += 1
        goal = str(att.claim.get("goal") or "")
        if goal:
            ledger._goals[subject].add(goal)
        ts = att.claim.get("ts")
        if isinstance(ts, str) and ts:
            ledger._timestamps[subject].append(ts)

    _recompute(rep, ledger._goals[subject], ledger._timestamps[subject])
    return ledger


def build_registry(
    attestations: list[dict[str, Any]], secret: str | None
) -> Registry:
    """Fold a list of attestation dicts into a fresh :class:`Registry`.

    Pure and deterministic.  Honest on empty input: an empty list yields an
    empty registry.  Non-dict entries are treated as empty (unverifiable)
    attestations via :meth:`Attestation.from_dict`'s defensive defaults.

    Parameters
    ----------
    attestations:
        Attestation dicts (already loaded).
    secret:
        Shared secret for verification (see :func:`ingest`).

    Returns
    -------
    Registry
        The aggregated trust ledger.
    """
    ledger = Registry()
    for attestation in attestations:
        ingest(ledger, attestation if isinstance(attestation, dict) else {}, secret)
    return ledger


def rank(registry: Registry) -> list[AgentReputation]:
    """Return agents ranked by ``trust_score`` desc, stable tiebreak by subject.

    A total, deterministic ordering: ties on ``trust_score`` (including the many
    ``0.0`` agents) break alphabetically by ``subject`` so the leaderboard is
    reproducible across runs and machines.

    Parameters
    ----------
    registry:
        The trust ledger to rank.

    Returns
    -------
    list[AgentReputation]
        Agents, highest trust first.
    """
    return sorted(
        registry.agents.values(),
        key=lambda rep: (-rep.trust_score, rep.subject),
    )


__all__ = [
    "VOLUME_THRESHOLD",
    "AgentReputation",
    "Registry",
    "build_registry",
    "ingest",
    "load_attestation",
    "rank",
]
