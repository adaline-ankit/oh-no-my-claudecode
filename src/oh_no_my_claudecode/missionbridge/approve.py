"""Approve-intent parser for the mission bridge.

Turns a single chat reply — a button ``callback_data`` id *or* free-text
natural language — into a structured
:class:`~oh_no_my_claudecode.missionbridge.models.ApproveAction`.

The parser is intentionally **pure and deterministic**: no I/O, no clock, no
randomness.  The same input always yields the same action, so it is trivially
offline-testable and safe to run inside a webhook handler.

Two input dialects are supported:

Button callback ids (emitted by the card renderers)
    ``mission:approve_all`` · ``mission:approve:unit-0001`` ·
    ``mission:show_diff:unit-0001`` · ``mission:abort``.

Natural language (a human typing in the channel)
    ``"approve all"`` / ``"ship it"`` / ``"lgtm"`` → APPROVE_ALL,
    ``"approve unit 1"`` / ``"merge auth"`` → APPROVE_UNIT,
    ``"show diff unit 2"`` / ``"diff unit-0002"`` → SHOW_DIFF,
    ``"abort"`` / ``"stop"`` / ``"kill"`` → ABORT,
    anything unrecognised → UNKNOWN.

The original message is always retained on the action for auditing.
"""

from __future__ import annotations

import re

from oh_no_my_claudecode.missionbridge.models import ApproveAction, ApproveKind

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Prefix every structured button id carries.
_CALLBACK_PREFIX = "mission:"

#: Width the ``unit-000N`` convention zero-pads unit ordinals to.
_UNIT_PAD = 4

#: A bare unit reference: ``unit-0001`` / ``unit 1`` / ``unit1`` / ``#1`` / ``1``.
_UNIT_TOKEN_RE = re.compile(r"(?:unit[\s._-]*|#)?0*(\d+)\b", re.IGNORECASE)

#: Locate a unit reference embedded anywhere in a natural-language phrase.
_UNIT_IN_TEXT_RE = re.compile(r"(?:unit[\s._-]*|#)0*(\d+)\b", re.IGNORECASE)

#: Whole-mission approval phrases.
_APPROVE_ALL_PHRASES = frozenset(
    {
        "approve all",
        "approve everything",
        "approve",
        "ship it",
        "ship",
        "shipit",
        "lgtm",
        "looks good",
        "looks good to me",
        "merge all",
        "merge everything",
        "yes",
        "go",
    }
)

#: Abort phrases.
_ABORT_PHRASES = frozenset(
    {
        "abort",
        "stop",
        "kill",
        "cancel",
        "halt",
        "no",
    }
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize_unit_id(token: str) -> str | None:
    """Normalize a loose unit reference to the canonical ``unit-000N`` form.

    Accepts ``"unit-0001"``, ``"unit 1"``, ``"unit1"``, ``"#1"`` or a bare
    ``"1"`` and returns ``"unit-0001"``.  Returns ``None`` when *token* carries
    no recognisable ordinal.

    The ordinal is zero-padded to :data:`_UNIT_PAD` digits; ordinals already
    wider than the pad are preserved (e.g. ``"unit 12345"`` → ``"unit-12345"``).
    """

    if not token:
        return None
    match = _UNIT_TOKEN_RE.fullmatch(token.strip())
    if match is None:
        return None
    return f"unit-{int(match.group(1)):0{_UNIT_PAD}d}"


def _first_unit_in_text(text: str) -> str | None:
    """Return the first embedded ``unit-000N`` reference in *text*, if any."""

    match = _UNIT_IN_TEXT_RE.search(text)
    if match is None:
        return None
    return f"unit-{int(match.group(1)):0{_UNIT_PAD}d}"


def _normalize(message: str) -> str:
    """Lower-case and collapse whitespace/punctuation noise for matching."""

    lowered = message.strip().lower()
    # Drop leading command noise like a bot mention or a slash-command prefix.
    lowered = lowered.lstrip("/@!")
    # Collapse runs of whitespace so multi-space input matches phrase sets.
    return re.sub(r"\s+", " ", lowered).strip()


def _parse_callback(message: str) -> ApproveAction | None:
    """Parse a structured ``mission:...`` button id, or ``None`` if not one."""

    stripped = message.strip()
    if not stripped.lower().startswith(_CALLBACK_PREFIX):
        return None

    body = stripped[len(_CALLBACK_PREFIX) :]
    parts = body.split(":")
    verb = parts[0].strip().lower()

    if verb == "approve_all":
        return ApproveAction(ApproveKind.APPROVE_ALL, None, message)
    if verb == "abort":
        return ApproveAction(ApproveKind.ABORT, None, message)
    if verb == "approve" and len(parts) >= 2:
        unit_id = normalize_unit_id(parts[1])
        if unit_id is not None:
            return ApproveAction(ApproveKind.APPROVE_UNIT, unit_id, message)
    if verb == "show_diff" and len(parts) >= 2:
        unit_id = normalize_unit_id(parts[1])
        if unit_id is not None:
            return ApproveAction(ApproveKind.SHOW_DIFF, unit_id, message)

    # A ``mission:`` id we don't recognise — deliberately UNKNOWN, not a guess.
    return ApproveAction(ApproveKind.UNKNOWN, None, message)


def _parse_natural_language(message: str) -> ApproveAction:
    """Parse free-text chat into an :class:`ApproveAction` (never ``None``)."""

    text = _normalize(message)
    if not text:
        return ApproveAction(ApproveKind.UNKNOWN, None, message)

    # Order matters: diff and per-unit approvals are checked before the broad
    # whole-mission / abort phrase sets so "approve unit 1" isn't swallowed by
    # the "approve" catch-all.
    if re.search(r"\b(show[\s._-]*diff|diff)\b", text):
        unit_id = _first_unit_in_text(text)
        if unit_id is not None:
            return ApproveAction(ApproveKind.SHOW_DIFF, unit_id, message)

    unit_id = _first_unit_in_text(text)
    if re.search(r"\b(approve|merge|ship|accept)\b", text) and unit_id is not None:
        return ApproveAction(ApproveKind.APPROVE_UNIT, unit_id, message)

    if text in _ABORT_PHRASES:
        return ApproveAction(ApproveKind.ABORT, None, message)

    if text in _APPROVE_ALL_PHRASES:
        return ApproveAction(ApproveKind.APPROVE_ALL, None, message)

    return ApproveAction(ApproveKind.UNKNOWN, None, message)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_action(message: str) -> ApproveAction:
    """Resolve a chat *message* into a structured :class:`ApproveAction`.

    Handles both button ``callback_data`` ids (``mission:...``) and free-text
    natural language.  The raw *message* is always retained on the returned
    action.  Unrecognised input resolves to :attr:`ApproveKind.UNKNOWN` rather
    than raising, so a webhook can always answer.
    """

    if not message or not message.strip():
        return ApproveAction(ApproveKind.UNKNOWN, None, message)

    callback = _parse_callback(message)
    if callback is not None:
        return callback

    return _parse_natural_language(message)
