"""Pure policy decision broker; this module never executes actions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .audit import AuditLog
from .models import Action, ActionType, Capability, Decision, DecisionEffect, Policy
from .redaction import redact_secrets
from .tokens import CapabilityToken, TokenAuthority


class ToolBroker:
    """Evaluate declared actions against policy and signed capabilities."""

    def __init__(
        self,
        *,
        policy: Policy | None = None,
        token_authority: TokenAuthority,
        audit_log: AuditLog | None = None,
        clock: Callable[[], datetime] | None = None,
        secret_values: tuple[str, ...] = (),
    ) -> None:
        self.policy = policy or Policy()
        self.token_authority = token_authority
        self.audit_log = audit_log
        self._clock = clock or (lambda: datetime.now(UTC))
        self._secret_values = tuple(secret_values)

    def issue_token(
        self,
        *,
        subject: str,
        capabilities: Iterable[Capability],
        ttl: timedelta,
    ) -> str:
        return self.token_authority.issue(
            subject=subject,
            capabilities=capabilities,
            ttl=ttl,
        )

    def decide(
        self,
        action: Action,
        *,
        tokens: Iterable[str] = (),
        subject: str | None = None,
    ) -> Decision:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("broker clock must return a timezone-aware datetime")
        denied = sorted(
            rule.rule_id
            for rule in self.policy.rules
            if rule.effect is DecisionEffect.DENY
            and rule.capability.matches(action, match_verifier=False)
        )
        matching_rules = [rule for rule in self.policy.rules if rule.capability.matches(action)]
        verified_tokens = self._verify_tokens(tokens, subject=subject, now=now)
        matching_tokens = sorted(
            token.token_id
            for token in verified_tokens
            if any(capability.matches(action) for capability in token.capabilities)
        )

        if denied:
            decision = Decision(DecisionEffect.DENY, "policy_deny", tuple(denied))
        elif matching_tokens:
            reason = "explicit_verifier_capability" if action.verifier else "capability_token"
            decision = Decision(
                DecisionEffect.ALLOW,
                reason,
                matched_token_ids=tuple(matching_tokens),
            )
        else:
            allowed = sorted(
                rule.rule_id for rule in matching_rules if rule.effect is DecisionEffect.ALLOW
            )
            approvals = sorted(
                rule.rule_id
                for rule in matching_rules
                if rule.effect is DecisionEffect.REQUIRE_APPROVAL
            )
            if approvals:
                decision = Decision(
                    DecisionEffect.REQUIRE_APPROVAL,
                    "policy_approval_required",
                    tuple(approvals),
                )
            elif allowed:
                decision = Decision(DecisionEffect.ALLOW, "policy_allow", tuple(allowed))
            else:
                decision = Decision(DecisionEffect.DENY, "default_deny")

        if action.action_type is ActionType.FILESYSTEM and action.path is not None:
            decision = replace(
                decision,
                resolved_path=str(Path(action.path).resolve(strict=False)),
            )

        self._audit(action, decision, subject=subject)
        return decision

    def _verify_tokens(
        self,
        tokens: Iterable[str],
        *,
        subject: str | None,
        now: datetime,
    ) -> list[CapabilityToken]:
        if subject is None:
            return []
        verified: list[CapabilityToken] = []
        for raw_token in tokens:
            token = self.token_authority.verify(raw_token, subject=subject, now=now)
            if token is not None:
                verified.append(token)
        return verified

    def _audit(self, action: Action, decision: Decision, *, subject: str | None) -> None:
        if self.audit_log is None:
            return
        payload: dict[str, object] = {
            "action": action.audit_payload(),
            "decision": {
                "effect": decision.effect.value,
                "reason_code": decision.reason_code,
                "matched_rule_ids": list(decision.matched_rule_ids),
                "matched_token_ids": list(decision.matched_token_ids),
                "resolved_path": decision.resolved_path,
            },
        }
        if subject is not None:
            payload["subject"] = subject
        clean = redact_secrets(payload, secret_values=self._secret_values)
        self.audit_log.append("policy_decision", clean)
