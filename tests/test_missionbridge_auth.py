"""Tests for ``missionbridge.auth`` — the channel-scoped mission allowlist.

Coverage:
- allowlisted identity → allowed; unknown identity → denied.
- empty allowlist + ``open_when_empty=False`` → denied (deny-by-default).
- empty allowlist + ``open_when_empty=True`` → allowed, with an explicit reason.
- channel scoping: ``slack:U1`` and ``telegram:U1`` are distinct principals.
- ``load_policy`` on a missing file → deny-by-default, no crash.
- ``load_policy`` on malformed JSON → deny-by-default (never widen on error).
- ``add_identity`` / ``remove_identity`` round-trip idempotently in a tmp repo.
"""

from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.missionbridge.auth import (
    add_identity,
    allowlist_path,
    authorize,
    load_policy,
    remove_identity,
)
from oh_no_my_claudecode.missionbridge.models import AuthPolicy


def test_allowlisted_identity_allowed() -> None:
    policy = AuthPolicy(frozenset({"slack:U123"}))
    decision = authorize(policy, channel="slack", user_id="U123")
    assert decision.allowed is True
    assert decision.reason == "allowlisted"


def test_unknown_identity_denied() -> None:
    policy = AuthPolicy(frozenset({"slack:U123"}))
    decision = authorize(policy, channel="slack", user_id="U999")
    assert decision.allowed is False


def test_empty_allowlist_deny_by_default() -> None:
    policy = AuthPolicy(frozenset(), open_when_empty=False)
    decision = authorize(policy, channel="slack", user_id="U123")
    assert decision.allowed is False


def test_empty_allowlist_open_when_empty_allows() -> None:
    policy = AuthPolicy(frozenset(), open_when_empty=True)
    decision = authorize(policy, channel="slack", user_id="U123")
    assert decision.allowed is True
    assert decision.reason


def test_channel_scoping_is_distinct() -> None:
    policy = AuthPolicy(frozenset({"slack:U1"}))
    assert authorize(policy, channel="slack", user_id="U1").allowed is True
    assert authorize(policy, channel="telegram", user_id="U1").allowed is False


def test_load_policy_missing_file_is_deny_by_default(tmp_path: Path) -> None:
    policy = load_policy(tmp_path)
    assert policy.allowed_identities == frozenset()
    assert policy.open_when_empty is False
    assert authorize(policy, channel="slack", user_id="U1").allowed is False


def test_load_policy_malformed_json_is_deny_by_default(tmp_path: Path) -> None:
    target = allowlist_path(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not valid json", encoding="utf-8")
    policy = load_policy(tmp_path)
    assert policy.allowed_identities == frozenset()
    assert policy.open_when_empty is False


def test_load_policy_reads_allowed_and_flag(tmp_path: Path) -> None:
    target = allowlist_path(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"allowed": ["slack:U123", "telegram:456"], "open_when_empty": False}),
        encoding="utf-8",
    )
    policy = load_policy(tmp_path)
    assert policy.allowed_identities == frozenset({"slack:U123", "telegram:456"})
    assert authorize(policy, channel="telegram", user_id="456").allowed is True


def test_add_identity_round_trips(tmp_path: Path) -> None:
    path = add_identity(tmp_path, "slack:U123")
    assert path == allowlist_path(tmp_path)
    policy = load_policy(tmp_path)
    assert "slack:U123" in policy.allowed_identities
    assert authorize(policy, channel="slack", user_id="U123").allowed is True


def test_add_identity_is_idempotent(tmp_path: Path) -> None:
    add_identity(tmp_path, "slack:U123")
    first = allowlist_path(tmp_path).read_text(encoding="utf-8")
    add_identity(tmp_path, "slack:U123")
    second = allowlist_path(tmp_path).read_text(encoding="utf-8")
    assert first == second
    assert load_policy(tmp_path).allowed_identities == frozenset({"slack:U123"})


def test_remove_identity_round_trips(tmp_path: Path) -> None:
    add_identity(tmp_path, "slack:U123")
    add_identity(tmp_path, "telegram:456")
    remove_identity(tmp_path, "slack:U123")
    policy = load_policy(tmp_path)
    assert policy.allowed_identities == frozenset({"telegram:456"})
    assert authorize(policy, channel="slack", user_id="U123").allowed is False


def test_remove_identity_absent_is_idempotent(tmp_path: Path) -> None:
    add_identity(tmp_path, "telegram:456")
    before = allowlist_path(tmp_path).read_text(encoding="utf-8")
    remove_identity(tmp_path, "slack:does-not-exist")
    after = allowlist_path(tmp_path).read_text(encoding="utf-8")
    assert before == after


def test_add_identity_preserves_open_when_empty_flag(tmp_path: Path) -> None:
    target = allowlist_path(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"allowed": [], "open_when_empty": True}), encoding="utf-8")
    add_identity(tmp_path, "slack:U1")
    policy = load_policy(tmp_path)
    assert policy.open_when_empty is True
    assert "slack:U1" in policy.allowed_identities
