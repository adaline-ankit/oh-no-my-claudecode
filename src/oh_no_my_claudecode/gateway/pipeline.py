"""The pure core of the accountable agent gateway.

:func:`handle_inbound` is the single decision function the live transports call.
It is deterministic and offline-friendly: the only I/O it performs is reading
the mission allowlist (via :mod:`oh_no_my_claudecode.missionbridge.auth`), so it
can be exercised in tests without a socket, a clock, or a network.

It reuses the mission-bridge brain wholesale rather than reinventing any policy:

1. **Authorize** the channel-scoped identity via
   :func:`~oh_no_my_claudecode.missionbridge.auth.authorize` — a denied identity
   short-circuits to ``status="denied"`` (deny-by-default).
2. **Approve/abort?** — if the text resolves to a non-``UNKNOWN``
   :class:`~oh_no_my_claudecode.missionbridge.models.ApproveKind` via
   :func:`~oh_no_my_claudecode.missionbridge.approve.parse_action`, it is an
   action against an in-flight mission → ``status="action"``.
3. **New mission?** — otherwise
   :func:`~oh_no_my_claudecode.missionbridge.intake.parse_intake` normalizes the
   text into an :class:`~oh_no_my_claudecode.missionbridge.models.IntakeTask`;
   no goal (empty / mention-only) → ``status="ignored"``, a goal →
   ``status="accepted"``.

The order matters: an approval reply ("ship it") must never be mistaken for a
new mission goal, so the action check runs before intake.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from oh_no_my_claudecode.missionbridge.approve import parse_action
from oh_no_my_claudecode.missionbridge.auth import authorize, load_policy
from oh_no_my_claudecode.missionbridge.intake import parse_intake
from oh_no_my_claudecode.missionbridge.models import ApproveAction, ApproveKind, IntakeTask

__all__ = ["InboundResult", "handle_inbound"]

#: The four terminal decisions the gateway can reach for one inbound message.
STATUS_DENIED = "denied"
STATUS_ACTION = "action"
STATUS_IGNORED = "ignored"
STATUS_ACCEPTED = "accepted"


@dataclass(frozen=True)
class InboundResult:
    """The outcome of routing one inbound chat message through the gateway.

    Exactly one of :attr:`task` / :attr:`action` is populated, and only for the
    matching :attr:`status`:

    - ``"denied"``   — identity not on the allowlist; :attr:`reason` explains.
    - ``"action"``   — an approve/abort reply; :attr:`action` carries it.
    - ``"ignored"``  — authorized, but no goal (empty / mention-only).
    - ``"accepted"`` — a new mission; :attr:`task` carries the goal + options.
    """

    status: str
    reason: str | None = None
    task: IntakeTask | None = None
    action: ApproveAction | None = None


def handle_inbound(
    repo_root: Path | str,
    *,
    channel: str,
    user_id: str,
    text: str,
    mention: str = "@onmc",
) -> InboundResult:
    """Route one inbound chat *text* into an :class:`InboundResult`.

    Parameters
    ----------
    repo_root:
        Repository root whose ``.onmc/mission-allowlist.json`` gates access.
    channel:
        Transport channel name (``"slack"`` / ``"telegram"`` / ``"openclaw"`` …);
        combined with *user_id* into the channel-scoped allowlist identity.
    user_id:
        The transport's raw user id.
    text:
        The raw user message (transport envelope already stripped).
    mention:
        Bot handle to strip when parsing a new mission goal.

    Returns
    -------
    InboundResult
        A deny/action/ignore/accept decision — never raises for ordinary input.
    """
    root = Path(repo_root)

    decision = authorize(load_policy(root), channel=channel, user_id=user_id)
    if not decision.allowed:
        return InboundResult(status=STATUS_DENIED, reason=decision.reason)

    action = parse_action(text)
    if action.kind is not ApproveKind.UNKNOWN:
        return InboundResult(status=STATUS_ACTION, action=action)

    task = parse_intake(text, mention=mention)
    if task is None:
        return InboundResult(status=STATUS_IGNORED, reason="no goal in message")
    return InboundResult(status=STATUS_ACCEPTED, task=task)
