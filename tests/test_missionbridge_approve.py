"""Tests for the mission-bridge approve-intent parser.

Coverage:
- Button ``callback_data`` ids parse to the right kind (+ unit where relevant).
- Natural-language variants: "approve all" / "lgtm" / "ship it" → APPROVE_ALL;
  "approve unit 1" / "merge auth" → APPROVE_UNIT; "diff unit 2" → SHOW_DIFF;
  "abort" / "stop" / "kill" → ABORT.
- Unit normalization: "1" / "unit 1" / "unit1" / "#1" / "unit-0001" → "unit-0001".
- Garbage → UNKNOWN.
- The raw message is always retained.
- The parser is pure + deterministic (same input → identical action).
"""

from __future__ import annotations

import pytest

from oh_no_my_claudecode.missionbridge.approve import normalize_unit_id, parse_action
from oh_no_my_claudecode.missionbridge.models import ApproveAction, ApproveKind

# ---------------------------------------------------------------------------
# Button callback_data ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("callback", "kind", "unit_id"),
    [
        ("mission:approve_all", ApproveKind.APPROVE_ALL, None),
        ("mission:abort", ApproveKind.ABORT, None),
        ("mission:approve:unit-0001", ApproveKind.APPROVE_UNIT, "unit-0001"),
        ("mission:approve:unit-0042", ApproveKind.APPROVE_UNIT, "unit-0042"),
        ("mission:show_diff:unit-0001", ApproveKind.SHOW_DIFF, "unit-0001"),
        ("mission:show_diff:unit-0002", ApproveKind.SHOW_DIFF, "unit-0002"),
    ],
)
def test_callback_ids_parse(callback: str, kind: ApproveKind, unit_id: str | None) -> None:
    action = parse_action(callback)
    assert action.kind is kind
    assert action.unit_id == unit_id
    assert action.raw == callback


def test_callback_unit_ordinal_is_normalized() -> None:
    # A button that carried a loose ordinal still lands on the canonical form.
    action = parse_action("mission:approve:1")
    assert action.kind is ApproveKind.APPROVE_UNIT
    assert action.unit_id == "unit-0001"


def test_unknown_callback_verb_is_unknown() -> None:
    action = parse_action("mission:frobnicate:unit-0001")
    assert action.kind is ApproveKind.UNKNOWN
    assert action.unit_id is None
    assert action.raw == "mission:frobnicate:unit-0001"


def test_per_unit_callback_without_unit_is_unknown() -> None:
    action = parse_action("mission:approve:")
    assert action.kind is ApproveKind.UNKNOWN
    assert action.unit_id is None


# ---------------------------------------------------------------------------
# Natural language
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    ["approve all", "APPROVE ALL", "lgtm", "ship it", "  ship it  ", "looks good to me"],
)
def test_natural_approve_all(message: str) -> None:
    action = parse_action(message)
    assert action.kind is ApproveKind.APPROVE_ALL
    assert action.unit_id is None
    assert action.raw == message


@pytest.mark.parametrize(
    ("message", "unit_id"),
    [
        ("approve unit 1", "unit-0001"),
        ("approve unit-0001", "unit-0001"),
        ("approve unit1", "unit-0001"),
        ("approve #2", "unit-0002"),
        ("merge unit 3", "unit-0003"),
        ("accept unit-0007", "unit-0007"),
    ],
)
def test_natural_approve_unit(message: str, unit_id: str) -> None:
    action = parse_action(message)
    assert action.kind is ApproveKind.APPROVE_UNIT
    assert action.unit_id == unit_id
    assert action.raw == message


@pytest.mark.parametrize(
    ("message", "unit_id"),
    [
        ("show diff unit 2", "unit-0002"),
        ("diff unit-0002", "unit-0002"),
        ("show diff unit-0001", "unit-0001"),
        ("diff #3", "unit-0003"),
    ],
)
def test_natural_show_diff(message: str, unit_id: str) -> None:
    action = parse_action(message)
    assert action.kind is ApproveKind.SHOW_DIFF
    assert action.unit_id == unit_id
    assert action.raw == message


@pytest.mark.parametrize("message", ["abort", "stop", "kill", "ABORT", "cancel"])
def test_natural_abort(message: str) -> None:
    action = parse_action(message)
    assert action.kind is ApproveKind.ABORT
    assert action.unit_id is None
    assert action.raw == message


def test_diff_beats_approve_when_both_present() -> None:
    # "diff" intent must win over the approve catch-all for the same unit.
    action = parse_action("show diff for unit 2")
    assert action.kind is ApproveKind.SHOW_DIFF
    assert action.unit_id == "unit-0002"


@pytest.mark.parametrize(
    "message",
    ["", "   ", "what is going on", "hello there", "unit", "please help me", "approveall pizza"],
)
def test_garbage_is_unknown(message: str) -> None:
    action = parse_action(message)
    assert action.kind is ApproveKind.UNKNOWN
    assert action.unit_id is None
    assert action.raw == message


def test_bare_approve_without_unit_is_approve_all() -> None:
    action = parse_action("approve")
    assert action.kind is ApproveKind.APPROVE_ALL
    assert action.unit_id is None


# ---------------------------------------------------------------------------
# Unit normalization helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    ["1", "unit 1", "unit1", "#1", "unit-0001", "unit-1", "  unit 1  ", "UNIT 1"],
)
def test_normalize_unit_id_canonical(token: str) -> None:
    assert normalize_unit_id(token) == "unit-0001"


def test_normalize_unit_id_wider_ordinal_preserved() -> None:
    assert normalize_unit_id("unit 12345") == "unit-12345"


@pytest.mark.parametrize("token", ["", "unit", "auth", "abc", "  "])
def test_normalize_unit_id_none(token: str) -> None:
    assert normalize_unit_id(token) is None


# ---------------------------------------------------------------------------
# Purity / determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    ["mission:approve:unit-0001", "approve unit 3", "diff unit 2", "lgtm", "abort", "garbage"],
)
def test_deterministic(message: str) -> None:
    first = parse_action(message)
    second = parse_action(message)
    assert first == second
    assert isinstance(first, ApproveAction)
