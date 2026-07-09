"""OpenClaw transport adapter for the accountable agent gateway.

OpenClaw is an async-agent *router*: it moves messages across chat platforms
(WebSocket / webhook) and, by design, "never reasons, only routes".  onmc is the
reasoning + accountability layer.  This module is the seam that lets OpenClaw be
the transport while onmc makes the trust decision:

1. :func:`parse_openclaw_event` normalizes an OpenClaw inbound envelope into a
   small frozen :class:`OpenClawInbound` (or ``None`` for non-actionable events).
2. :func:`handle_openclaw` feeds that into the *existing* gateway pipeline
   (:func:`oh_no_my_claudecode.gateway.pipeline.handle_inbound`) — the same
   deny / action / ignore / accept brain the daemon already uses — and turns the
   :class:`~oh_no_my_claudecode.gateway.pipeline.InboundResult` back into an
   OpenClaw-shaped outbound reply via :func:`to_openclaw_reply`.

Nothing here duplicates the auth / approve / intake decision tree; it only
translates envelopes.  Dispatch uses the same injectable-``dispatcher`` seam as
:mod:`oh_no_my_claudecode.gateway.server`, defaulting to the dry dispatcher so a
translated ``accepted`` message never spawns a swarm as a side effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.gateway.pipeline import (
    STATUS_ACCEPTED,
    STATUS_ACTION,
    STATUS_DENIED,
    STATUS_IGNORED,
    InboundResult,
    handle_inbound,
)
from oh_no_my_claudecode.gateway.server import Dispatcher, dry_dispatcher
from oh_no_my_claudecode.missionbridge.card import ACTION_ABORT, ACTION_APPROVE_ALL

__all__ = [
    "OpenClawInbound",
    "handle_openclaw",
    "parse_openclaw_event",
    "to_openclaw_reply",
]

#: OpenClaw event ``type`` values we treat as actionable chat messages.  When an
#: envelope carries no ``type`` at all we assume it is a message (many OpenClaw
#: platform bridges omit it); a present-but-non-message type (``"typing"`` /
#: ``"presence"`` / ``"system"`` …) is dropped as non-actionable.
_MESSAGE_TYPES = frozenset({"message", "chat", "text", "msg"})


@dataclass(frozen=True)
class OpenClawInbound:
    """A normalized, actionable OpenClaw inbound message.

    OpenClaw platform bridges use slightly different field names per platform;
    this dataclass is the single normalized shape the gateway consumes.

    Attributes
    ----------
    channel:
        Transport channel / platform name (``"slack"`` / ``"telegram"`` …),
        combined with :attr:`user_id` into the allowlist identity.
    user_id:
        The platform's raw sender id.
    text:
        The raw message body (OpenClaw envelope already stripped).
    mention:
        Bot handle to strip when parsing a new mission goal.
    """

    channel: str
    user_id: str
    text: str
    mention: str = "@onmc"


def _first_str(payload: dict[str, Any], *keys: str) -> str | None:
    """Return the first non-blank string among *payload*'s *keys*, else ``None``."""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def parse_openclaw_event(payload: dict[str, Any]) -> OpenClawInbound | None:
    """Normalize an OpenClaw webhook/WS envelope into an :class:`OpenClawInbound`.

    Returns ``None`` when the payload is not an actionable message: a non-dict
    body, a present-but-non-message ``type``, or a missing channel / sender /
    text field.  Never raises for ordinary input.

    Field aliases (OpenClaw bridges vary by platform):

    - channel ← ``channel`` | ``platform``
    - user    ← ``user`` | ``sender_id`` | ``user_id``
    - text    ← ``text`` | ``message``
    - mention ← ``mention`` (defaults to ``@onmc``)
    """
    if not isinstance(payload, dict):
        return None

    event_type = payload.get("type")
    if isinstance(event_type, str) and event_type.lower() not in _MESSAGE_TYPES:
        return None

    channel = _first_str(payload, "channel", "platform")
    user_id = _first_str(payload, "user", "sender_id", "user_id")
    text = _first_str(payload, "text", "message")
    if channel is None or user_id is None or text is None:
        return None

    mention = _first_str(payload, "mention") or "@onmc"
    return OpenClawInbound(channel=channel, user_id=user_id, text=text, mention=mention)


