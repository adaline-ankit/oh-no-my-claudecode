"""Mission bridge — turn a swarm mission into a chat experience.

Composes the existing engine (``mission`` planner, ``missioncontrol`` dashboard
reader, ``swarm`` + tamper-evident receipts) into the pieces a chat gateway
(Slack / Telegram / Claude Code Channels) needs:

- a channel-agnostic **trust card** built from the swarm manifest + receipts
  (:mod:`.card`),
- an **approve-intent** parser for chat replies (:mod:`.approve`),
- an **intake** normalizer that turns a chat message into a mission goal
  (:mod:`.intake`),
- an **auth** allowlist deciding who may command the swarm (:mod:`.auth`).

Every piece is pure + offline-testable; the live inbound-webhook wiring lives
outside this module.
"""

from __future__ import annotations

from oh_no_my_claudecode.missionbridge.models import (
    ApproveAction,
    AuthPolicy,
    IntakeTask,
    MissionCard,
    UnitLine,
)

__all__ = [
    "ApproveAction",
    "AuthPolicy",
    "IntakeTask",
    "MissionCard",
    "UnitLine",
]
