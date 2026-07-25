"""A reference monitor that composes the tool broker into an enforcement gate.

The :class:`~oh_no_my_claudecode.tool_broker.ToolBroker` is the *decision* primitive:
given a declared :class:`~oh_no_my_claudecode.tool_broker.Action` it returns an
allow / deny / require-approval :class:`~oh_no_my_claudecode.tool_broker.Decision`,
and it never touches the filesystem, a process, the network, or a secret store.

This module adds the classic *reference-monitor* wrapper around that decision:

* every supported effect (filesystem, command, network, secret) crosses
  :meth:`ReferenceMonitor.guard`, which delegates the decision to the broker;
* a **denied** effect is a no-op — the monitor never performs an effect itself and,
  in enforced mode, never hands a denied effect to the caller-supplied
  :class:`EffectExecutor` (so a DENY leaves no side effect);
* an **egress allowlist** screens network effects: a host not on the allowlist is
  denied even if the broker would otherwise allow it (composition never loosens);
* an explicit *requires-approval* path escalates capability-elevation / destructive
  effects to human approval;
* an append-only :class:`DecisionRecord` trace captures every allow / deny / escalate
  with its reason and the taint provenance of the inputs — with secret material
  scrubbed via the broker's own redaction helper.

The monitor can be constructed as ``ReferenceMonitor(enforced=False)``; that flag
labels it *advisory* — it still records what it *would* decide, but its verdicts do
not block execution, and every trace record says so.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast

from oh_no_my_claudecode.tool_broker import (
    Action,
    ActionType,
    Decision,
    DecisionEffect,
    NetworkRule,
    ToolBroker,
    redact_secrets,
)

from .taint import SecretHandle, TaintLabel

_OUTCOME: dict[DecisionEffect, str] = {
    DecisionEffect.ALLOW: "allow",
    DecisionEffect.DENY: "deny",
    DecisionEffect.REQUIRE_APPROVAL: "escalate",
}


@dataclass(frozen=True)
class Effect:
    """A declared side-effecting operation submitted to the reference monitor.

    Wraps a broker :class:`Action` (the decision primitive) with the taint
    provenance of the inputs that motivated it, any :class:`SecretHandle` objects the
    effect references (for egress screening), and a ``requires_approval`` flag that
    forces capability-elevation / destructive intents onto the approval path.
    """

    action: Action
    provenance: frozenset[TaintLabel] = field(default_factory=frozenset)
    secret_handles: tuple[SecretHandle, ...] = ()
    requires_approval: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance", frozenset(self.provenance))
        object.__setattr__(self, "secret_handles", tuple(self.secret_handles))
        if any(not isinstance(label, TaintLabel) for label in self.provenance):
            raise ValueError("provenance must contain only TaintLabel members")
        if any(not isinstance(handle, SecretHandle) for handle in self.secret_handles):
            raise ValueError("secret_handles must contain only SecretHandle objects")

    @classmethod
    def filesystem(
        cls,
        operation: str,
        path: str | Path,
        *,
        provenance: Iterable[TaintLabel] = (),
        requires_approval: bool = False,
    ) -> Effect:
        return cls(
            Action.filesystem(operation, path),
            provenance=frozenset(provenance),
            requires_approval=requires_approval,
        )

    @classmethod
    def command(
        cls,
        argv: tuple[str, ...] | list[str],
        *,
        provenance: Iterable[TaintLabel] = (),
        requires_approval: bool = False,
    ) -> Effect:
        return cls(
            Action.command(argv),
            provenance=frozenset(provenance),
            requires_approval=requires_approval,
        )

    @classmethod
    def network(
        cls,
        operation: str,
        host: str,
        port: int | None = None,
        *,
        provenance: Iterable[TaintLabel] = (),
        secret_handles: Iterable[SecretHandle] = (),
        requires_approval: bool = False,
    ) -> Effect:
        return cls(
            Action.network(operation, host, port),
            provenance=frozenset(provenance),
            secret_handles=tuple(secret_handles),
            requires_approval=requires_approval,
        )

    @classmethod
    def secret(
        cls,
        operation: str,
        name: str,
        *,
        secret_handles: Iterable[SecretHandle] = (),
        provenance: Iterable[TaintLabel] = (),
        requires_approval: bool = False,
    ) -> Effect:
        return cls(
            Action.secret(operation, name),
            provenance=frozenset(provenance),
            secret_handles=tuple(secret_handles),
            requires_approval=requires_approval,
        )


@dataclass(frozen=True)
class DecisionRecord:
    """One append-only entry in the reference monitor's decision trace."""

    effect_kind: str
    outcome: str  # "allow" | "deny" | "escalate"
    reason: str
    enforced: bool  # False => advisory: the verdict did not block execution
    provenance: tuple[str, ...]
    resource: str  # redacted human summary — never a raw secret value
    matched_rule_ids: tuple[str, ...]

    @property
    def mode(self) -> str:
        return "enforced" if self.enforced else "advisory"

    def to_dict(self) -> dict[str, object]:
        return {
            "effect_kind": self.effect_kind,
            "outcome": self.outcome,
            "reason": self.reason,
            "mode": self.mode,
            "enforced": self.enforced,
            "provenance": list(self.provenance),
            "resource": self.resource,
            "matched_rule_ids": list(self.matched_rule_ids),
        }


