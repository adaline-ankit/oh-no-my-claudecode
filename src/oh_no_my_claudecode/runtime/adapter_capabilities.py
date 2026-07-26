"""Machine-readable capability profiles for supported coding-agent adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from oh_no_my_claudecode.loop.adapter_contract import contract_for

AgentName = Literal["claude", "codex", "opencode"]

_SUPPORTED_AGENTS: tuple[AgentName, ...] = ("claude", "codex", "opencode")


@dataclass(frozen=True, slots=True)
class AdapterCapability:
    """Honest telemetry and control-surface contract for one agent adapter."""

    agent: AgentName
    cli_binary: str
    invocation_mode: str
    auth_scope: str
    model_override: bool
    tokens: str
    cost: str
    files_touched: str
    structured_output: str
    isolation: str
    limitations: tuple[str, ...]
    schema_version: str = "1"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "agent": self.agent,
            "cli_binary": self.cli_binary,
            "invocation_mode": self.invocation_mode,
            "auth_scope": self.auth_scope,
            "model_override": self.model_override,
            "tokens": self.tokens,
            "cost": self.cost,
            "files_touched": self.files_touched,
            "structured_output": self.structured_output,
            "isolation": self.isolation,
            "limitations": list(self.limitations),
            "conformance": contract_for(self.agent).to_dict()["capabilities"],
        }


_CAPABILITIES: dict[AgentName, AdapterCapability] = {
    "claude": AdapterCapability(
        agent="claude",
        cli_binary="claude",
        invocation_mode="claude -p --output-format json",
        auth_scope="ambient Claude CLI session or configured Claude credentials",
        model_override=True,
        tokens="reported_structured_when_cli_emits_usage",
        cost="reported_structured_when_cli_emits_total_cost_usd",
        files_touched="git_status_diff",
        structured_output="json_result_envelope_best_effort",
        isolation="Claude CLI permission mode acceptEdits; not a process sandbox",
        limitations=(
            "Cost and token telemetry are unavailable when the Claude CLI omits usage.",
            "File edits are auto-accepted; shell, network, and external tools remain "
            "governed by the Claude CLI.",
            "This adapter does not create a container or microVM boundary by itself.",
        ),
    ),
    "codex": AdapterCapability(
        agent="codex",
        cli_binary="codex",
        invocation_mode="codex exec --sandbox workspace-write",
        auth_scope="ambient Codex CLI login or environment configured for Codex",
        model_override=True,
        tokens="best_effort_human_stdout_parse",
        cost="not_reported",
        files_touched="git_status_diff",
        structured_output="plain_stdout_with_best_effort_usage_parse",
        isolation="Codex CLI workspace-write sandbox; not an ONMC-owned container",
        limitations=(
            "Cost is never reported by headless Codex exec and must stay unknown.",
            "Token telemetry depends on a human-readable tokens-used line and may be absent.",
            "Authentication failures are inferred from provider error text, not a "
            "structured auth API.",
        ),
    ),
    "opencode": AdapterCapability(
        agent="opencode",
        cli_binary="opencode",
        invocation_mode="opencode run --format json --dir <repo>",
        auth_scope="ambient OpenCode configuration and provider credentials",
        model_override=True,
        tokens="reported_when_json_event_stream_emits_usage",
        cost="not_reported",
        files_touched="git_status_diff",
        structured_output="json_event_stream_best_effort",
        isolation="OpenCode CLI project directory scoping; not an ONMC-owned container",
        limitations=(
            "Cost is not emitted by the OpenCode headless adapter and must stay unknown.",
            "Token telemetry is available only when provider usage appears in the JSON "
            "event stream.",
            "Provider selection and credentials remain owned by the local OpenCode configuration.",
        ),
    ),
}


def adapter_capability(agent: str) -> AdapterCapability:
    """Return the explicit capability profile for *agent*."""
    if agent not in _CAPABILITIES:
        raise ValueError("agent must be claude, codex, or opencode")
    return _CAPABILITIES[agent]


def adapter_capability_payload(agent: str) -> dict[str, object]:
    """Return the JSON-safe payload embedded in runtime contracts."""
    return adapter_capability(agent).to_dict()


def all_adapter_capabilities() -> tuple[AdapterCapability, ...]:
    """Return all supported adapter profiles in stable agent order."""
    return tuple(_CAPABILITIES[name] for name in _SUPPORTED_AGENTS)


__all__ = [
    "AdapterCapability",
    "AgentName",
    "adapter_capability",
    "adapter_capability_payload",
    "all_adapter_capabilities",
]
