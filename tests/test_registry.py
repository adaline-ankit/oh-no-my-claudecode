"""Tests for the ``onmc registry`` agent-reputation trust ledger.

All pure and self-contained: attestations are built with the real
:func:`oh_no_my_claudecode.attest.attest.build_attestation` over fake receipts
and a known secret, so signature verification is exercised end-to-end without
touching the filesystem (except ``tmp_path`` for the CLI/load tests).

Covers:
- only signature-verified attestations count toward the verified tally;
- higher verified-rate / volume ranks higher (trust-score ordering);
- a tampered / wrong-secret attestation is flagged as invalid, not counted;
- ``rank()`` is a stable, deterministic total order (tiebreak by subject);
- an empty registry is graceful (no div-by-zero, empty rank);
- agent lookup + trust-score formula invariants;
- ``load_attestation`` is tolerant of missing / malformed files.

Never asserts against Rich / ``--help`` output.
"""

from __future__ import annotations

import json
from typing import Any

from oh_no_my_claudecode.attest.attest import build_attestation
from oh_no_my_claudecode.registry.registry import (
    VOLUME_THRESHOLD,
    AgentReputation,
    Registry,
    build_registry,
    ingest,
    load_attestation,
    rank,
)

_SECRET = "test-secret-42"  # noqa: S105 - test fixture secret, not a real credential
_WRONG_SECRET = "the-wrong-secret"  # noqa: S105 - test fixture, deliberately mismatched


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _receipt(
    agent: str,
    *,
    verified: bool = True,
    goal: str = "do the thing",
    ts: str = "2026-01-01T00:00:00Z",
) -> dict[str, Any]:
    """A minimal fake receipt with the fields ``canonical_claim`` reads."""
    return {
        "agent": agent,
        "goal": goal,
        "verified": verified,
        "git_tree_sha": f"tree-{agent}-{goal}",
        "diff_sha": f"diff-{agent}-{goal}",
        "receipt_hash": f"rh-{agent}-{goal}",
        "ended_at": ts,
    }


def _att(agent: str, *, secret: str | None = _SECRET, **kw: Any) -> dict[str, Any]:
    """A signed attestation dict for *agent* (defaults to the test secret)."""
    return build_attestation(_receipt(agent, **kw), secret=secret).to_dict()


# ---------------------------------------------------------------------------
# Verified-tally honesty
# ---------------------------------------------------------------------------


def test_only_verified_signatures_count() -> None:
    """Signature-valid + claim-verified counts; everything else does not."""
    atts = [
        _att("alice", verified=True, goal="g1"),   # counts
        _att("alice", verified=True, goal="g2"),   # counts
        _att("alice", verified=False, goal="g3"),  # signed but claim unverified -> not counted
    ]
    reg = build_registry(atts, _SECRET)
    alice = reg.agents["alice"]
    assert alice.attestations == 3
    assert alice.verified == 2
    assert alice.invalid == 0  # all signatures verified
    assert alice.distinct_goals == 2  # only verified goals counted
    assert alice.verified_rate == round(2 / 3, 4)


def test_wrong_secret_is_flagged_invalid_not_counted() -> None:
    """An attestation signed with a different secret fails verification."""
    good = _att("bob", secret=_SECRET, verified=True)
    tampered = _att("bob", secret=_WRONG_SECRET, verified=True)

    reg = build_registry([good, tampered], _SECRET)
    bob = reg.agents["bob"]
    assert bob.attestations == 2
    assert bob.verified == 1  # only the correctly-signed one
    assert bob.invalid == 1  # the wrong-secret one is flagged
    assert bob.verified_rate == 0.5


def test_mutated_claim_breaks_signature() -> None:
    """Tampering with the claim after signing makes it verify as invalid."""
    att = _att("carol", verified=True, goal="original")
    att["claim"]["goal"] = "mutated"  # tamper post-signature

    reg = build_registry([att], _SECRET)
    carol = reg.agents["carol"]
    assert carol.attestations == 1
    assert carol.verified == 0
    assert carol.invalid == 1
    assert carol.trust_score == 0.0


def test_signed_att_without_secret_does_not_verify() -> None:
    """A signed (HMAC) attestation cannot be authenticated with no secret."""
    att = _att("dave", verified=True)
    reg = build_registry([att], None)  # no secret available
    dave = reg.agents["dave"]
    assert dave.verified == 0
    assert dave.invalid == 1


# ---------------------------------------------------------------------------
# Trust-score ordering + formula
# ---------------------------------------------------------------------------


def test_trust_score_ordering_reliability() -> None:
    """Higher verified-rate ranks higher at equal volume."""
    # reliable: 4/4 verified; flaky: 2/4 verified (2 wrong-secret invalids)
    reliable = [_att("reliable", verified=True, goal=f"g{i}") for i in range(4)]
    flaky = [_att("flaky", verified=True, goal=f"g{i}") for i in range(2)]
    flaky += [_att("flaky", secret=_WRONG_SECRET, verified=True, goal=f"b{i}") for i in range(2)]

    reg = build_registry(reliable + flaky, _SECRET)
    ranked = rank(reg)
    assert [r.subject for r in ranked] == ["reliable", "flaky"]
    assert ranked[0].trust_score > ranked[1].trust_score


