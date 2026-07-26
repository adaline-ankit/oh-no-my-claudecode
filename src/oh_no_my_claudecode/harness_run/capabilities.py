"""Pre-execution capability manifest for harness runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oh_no_my_claudecode.runtime.adapter_capabilities import adapter_capability_payload

from .isolation import IsolationProfile

_SCHEMA_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ExecutionCapabilityManifest:
    """One honest declaration of the run boundary before any agent is invoked."""

    agent: str
    model: str
    verifier_argv: tuple[str, ...]
    filesystem: str
    filesystem_write: bool
    process: str
    process_isolated: bool
    network: str
    egress_constrained: bool
    secrets: str
    secrets_scoped: bool
    timeout_seconds_per_node: float
    max_iterations: int
    token_budget: int
    max_cost_usd: float | None
    token_telemetry: str
    cost_telemetry: str
    sandbox_requested: bool
    sandbox_provider: str
    sandbox_enforced: bool
    adapter_limitations: tuple[str, ...]
    isolation_limitations: tuple[str, ...]
    sandbox_limitations: tuple[str, ...]
    schema_version: str = _SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "agent": self.agent,
            "model": self.model,
            "verifier_argv": list(self.verifier_argv),
            "filesystem": self.filesystem,
            "filesystem_write": self.filesystem_write,
            "process": self.process,
            "process_isolated": self.process_isolated,
            "network": self.network,
            "egress_constrained": self.egress_constrained,
            "secrets": self.secrets,
            "secrets_scoped": self.secrets_scoped,
            "timeout_seconds_per_node": self.timeout_seconds_per_node,
            "max_iterations": self.max_iterations,
            "token_budget": self.token_budget,
            "max_cost_usd": self.max_cost_usd,
            "token_telemetry": self.token_telemetry,
            "cost_telemetry": self.cost_telemetry,
            "sandbox_requested": self.sandbox_requested,
            "sandbox_provider": self.sandbox_provider,
            "sandbox_enforced": self.sandbox_enforced,
            "adapter_limitations": list(self.adapter_limitations),
            "isolation_limitations": list(self.isolation_limitations),
            "sandbox_limitations": list(self.sandbox_limitations),
        }


def execution_capability_manifest(
    *,
    agent: str,
    model: str,
    verifier_argv: tuple[str, ...],
    max_iterations: int,
    token_budget: int,
    max_cost_usd: float | None,
    isolation: IsolationProfile,
    sandbox_requested: bool = False,
    sandbox_provider: str = "none",
    sandbox_enforced: bool = False,
    sandbox_limitations: tuple[str, ...] = (),
    filesystem_write: bool = True,
    timeout_seconds_per_node: float = 120.0,
) -> ExecutionCapabilityManifest:
    """Build the capability boundary bound into a plan before execution."""

    adapter = adapter_capability_payload(agent)
    raw_limitations = adapter["limitations"]
    adapter_limitations = (
        tuple(str(item) for item in raw_limitations)
        if isinstance(raw_limitations, list | tuple)
        else (str(raw_limitations),)
    )
    return ExecutionCapabilityManifest(
        agent=agent,
        model=model,
        verifier_argv=verifier_argv,
        filesystem=isolation.filesystem,
        filesystem_write=filesystem_write,
        process=isolation.process,
        process_isolated=False,
        network=isolation.network,
        egress_constrained=False,
        secrets=isolation.secrets,
        secrets_scoped=False,
        timeout_seconds_per_node=timeout_seconds_per_node,
        max_iterations=max_iterations,
        token_budget=token_budget,
        max_cost_usd=max_cost_usd,
        token_telemetry=str(adapter["tokens"]),
        cost_telemetry=str(adapter["cost"]),
        sandbox_requested=sandbox_requested,
        sandbox_provider=sandbox_provider,
        sandbox_enforced=sandbox_enforced,
        adapter_limitations=adapter_limitations,
        isolation_limitations=isolation.limitations,
        sandbox_limitations=sandbox_limitations,
    )


__all__ = ["ExecutionCapabilityManifest", "execution_capability_manifest"]