@dataclass(frozen=True)
class EnforcementResult:
    """Outcome of :meth:`ReferenceMonitor.enforce`."""

    decision: Decision
    performed: bool  # whether the executor was actually invoked
    advisory: bool  # True when the monitor was in advisory (non-enforcing) mode

    @property
    def blocked(self) -> bool:
        """True when the effect was prevented from running (enforced deny/escalate)."""
        return not self.performed


class EffectExecutor(Protocol):
    """The separately-owned party that actually performs an authorized effect.

    The reference monitor only *authorizes*; it hands an effect to an executor
    exclusively after an ALLOW verdict in enforced mode. Tests supply a spy
    implementation to prove a denied effect is never handed over.
    """

    def execute(self, effect: Effect) -> object: ...


def _summarize(action: Action, secret_values: tuple[str, ...]) -> str:
    """A short, secret-scrubbed description of an action for the trace."""
    if action.action_type is ActionType.COMMAND:
        raw = " ".join(action.argv)
    elif action.action_type is ActionType.FILESYSTEM:
        raw = action.path or ""
    elif action.action_type is ActionType.NETWORK:
        raw = action.host or ""
        if action.port is not None:
            raw = f"{raw}:{action.port}"
    else:
        raw = action.resource
    scrubbed = redact_secrets(f"{action.operation} {raw}".strip(), secret_values=secret_values)
    return cast(str, scrubbed)


class ReferenceMonitor:
    """Authorize declared effects by composing the tool broker's decisions."""

    def __init__(
        self,
        broker: ToolBroker,
        *,
        enforced: bool = True,
        egress_allowlist: Iterable[str] = (),
        subject: str | None = None,
        tokens: Iterable[str] = (),
        secret_values: tuple[str, ...] = (),
    ) -> None:
        self._broker = broker
        self._enforced = enforced
        self._egress_rules: tuple[NetworkRule, ...] = tuple(
            NetworkRule(host) for host in egress_allowlist
        )
        self._subject = subject
        self._tokens = tuple(tokens)
        self._secret_values = tuple(secret_values)
        self._trace: list[DecisionRecord] = []

    @property
    def enforced(self) -> bool:
        return self._enforced

    @property
    def advisory(self) -> bool:
        return not self._enforced

    @property
    def trace(self) -> tuple[DecisionRecord, ...]:
        """The append-only decision trace as an immutable snapshot."""
        return tuple(self._trace)

    def trace_dicts(self) -> list[dict[str, object]]:
        return [record.to_dict() for record in self._trace]

    def guard(self, effect: Effect) -> Decision:
        """Return the allow / deny / escalate decision for *effect* and trace it.

        Delegates the core decision to :meth:`ToolBroker.decide`, then layers the
        egress allowlist and the requires-approval elevation path on top. Neither
        layer can loosen a broker DENY. The taint provenance of the effect is
        recorded but never consulted when computing the verdict.
        """
        action = effect.action
        decision = self._broker.decide(action, tokens=self._tokens, subject=self._subject)

        # Egress allowlist: a network host that is not explicitly allowlisted is
        # denied even when the broker would allow it. Deny is never loosened.
        if (
            action.action_type is ActionType.NETWORK
            and decision.effect is not DecisionEffect.DENY
            and not self._egress_allowed(action.host, action.port)
        ):
            decision = Decision(DecisionEffect.DENY, "egress_not_allowlisted")

        # Capability-elevation / destructive intent is pushed onto the approval
        # path even if a broker rule would have allowed it outright.
        if effect.requires_approval and decision.effect is DecisionEffect.ALLOW:
            decision = Decision(DecisionEffect.REQUIRE_APPROVAL, "elevation_requires_approval")

        self._record(effect, decision)
        return decision

    def enforce(self, effect: Effect, executor: EffectExecutor) -> EnforcementResult:
        """Guard *effect*, then hand it to *executor* only when truly authorized.

        In enforced mode the executor is invoked exclusively on an ALLOW verdict;
        a DENY or ESCALATE leaves the executor untouched, so a denied effect has
        no side effect. In advisory mode the verdict cannot block: the executor is
        always invoked and the trace records the run as advisory.
        """
        decision = self.guard(effect)
        allowed = decision.effect is DecisionEffect.ALLOW

        if self._enforced:
            if allowed:
                executor.execute(effect)
                return EnforcementResult(decision, performed=True, advisory=False)
            return EnforcementResult(decision, performed=False, advisory=False)

        # Advisory mode: the monitor observes but cannot stop the effect.
        executor.execute(effect)
        return EnforcementResult(decision, performed=True, advisory=True)

    def _egress_allowed(self, host: str | None, port: int | None) -> bool:
        if host is None:
            return False
        return any(rule.matches(host, port) for rule in self._egress_rules)

    def _record(self, effect: Effect, decision: Decision) -> None:
        record = DecisionRecord(
            effect_kind=effect.action.action_type.value,
            outcome=_OUTCOME[decision.effect],
            reason=decision.reason_code,
            enforced=self._enforced,
            provenance=tuple(sorted(label.value for label in effect.provenance)),
            resource=_summarize(effect.action, self._secret_values),
            matched_rule_ids=decision.matched_rule_ids,
        )
        self._trace.append(record)


__all__ = [
    "DecisionRecord",
    "Effect",
    "EffectExecutor",
    "EnforcementResult",
    "ReferenceMonitor",
]