def test_trust_score_ordering_volume() -> None:
    """At equal (perfect) verified-rate, more verified volume ranks higher."""
    heavy = [_att("heavy", verified=True, goal=f"g{i}") for i in range(VOLUME_THRESHOLD)]
    light = [_att("light", verified=True, goal="only")]
    reg = build_registry(heavy + light, _SECRET)
    ranked = rank(reg)
    assert ranked[0].subject == "heavy"
    assert ranked[0].trust_score == 1.0  # 100% rate, saturated volume
    assert ranked[1].subject == "light"
    assert 0.0 < ranked[1].trust_score < 1.0


def test_trust_score_zero_without_verified_work() -> None:
    """No verified work -> trust score exactly 0.0 (trust is earned)."""
    atts = [_att("ghost", secret=_WRONG_SECRET, verified=True) for _ in range(5)]
    reg = build_registry(atts, _SECRET)
    ghost = reg.agents["ghost"]
    assert ghost.verified == 0
    assert ghost.invalid == 5
    assert ghost.trust_score == 0.0


def test_trust_score_formula_exact() -> None:
    """Documented formula: verified_rate * min(1, verified/THRESHOLD)."""
    # 3 verified out of 4 total, verified=3 < THRESHOLD.
    atts = [_att("x", verified=True, goal=f"g{i}") for i in range(3)]
    atts.append(_att("x", secret=_WRONG_SECRET, verified=True))  # 1 invalid
    reg = build_registry(atts, _SECRET)
    x = reg.agents["x"]
    expected = round((3 / 4) * min(1.0, 3 / VOLUME_THRESHOLD), 4)
    assert x.trust_score == expected


# ---------------------------------------------------------------------------
# rank() stability + emptiness
# ---------------------------------------------------------------------------


def test_rank_stable_tiebreak_by_subject() -> None:
    """Equal trust scores break alphabetically by subject, deterministically."""
    # three agents, all zero trust (no verified work) -> alphabetical order
    atts = [
        _att("charlie", secret=_WRONG_SECRET, verified=True),
        _att("alpha", secret=_WRONG_SECRET, verified=True),
        _att("bravo", secret=_WRONG_SECRET, verified=True),
    ]
    reg = build_registry(atts, _SECRET)
    ranked = rank(reg)
    assert [r.subject for r in ranked] == ["alpha", "bravo", "charlie"]
    # deterministic: same input -> same order
    assert [r.subject for r in rank(build_registry(atts, _SECRET))] == [
        "alpha",
        "bravo",
        "charlie",
    ]


def test_empty_registry_graceful() -> None:
    """No attestations -> empty registry, empty rank, no exceptions."""
    reg = build_registry([], _SECRET)
    assert reg.agents == {}
    assert rank(reg) == []
    assert reg.to_dict() == {"agents": {}}


def test_non_dict_entries_are_tolerated() -> None:
    """Non-dict list entries fold into the defensive 'onmc' subject, no crash."""
    reg = build_registry([None, "garbage", 42], _SECRET)  # type: ignore[list-item]
    assert set(reg.agents) == {"onmc"}
    assert reg.agents["onmc"].attestations == 3
    assert reg.agents["onmc"].verified == 0


# ---------------------------------------------------------------------------
# ingest() incremental behaviour
# ---------------------------------------------------------------------------


def test_ingest_is_incremental_and_returns_same_ledger() -> None:
    """ingest() mutates in place and equals a batch build_registry()."""
    ledger = Registry()
    a1 = _att("eve", verified=True, goal="g1")
    a2 = _att("eve", verified=True, goal="g2")
    assert ingest(ledger, a1, _SECRET) is ledger
    ingest(ledger, a2, _SECRET)

    batch = build_registry([a1, a2], _SECRET)
    assert ledger.agents["eve"].to_dict() == batch.agents["eve"].to_dict()


def test_first_last_seen_track_verified_timestamps() -> None:
    """first_seen/last_seen span verified attestations chronologically."""
    atts = [
        _att("frank", verified=True, goal="g1", ts="2026-03-01T00:00:00Z"),
        _att("frank", verified=True, goal="g2", ts="2026-01-01T00:00:00Z"),
        _att("frank", verified=True, goal="g3", ts="2026-02-01T00:00:00Z"),
    ]
    reg = build_registry(atts, _SECRET)
    frank = reg.agents["frank"]
    assert frank.first_seen == "2026-01-01T00:00:00Z"
    assert frank.last_seen == "2026-03-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Agent lookup + load_attestation I/O
# ---------------------------------------------------------------------------


def test_agent_lookup() -> None:
    """Subjects are keyed by identity; lookup returns the right record."""
    reg = build_registry([_att("grace", verified=True), _att("heidi", verified=True)], _SECRET)
    assert reg.agents["grace"].subject == "grace"
    assert reg.agents["heidi"].subject == "heidi"
    assert reg.agents.get("missing") is None
    assert isinstance(reg.agents["grace"], AgentReputation)


def test_load_attestation_tolerant(tmp_path: Any) -> None:
    """load_attestation returns {} on missing/malformed, dict on valid JSON."""
    assert load_attestation(tmp_path / "nope.json") == {}

    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert load_attestation(bad) == {}

    non_obj = tmp_path / "list.json"
    non_obj.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_attestation(non_obj) == {}

    good = tmp_path / "good.json"
    att = _att("ivan", verified=True)
    good.write_text(json.dumps(att), encoding="utf-8")
    loaded = load_attestation(good)
    assert loaded["subject"] == "ivan"

    # round-trips through the registry
    reg = build_registry([loaded], _SECRET)
    assert reg.agents["ivan"].verified == 1
