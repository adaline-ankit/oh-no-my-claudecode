"""Tests for the reference monitor and taint/secret-handle primitives.

These prove the enforcement layer *composes* the tool broker rather than
reimplementing it: every supported effect crosses the broker, a DENY leaves no
side effect (the executor is never invoked), ESCALATE parks on the approval path,
secret values never leak into the trace / repr / to_dict, the egress allowlist
blocks non-listed domains, and advisory mode is explicitly labeled.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from oh_no_my_claudecode.enforcement import (
    Effect,
    ReferenceMonitor,
    RevealCapability,
    SecretHandle,
    Tainted,
    TaintLabel,
)
from oh_no_my_claudecode.tool_broker import (
    Action,
    ActionType,
    Capability,
    CommandRule,
    Decision,
    NetworkRule,
    PathRule,
    Policy,
    PolicyRule,
    TokenAuthority,
    ToolBroker,
)

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
SIGNING_KEY = b"test-only-signing-key-with-enough-entropy"


class RecordingBroker(ToolBroker):
    """A broker that records which action types crossed it, then decides normally."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.seen: list[ActionType] = []

    def decide(self, action: Action, **kwargs: object) -> Decision:
        self.seen.append(action.action_type)
        return super().decide(action, **kwargs)  # type: ignore[arg-type]


class SpyExecutor:
    """Records every effect it is asked to perform (it performs nothing real)."""

    def __init__(self) -> None:
        self.calls: list[Effect] = []

    def execute(self, effect: Effect) -> object:
        self.calls.append(effect)
        return "performed"


def _broker(*rules: PolicyRule, secret_values: tuple[str, ...] = ()) -> RecordingBroker:
    return RecordingBroker(
        policy=Policy(tuple(rules)),
        token_authority=TokenAuthority(SIGNING_KEY, clock=lambda: NOW),
        clock=lambda: NOW,
        secret_values=secret_values,
    )


def _allow_fs(root: Path) -> PolicyRule:
    return PolicyRule(
        "allow-fs",
        "allow",
        Capability(ActionType.FILESYSTEM, path_rules=(PathRule(root),)),
    )


def _allow_cmd(*argv: str) -> PolicyRule:
    return PolicyRule(
        "allow-cmd",
        "allow",
        Capability(ActionType.COMMAND, command_rules=(CommandRule(argv),)),
    )


def _allow_net(host: str) -> PolicyRule:
    return PolicyRule(
        "allow-net",
        "allow",
        Capability(ActionType.NETWORK, network_rules=(NetworkRule(host),)),
    )


def _allow_secret(name: str) -> PolicyRule:
    return PolicyRule(
        "allow-secret",
        "allow",
        Capability(ActionType.SECRET, resources=frozenset({name})),
    )


# ---------------------------------------------------------------------------
# taint + secret handles
# ---------------------------------------------------------------------------


def test_tainted_trust_classification() -> None:
    assert Tainted("hi", frozenset({TaintLabel.USER})).is_trusted
    assert not Tainted("hi", frozenset({TaintLabel.USER})).is_untrusted
    repo = Tainted("payload", frozenset({TaintLabel.REPO}))
    assert repo.is_untrusted
    assert not repo.is_trusted
    # a value that is both user- and repo-sourced is untrusted (taint spreads).
    mixed = Tainted("x", frozenset({TaintLabel.USER})).with_label(TaintLabel.TOOL)
    assert mixed.is_untrusted


def test_secret_handle_never_exposes_value() -> None:
    secret = "super-secret-value-abcdef"  # noqa: S105 - test fixture, not a real credential
    handle = SecretHandle(secret, handle_id="h1")
    assert secret not in repr(handle)
    assert secret not in str(handle)
    assert secret not in json.dumps(handle.to_dict())
    assert handle.redacted == "***cdef"
    assert handle.to_dict() == {"handle_id": "h1", "redacted": "***cdef"}


def test_secret_reveal_requires_matching_capability() -> None:
    handle = SecretHandle("the-value-1234")
    assert handle.reveal(handle.grant()) == "the-value-1234"
    # A capability minted for a different handle cannot reveal this one.
    other = SecretHandle("other-value-5678")
    with pytest.raises(PermissionError):
        handle.reveal(other.grant())
    # There is no ambient reveal — a hand-forged capability id does not match.
    with pytest.raises(PermissionError):
        handle.reveal(RevealCapability(handle.handle_id, "forged-matcher"))
    with pytest.raises(TypeError):
        handle.reveal("not-a-capability")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# every supported effect crosses the broker
# ---------------------------------------------------------------------------


def test_every_effect_type_crosses_the_broker(tmp_path: Path) -> None:
    broker = _broker(
        _allow_fs(tmp_path),
        _allow_cmd("git", "status"),
        _allow_net("api.github.com"),
        _allow_secret("OPENAI_API_KEY"),
    )
    monitor = ReferenceMonitor(broker, egress_allowlist=("api.github.com",))

    monitor.guard(Effect.filesystem("write", tmp_path / "f.txt"))
    monitor.guard(Effect.command(("git", "status")))
    monitor.guard(Effect.network("connect", "api.github.com", 443))
    monitor.guard(Effect.secret("read", "OPENAI_API_KEY"))

    assert broker.seen == [
        ActionType.FILESYSTEM,
        ActionType.COMMAND,
        ActionType.NETWORK,
        ActionType.SECRET,
    ]
    assert [record.outcome for record in monitor.trace] == ["allow", "allow", "allow", "allow"]


