"""Shared, pure dataclasses for the mission bridge.

These are the contract every bridge piece (card / approve / intake / auth)
depends on.  Kept free of I/O so they stay trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ApproveKind(StrEnum):
    """The action a chat reply resolves to."""

    APPROVE_ALL = "approve_all"
    APPROVE_UNIT = "approve_unit"
    ABORT = "abort"
    SHOW_DIFF = "show_diff"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ApproveAction:
    """A parsed chat command against a mission.

    Attributes
    ----------
    kind:
        The resolved :class:`ApproveKind`.
    unit_id:
        Target unit (e.g. ``"unit-0001"``) for ``APPROVE_UNIT`` / ``SHOW_DIFF``;
        ``None`` for whole-mission actions.
    raw:
        The original message text, retained for auditing.
    """

    kind: ApproveKind
    unit_id: str | None = None
    raw: str = ""


@dataclass(frozen=True)
class IntakeTask:
    """A chat message normalized into a mission request.

    Attributes
    ----------
    goal:
        The free-text engineering goal to plan a mission around.
    concurrency:
        Requested fan-out width, if the message specified one.
    budget_usd:
        Requested run budget cap, if specified.
    """

    goal: str
    concurrency: int | None = None
    budget_usd: float | None = None


@dataclass(frozen=True)
class UnitLine:
    """One unit's row in the trust card.

    ``verified`` and ``held`` are the trust signals: a held unit produced no
    real/verified work and is intentionally NOT shipped as a PR.
    """

    unit_id: str
    goal: str
    status: str
    verified: bool
    held: bool
    cost_usd: float | None = None
    diff_sha: str | None = None
    receipt_hash: str | None = None
    pr_url: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class MissionCard:
    """The channel-agnostic trust report for a finished or in-flight mission.

    Renderers (Slack blocks / Telegram / plain) consume this; they never read
    swarm state directly.
    """

    mission_id: str
    goal: str
    units: list[UnitLine] = field(default_factory=list)
    total_cost_usd: float | None = None
    generated_note: str = ""

    @property
    def verified_count(self) -> int:
        return sum(1 for u in self.units if u.verified and not u.held)

    @property
    def held_count(self) -> int:
        return sum(1 for u in self.units if u.held)

    @property
    def unit_count(self) -> int:
        return len(self.units)


@dataclass(frozen=True)
class AuthDecision:
    """Result of an allowlist check."""

    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class AuthPolicy:
    """Who may command a mission from a channel.

    A deny-by-default allowlist keyed by channel-scoped identity
    (e.g. ``"slack:U123"`` / ``"telegram:456"``).  An empty allowlist denies
    everyone unless :attr:`open_when_empty` is set (single-user local default).
    """

    allowed_identities: frozenset[str] = frozenset()
    open_when_empty: bool = False

    def decide(self, identity: str) -> AuthDecision:
        if identity in self.allowed_identities:
            return AuthDecision(True, "allowlisted")
        if not self.allowed_identities and self.open_when_empty:
            return AuthDecision(True, "open (no allowlist configured)")
        return AuthDecision(False, "not on the mission allowlist")