def _reply_text(result: InboundResult, card_text: str | None) -> str:
    """Build the human-facing reply body for one :class:`InboundResult`."""
    if result.status == STATUS_DENIED:
        base = f"⛔ Denied: {result.reason or 'not on the mission allowlist'}"
    elif result.status == STATUS_ACTION and result.action is not None:
        target = f" {result.action.unit_id}" if result.action.unit_id else ""
        base = f"🛠 Action: {result.action.kind}{target}"
    elif result.status == STATUS_IGNORED:
        base = f"🤷 Ignored: {result.reason or 'no goal in message'}"
    elif result.status == STATUS_ACCEPTED and result.task is not None:
        bits = [f"✅ Accepted mission: {result.task.goal}"]
        if result.task.concurrency is not None:
            bits.append(f"{result.task.concurrency} agents")
        if result.task.budget_usd is not None:
            bits.append(f"budget ${result.task.budget_usd:.2f}")
        base = " · ".join(bits)
    else:  # pragma: no cover - defensive; handle_inbound only returns the four above
        base = f"{result.status}"

    if card_text:
        return f"{base}\n\n{card_text}"
    return base


def _reply_buttons(result: InboundResult) -> list[dict[str, str]]:
    """Return mission-level buttons mirroring the shared card action ids.

    An ``accepted`` mission is the point at which a user may want to approve or
    abort, so we surface the same ``mission:approve_all`` / ``mission:abort``
    action ids the Slack/Telegram trust cards use — one parser handles all
    channels.  Other statuses carry no buttons.
    """
    if result.status != STATUS_ACCEPTED:
        return []
    return [
        {"text": "Approve all", "action_id": ACTION_APPROVE_ALL},
        {"text": "Abort", "action_id": ACTION_ABORT},
    ]


def to_openclaw_reply(
    result: InboundResult,
    *,
    card_text: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    """Turn a gateway :class:`InboundResult` into an OpenClaw-shaped reply dict.

    Pure — performs no network I/O.  The reply echoes the *channel* (when known),
    a human ``text`` body (optionally including a rendered trust *card_text*), and
    — for an accepted mission — ``buttons`` whose ``action_id``s mirror the
    mission-bridge card namespace so an OpenClaw button tap routes straight back
    through the same approve/abort parser.
    """
    reply: dict[str, Any] = {"status": result.status, "text": _reply_text(result, card_text)}
    if channel is not None:
        reply["channel"] = channel
    if result.reason is not None:
        reply["reason"] = result.reason
    buttons = _reply_buttons(result)
    if buttons:
        reply["buttons"] = buttons
    return reply


def handle_openclaw(
    repo_root: Path | str,
    payload: dict[str, Any],
    *,
    dispatcher: Dispatcher | None = None,
) -> dict[str, Any]:
    """Route one OpenClaw event through the gateway and return an OpenClaw reply.

    Glue only: :func:`parse_openclaw_event` → :func:`handle_inbound` →
    :func:`to_openclaw_reply`.  A non-actionable payload short-circuits to an
    ``ignored`` reply.  An ``accepted`` mission invokes *dispatcher* (default
    :func:`~oh_no_my_claudecode.gateway.server.dry_dispatcher`, which spawns
    nothing) exactly as the HTTP gateway does, and folds its JSON-safe result
    under ``dispatch``.  Never raises for ordinary input.
    """
    inbound = parse_openclaw_event(payload)
    if inbound is None:
        return {
            "status": STATUS_IGNORED,
            "text": "🤷 Not an actionable OpenClaw message.",
            "reason": "not-a-message",
        }

    dispatch = dispatcher or dry_dispatcher
    result = handle_inbound(
        repo_root,
        channel=inbound.channel,
        user_id=inbound.user_id,
        text=inbound.text,
        mention=inbound.mention,
    )
    reply = to_openclaw_reply(result, channel=inbound.channel)
    if result.status == STATUS_ACCEPTED and result.task is not None:
        reply["dispatch"] = dispatch(Path(repo_root), result.task)
    return reply