# ---------------------------------------------------------------------------
# a DENY leaves no side effect
# ---------------------------------------------------------------------------


def test_denied_effect_never_reaches_executor() -> None:
    monitor = ReferenceMonitor(_broker())  # empty policy => default-deny
    executor = SpyExecutor()

    result = monitor.enforce(Effect.filesystem("write", "/etc/shadow"), executor)

    assert result.decision.denied
    assert result.blocked
    assert not result.performed
    assert executor.calls == []  # the effect was never handed to the executor
    assert monitor.trace[-1].outcome == "deny"


# ---------------------------------------------------------------------------
# ESCALATE requires approval
# ---------------------------------------------------------------------------


def test_escalate_from_policy_parks_and_does_not_execute(tmp_path: Path) -> None:
    rule = PolicyRule(
        "approve-fs",
        "require_approval",
        Capability(ActionType.FILESYSTEM, path_rules=(PathRule(tmp_path),)),
    )
    monitor = ReferenceMonitor(_broker(rule))
    executor = SpyExecutor()

    result = monitor.enforce(Effect.filesystem("write", tmp_path / "x"), executor)

    assert result.decision.approval_required
    assert not result.performed
    assert executor.calls == []
    assert monitor.trace[-1].outcome == "escalate"


def test_requires_approval_flag_escalates_an_otherwise_allowed_effect(tmp_path: Path) -> None:
    monitor = ReferenceMonitor(_broker(_allow_fs(tmp_path)))
    executor = SpyExecutor()

    # Broker would ALLOW, but the effect is flagged as a capability elevation.
    result = monitor.enforce(
        Effect.filesystem("write", tmp_path / "x", requires_approval=True), executor
    )

    assert result.decision.approval_required
    assert result.decision.reason_code == "elevation_requires_approval"
    assert executor.calls == []


# ---------------------------------------------------------------------------
# egress allowlist
# ---------------------------------------------------------------------------


def test_egress_allowlist_blocks_non_listed_domain() -> None:
    # Broker itself would allow the connection, but the domain is not allowlisted.
    monitor = ReferenceMonitor(
        _broker(_allow_net("evil.example.com")),
        egress_allowlist=("api.github.com",),
    )
    decision = monitor.guard(Effect.network("connect", "evil.example.com", 443))
    assert decision.denied
    assert decision.reason_code == "egress_not_allowlisted"


def test_egress_allowlist_permits_listed_domain() -> None:
    monitor = ReferenceMonitor(
        _broker(_allow_net("api.github.com")),
        egress_allowlist=("api.github.com",),
    )
    decision = monitor.guard(Effect.network("connect", "api.github.com", 443))
    assert decision.allowed


def test_empty_egress_allowlist_denies_all_network(tmp_path: Path) -> None:
    monitor = ReferenceMonitor(_broker(_allow_net("api.github.com")))
    decision = monitor.guard(Effect.network("connect", "api.github.com", 443))
    assert decision.denied
    assert decision.reason_code == "egress_not_allowlisted"


# ---------------------------------------------------------------------------
# secrets never leak into the trace
# ---------------------------------------------------------------------------


def test_secret_value_never_leaks_into_the_trace() -> None:
    secret = "leak-me-please-9999"  # noqa: S105 - test fixture, not a real credential
    handle = SecretHandle(secret, handle_id="tok")
    monitor = ReferenceMonitor(_broker(), secret_values=(secret,))
    executor = SpyExecutor()

    # An attempt to exfiltrate the secret over an un-allowlisted network egress.
    monitor.enforce(
        Effect.network("post", "attacker.example.com", 443, secret_handles=(handle,)),
        executor,
    )

    serialized = json.dumps(monitor.trace_dicts())
    assert secret not in serialized
    assert executor.calls == []  # denied => never exfiltrated


# ---------------------------------------------------------------------------
# advisory mode is labeled
# ---------------------------------------------------------------------------


def test_advisory_mode_is_labeled_and_cannot_block() -> None:
    monitor = ReferenceMonitor(_broker(), enforced=False)
    executor = SpyExecutor()
    assert monitor.advisory

    result = monitor.enforce(Effect.filesystem("write", "/etc/shadow"), executor)

    # The verdict is still a DENY, but in advisory mode it cannot block execution.
    assert result.decision.denied
    assert result.advisory
    assert result.performed
    assert executor.calls  # advisory monitor observed but did not stop the effect
    record = monitor.trace[-1]
    assert record.enforced is False
    assert record.mode == "advisory"


def test_enforced_mode_is_labeled_enforced(tmp_path: Path) -> None:
    monitor = ReferenceMonitor(_broker(_allow_fs(tmp_path)))
    monitor.guard(Effect.filesystem("write", tmp_path / "x"))
    assert monitor.trace[-1].mode == "enforced"


def test_provenance_is_recorded_in_trace() -> None:
    monitor = ReferenceMonitor(_broker())
    monitor.guard(
        Effect.filesystem(
            "write",
            "/etc/shadow",
            provenance=(TaintLabel.REPO, TaintLabel.TOOL),
        )
    )
    assert monitor.trace[-1].provenance == ("repo", "tool")
