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

from oh_no_my_claudecode.missionbridge.approve import normalize_unit_id, parse_action
from oh_no_my_claudecode.missionbridge.auth import (
    add_identity,
    authorize,
    load_policy,
    remove_identity,
)
from oh_no_my_claudecode.missionbridge.card import (
    build_card,
    render_plain,
    render_slack_blocks,
    render_telegram,
)
from oh_no_my_claudecode.missionbridge.intake import parse_intake
from oh_no_my_claudecode.missionbridge.models import (
    ApproveAction,
    ApproveKind,
    AuthDecision,
    AuthPolicy,
    IntakeTask,
    MissionCard,
    UnitLine,
)

__all__ = [
    # models
    "ApproveAction",
    "ApproveKind",
    "AuthDecision",
    "AuthPolicy",
    "IntakeTask",
    "MissionCard",
    "UnitLine",
    # card
    "build_card",
    "render_slack_blocks",
    "render_telegram",
    "render_plain",
    # approve
    "parse_action",
    "normalize_unit_id",
    # intake
    "parse_intake",
    # auth
    "load_policy",
    "authorize",
    "add_identity",
    "remove_identity",
]
