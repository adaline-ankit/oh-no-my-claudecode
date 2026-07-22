"""Adversarial tests for the deny-by-default policy tool broker."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from oh_no_my_claudecode.tool_broker import (
    Action,
    ActionType,
    AuditLog,
    Capability,
    CommandRule,
    DecisionEffect,
    NetworkRule,
    PathRule,
    Policy,
    PolicyRule,
    TokenAuthority,
    ToolBroker,
    redact_secrets,
)

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
SIGNING_KEY = b"test-only-signing-key-with-enough-entropy"


def _broker(
    *rules: PolicyRule,
    audit_log: AuditLog | None = None,
    secret_values: tuple[str, ...] = (),
) -> ToolBroker:
    return ToolBroker(
        policy=Policy(tuple(rules)),
        token_authority=TokenAuthority(SIGNING_KEY, clock=lambda: NOW),
        audit_log=audit_log,
        clock=lambda: NOW,
        secret_values=secret_values,
    )


def _token(
    broker: ToolBroker,
    *capabilities: Capability,
    ttl: timedelta = timedelta(minutes=5),
    subject: str = "agent-1",
) -> str:
    return broker.issue_token(subject=subject, capabilities=capabilities, ttl=ttl)


class TestDefaultAndPolicyDecisions:
    def test_unknown_actions_are_denied_by_default(self) -> None:
        decision = _broker().decide(Action.tool("mcp.read", operation="invoke"))

        assert decision.effect is DecisionEffect.DENY
        assert decision.reason_code == "default_deny"

    @pytest.mark.parametrize(
        ("action", "capability"),
        [
            (
                Action.tool("mcp.read"),
                Capability(ActionType.TOOL, resources=frozenset({"mcp.read"})),
            ),
            (
                Action.secret("read", "DEPLOY_TOKEN"),
                Capability(
                    ActionType.SECRET,
                    operations=frozenset({"read"}),
                    resources=frozenset({"DEPLOY_TOKEN"}),
                ),
            ),
            (
                Action.budget("spend", "llm-usd", amount=2.5),
                Capability(
                    ActionType.BUDGET,
                    operations=frozenset({"spend"}),
                    resources=frozenset({"llm-usd"}),
                    max_amount=3.0,
                ),
            ),
            (
                Action.deployment("promote", "staging"),
                Capability(
                    ActionType.DEPLOYMENT,
                    operations=frozenset({"promote"}),
                    resources=frozenset({"staging"}),
                ),
            ),
        ],
    )
    def test_scoped_tokens_allow_only_matching_actions(
        self, action: Action, capability: Capability
    ) -> None:
        broker = _broker()
        token = _token(broker, capability)

        decision = broker.decide(action, tokens=[token], subject="agent-1")

        assert decision.effect is DecisionEffect.ALLOW
        assert decision.reason_code == "capability_token"

    def test_approval_is_only_returned_by_an_explicit_policy_rule(self) -> None:
        approval = PolicyRule(
            "approve-network",
            DecisionEffect.REQUIRE_APPROVAL,
            Capability(
                ActionType.NETWORK,
                operations=frozenset({"connect"}),
                network_rules=(NetworkRule("api.example.com", ports=frozenset({443})),),
            ),
        )
        broker = _broker(approval)

        decision = broker.decide(Action.network("connect", "api.example.com", 443))

        assert decision.effect is DecisionEffect.REQUIRE_APPROVAL
        assert decision.reason_code == "policy_approval_required"
        assert decision.matched_rule_ids == ("approve-network",)

    def test_explicit_deny_wins_over_token_and_allow_regardless_of_rule_order(self) -> None:
        scope = Capability(ActionType.TOOL, resources=frozenset({"dangerous"}))
        allow = PolicyRule("z-allow", DecisionEffect.ALLOW, scope)
        deny = PolicyRule("a-deny", DecisionEffect.DENY, scope)
        broker = _broker(allow, deny)
        token = _token(broker, scope)

        decision = broker.decide(Action.tool("dangerous"), tokens=[token], subject="agent-1")

        assert decision.effect is DecisionEffect.DENY
        assert decision.reason_code == "policy_deny"
        assert decision.matched_rule_ids == ("a-deny",)

    def test_verifier_label_cannot_bypass_an_ordinary_deny(self) -> None:
        command = CommandRule(("rm", "-rf", "/"), exact=True)
        broker = _broker(
            PolicyRule(
                "deny-destructive",
                DecisionEffect.DENY,
                Capability(ActionType.COMMAND, command_rules=(command,)),
            )
        )
        verifier_token = _token(
            broker,
            Capability(ActionType.COMMAND, command_rules=(command,), verifier=True),
        )

        decision = broker.decide(
            Action.command(command.argv, verifier=True),
            tokens=[verifier_token],
            subject="agent-1",
        )

        assert decision.effect is DecisionEffect.DENY
        assert decision.matched_rule_ids == ("deny-destructive",)

    def test_approval_rule_wins_over_overlapping_allow_rule(self) -> None:
        scope = Capability(ActionType.TOOL, resources=frozenset({"sensitive"}))
        broker = _broker(
            PolicyRule("allow-broadly", DecisionEffect.ALLOW, scope),
            PolicyRule("approve-sensitive", DecisionEffect.REQUIRE_APPROVAL, scope),
        )

        decision = broker.decide(Action.tool("sensitive"))

        assert decision.effect is DecisionEffect.REQUIRE_APPROVAL
        assert decision.matched_rule_ids == ("approve-sensitive",)

    def test_decisions_are_deterministic_and_rule_ids_are_sorted(self) -> None:
        scope = Capability(ActionType.TOOL, resources=frozenset({"read"}))
        broker = _broker(
            PolicyRule("z-rule", DecisionEffect.REQUIRE_APPROVAL, scope),
            PolicyRule("a-rule", DecisionEffect.REQUIRE_APPROVAL, scope),
        )
        action = Action.tool("read")

        first = broker.decide(action)
        second = broker.decide(action)

        assert first == second
        assert first.matched_rule_ids == ("a-rule", "z-rule")


class TestCapabilityTokens:
    def test_expired_token_is_denied(self) -> None:
        broker = _broker()
        token = _token(
            broker,
            Capability(ActionType.TOOL, resources=frozenset({"read"})),
            ttl=timedelta(seconds=-1),
        )

        decision = broker.decide(Action.tool("read"), tokens=[token], subject="agent-1")

        assert decision.effect is DecisionEffect.DENY
        assert decision.reason_code == "default_deny"

    def test_wrong_subject_cannot_reuse_token(self) -> None:
        broker = _broker()
        token = _token(
            broker,
            Capability(ActionType.TOOL, resources=frozenset({"read"})),
            subject="agent-1",
        )

        decision = broker.decide(Action.tool("read"), tokens=[token], subject="agent-2")

        assert decision.effect is DecisionEffect.DENY

    def test_omitting_subject_does_not_disable_subject_binding(self) -> None:
        broker = _broker()
        token = _token(
            broker,
            Capability(ActionType.TOOL, resources=frozenset({"read"})),
            subject="agent-1",
        )

        decision = broker.decide(Action.tool("read"), tokens=[token])

        assert decision.effect is DecisionEffect.DENY

    def test_token_payload_tampering_invalidates_signature(self) -> None:
        broker = _broker()
        token = _token(
            broker,
            Capability(ActionType.TOOL, resources=frozenset({"read"})),
        )
        payload, signature = token.split(".")
        replacement = "A" if payload[-1] != "A" else "B"
        tampered = f"{payload[:-1]}{replacement}.{signature}"

        decision = broker.decide(Action.tool("read"), tokens=[tampered], subject="agent-1")

        assert decision.effect is DecisionEffect.DENY

    def test_malformed_token_fails_closed(self) -> None:
        decision = _broker().decide(Action.tool("read"), tokens=["not-a-token"], subject="agent-1")

        assert decision.effect is DecisionEffect.DENY

    @pytest.mark.parametrize(
        "token",
        [
            "a" * 70_000,
            "abc=." + "a" * 43,
            "abc." + "a" * 42,
            "abc." + "!" * 43,
        ],
    )
    def test_oversized_or_noncanonical_tokens_fail_closed(self, token: str) -> None:
        decision = _broker().decide(Action.tool("read"), tokens=[token], subject="agent-1")

        assert decision.denied

    def test_explicit_verifier_capability_auto_allows_only_verifier_use(self) -> None:
        broker = _broker()
        plain = Capability(
            ActionType.COMMAND,
            command_rules=(CommandRule(("pytest", "-q"), exact=True),),
        )
        verifier = Capability(
            ActionType.COMMAND,
            command_rules=(CommandRule(("pytest", "-q"), exact=True),),
            verifier=True,
        )

        plain_token = _token(broker, plain)
        verifier_token = _token(broker, verifier)
        action = Action.command(("pytest", "-q"), verifier=True)

        assert broker.decide(
            Action.command(("pytest", "-q")),
            tokens=[verifier_token],
            subject="agent-1",
        ).denied
        assert broker.decide(action, tokens=[plain_token], subject="agent-1").denied
        decision = broker.decide(action, tokens=[verifier_token], subject="agent-1")
        assert decision.allowed
        assert decision.reason_code == "explicit_verifier_capability"


class TestCommandMatching:
    def test_command_rules_match_argv_not_shell_substrings(self) -> None:
        broker = _broker()
        token = _token(
            broker,
            Capability(
                ActionType.COMMAND,
                command_rules=(CommandRule(("git", "status"), exact=True),),
            ),
        )

        assert broker.decide(
            Action.command(("git", "status")), tokens=[token], subject="agent-1"
        ).allowed
        assert broker.decide(
            Action.command(("git", "status;", "rm", "-rf", "/")),
            tokens=[token],
            subject="agent-1",
        ).denied
        assert broker.decide(
            Action.command(("sh", "-c", "git status")),
            tokens=[token],
            subject="agent-1",
        ).denied

    def test_prefix_rule_allows_extra_arguments_but_not_executable_confusion(self) -> None:
        broker = _broker()
        token = _token(
            broker,
            Capability(
                ActionType.COMMAND,
                command_rules=(CommandRule(("git", "diff")),),
            ),
        )

        assert broker.decide(
            Action.command(("git", "diff", "--", "src/file.py")),
            tokens=[token],
            subject="agent-1",
        ).allowed
        assert broker.decide(
            Action.command(("/opt/local/bin/git", "diff")),
            tokens=[token],
            subject="agent-1",
        ).denied

    @pytest.mark.parametrize("argv", [(), ("git\x00status",), ("", "status")])
    def test_invalid_argv_is_rejected(self, argv: tuple[str, ...]) -> None:
        with pytest.raises(ValueError):
            Action.command(argv)

    @pytest.mark.parametrize(
        "action",
        [
            ActionType.TOOL,
            ActionType.SECRET,
            ActionType.BUDGET,
            ActionType.DEPLOYMENT,
        ],
    )
    def test_direct_construction_rejects_empty_scoped_resource(self, action: ActionType) -> None:
        with pytest.raises(ValueError):
            Action(action, "read")

    def test_action_rejects_fields_from_another_action_type(self) -> None:
        with pytest.raises(ValueError):
            Action(
                ActionType.TOOL,
                "invoke",
                resource="safe.read",
                argv=("rm", "-rf", "/"),
                path="/etc/shadow",
                host="169.254.169.254",
                port=80,
                amount=999,
            )
        with pytest.raises(ValueError):
            Action(ActionType.COMMAND, "execute", argv=("true",), resource="safe.read")

    def test_capability_rejects_irrelevant_scope_fields(self) -> None:
        with pytest.raises(ValueError):
            Capability(
                ActionType.TOOL,
                resources=frozenset({"safe"}),
                command_rules=(CommandRule(("rm",)),),
            )

    def test_verifier_flag_must_be_a_boolean(self) -> None:
        with pytest.raises(ValueError):
            Action(ActionType.TOOL, "invoke", resource="read", verifier=1)  # type: ignore[arg-type]


class TestFilesystemMatching:
    def test_empty_path_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            Action.filesystem("read", "")

    def test_path_scope_contains_normalized_descendants(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        broker = _broker()
        token = _token(
            broker,
            Capability(
                ActionType.FILESYSTEM,
                operations=frozenset({"read"}),
                path_rules=(PathRule(root),),
            ),
        )

        assert broker.decide(
            Action.filesystem("read", root / "src" / "new.py"),
            tokens=[token],
            subject="agent-1",
        ).allowed
        assert broker.decide(
            Action.filesystem("read", root / ".." / "outside.txt"),
            tokens=[token],
            subject="agent-1",
        ).denied

    def test_symlink_escape_is_denied(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        outside = tmp_path / "outside"
        root.mkdir()
        outside.mkdir()
        (root / "link").symlink_to(outside, target_is_directory=True)
        broker = _broker()
        token = _token(
            broker,
            Capability(
                ActionType.FILESYSTEM,
                path_rules=(PathRule(root),),
            ),
        )

        decision = broker.decide(
            Action.filesystem("read", root / "link" / "secret.txt"),
            tokens=[token],
            subject="agent-1",
        )

        assert decision.denied

    def test_redecision_detects_symlink_created_after_an_allow(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        outside = tmp_path / "outside"
        root.mkdir()
        outside.mkdir()
        broker = _broker()
        token = _token(
            broker,
            Capability(ActionType.FILESYSTEM, path_rules=(PathRule(root),)),
        )
        action = Action.filesystem("read", root / "slot" / "secret.txt")

        first = broker.decide(action, tokens=[token], subject="agent-1")
        assert first.allowed
        assert first.resolved_path == str(root / "slot" / "secret.txt")

        (root / "slot").symlink_to(outside, target_is_directory=True)
        second = broker.decide(action, tokens=[token], subject="agent-1")
        assert second.denied
        assert second.resolved_path == str(outside / "secret.txt")

    def test_path_scope_can_exclude_the_root_itself(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        broker = _broker()
        token = _token(
            broker,
            Capability(
                ActionType.FILESYSTEM,
                path_rules=(PathRule(root, allow_root=False),),
            ),
        )

        assert broker.decide(
            Action.filesystem("read", root), tokens=[token], subject="agent-1"
        ).denied


class TestNetworkMatching:
    def test_exact_host_is_canonicalized_but_suffix_confusion_is_denied(self) -> None:
        broker = _broker()
        token = _token(
            broker,
            Capability(
                ActionType.NETWORK,
                network_rules=(NetworkRule("API.Example.COM.", ports=frozenset({443})),),
            ),
        )

        assert broker.decide(
            Action.network("connect", "api.example.com", 443),
            tokens=[token],
            subject="agent-1",
        ).allowed
        assert broker.decide(
            Action.network("connect", "api.example.com.evil.test", 443),
            tokens=[token],
            subject="agent-1",
        ).denied
        assert broker.decide(
            Action.network("connect", "api.example.com", 80),
            tokens=[token],
            subject="agent-1",
        ).denied

    def test_wildcard_matches_subdomains_only(self) -> None:
        rule = NetworkRule("*.example.com")

        assert rule.matches("a.example.com", None)
        assert rule.matches("deep.a.example.com", None)
        assert not rule.matches("example.com", None)
        assert not rule.matches("example.com.evil", None)

    def test_cidr_matches_ip_literals_only(self) -> None:
        rule = NetworkRule("10.0.0.0/8")

        assert rule.matches("10.2.3.4", None)
        assert not rule.matches("11.2.3.4", None)
        assert not rule.matches("10.2.3.4.example.com", None)

    @pytest.mark.parametrize(
        "host", ["https://example.com", "user@example.com", "example.com/path", ""]
    )
    def test_ambiguous_or_url_hosts_are_rejected(self, host: str) -> None:
        with pytest.raises(ValueError):
            Action.network("connect", host, 443)


class TestRedactionAndAudit:
    def test_redaction_is_recursive_and_covers_secret_keys_and_values(self) -> None:
        secret = "super-secret-value"  # noqa: S105
        value = {
            "token": secret,
            "nested": [f"Bearer {secret}", {"message": f"prefix {secret} suffix"}],
            "safe": "visible",
        }

        redacted = redact_secrets(value, secret_values=(secret,))

        assert secret not in json.dumps(redacted)
        assert redacted["token"] == "[REDACTED]"  # noqa: S105
        assert redacted["safe"] == "visible"

    @pytest.mark.parametrize(
        "key",
        [
            "accessToken",
            "refresh-token",
            "clientSecret",
            "private_key",
            "auth",
            "cookie",
            "sessionId",
        ],
    )
    def test_common_secret_key_variants_are_redacted(self, key: str) -> None:
        assert redact_secrets({key: "short-secret"})[key] == "[REDACTED]"

    @pytest.mark.parametrize(
        "context",
        [
            {2: "non-string-key"},
            {"blob": b"bytes"},
            {"number": float("nan")},
        ],
    )
    def test_noncanonical_audit_context_is_rejected(self, context: object) -> None:
        with pytest.raises(ValueError):
            Action.tool("inspect", context=context)  # type: ignore[arg-type]

    def test_cyclic_or_too_deep_context_is_rejected(self) -> None:
        cyclic: dict[str, object] = {}
        cyclic["self"] = cyclic
        with pytest.raises(ValueError):
            Action.tool("inspect", context=cyclic)

        deep: object = "leaf"
        for _ in range(20):
            deep = [deep]
        with pytest.raises(ValueError):
            Action.tool("inspect", context={"deep": deep})

    def test_nested_context_is_immutable_after_action_construction(self) -> None:
        nested = {"value": "original"}
        source = {"nested": nested}
        action = Action.tool("inspect", context=source)
        nested["value"] = "changed"

        frozen_nested = action.context["nested"]
        assert isinstance(frozen_nested, Mapping)
        assert frozen_nested["value"] == "original"

    def test_audit_is_append_only_hash_chained_and_verifiable(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        audit = AuditLog(path, clock=lambda: NOW)
        broker = _broker(audit_log=audit)

        broker.decide(Action.tool("first"))
        first_bytes = path.read_bytes()
        broker.decide(Action.tool("second"))
        final_bytes = path.read_bytes()

        assert final_bytes.startswith(first_bytes)
        assert AuditLog.verify(path)
        events = [json.loads(line) for line in final_bytes.splitlines()]
        assert events[0]["previous_hash"] == "0" * 64
        assert events[1]["previous_hash"] == events[0]["event_hash"]
        assert AuditLog.verify(
            path,
            expected_sequence=1,
            expected_head=str(events[1]["event_hash"]),
        )

    def test_audit_tampering_is_detected(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        audit = AuditLog(path, clock=lambda: NOW)
        audit.append("decision", {"effect": "deny", "resource": "original"})
        path.write_text(path.read_text().replace("original", "tampered"))

        assert not AuditLog.verify(path)

    def test_audit_checkpoint_detects_tail_deletion(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        audit = AuditLog(path, clock=lambda: NOW)
        first = audit.append("decision", {"effect": "deny"})
        second = audit.append("decision", {"effect": "allow"})
        first_line = path.read_text().splitlines()[0]
        path.write_text(first_line + "\n")

        assert AuditLog.verify(path)
        assert not AuditLog.verify(
            path,
            expected_sequence=1,
            expected_head=str(second["event_hash"]),
        )
        assert AuditLog.verify(
            path,
            expected_sequence=0,
            expected_head=str(first["event_hash"]),
        )

    def test_decision_audit_never_contains_configured_secret(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        secret = "never-write-this-value"  # noqa: S105
        broker = _broker(
            audit_log=AuditLog(path, clock=lambda: NOW),
            secret_values=(secret,),
        )
        action = Action.tool("inspect", context={"authorization": f"Bearer {secret}"})

        broker.decide(action)

        audit_text = path.read_text()
        assert secret not in audit_text
        assert "[REDACTED]" in audit_text

    def test_decision_audit_redacts_secret_key_alias_without_configuration(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "audit.jsonl"
        broker = _broker(audit_log=AuditLog(path, clock=lambda: NOW))

        broker.decide(Action.tool("inspect", context={"clientSecret": "short-value"}))

        audit_text = path.read_text()
        assert "short-value" not in audit_text
        assert "[REDACTED]" in audit_text

    def test_audit_rejects_a_symlink_log_target(self, tmp_path: Path) -> None:
        real = tmp_path / "real.jsonl"
        real.write_text("")
        link = tmp_path / "audit.jsonl"
        link.symlink_to(real)

        with pytest.raises(ValueError):
            AuditLog(link).append("decision", {"effect": "deny"})
        assert not AuditLog.verify(link)
