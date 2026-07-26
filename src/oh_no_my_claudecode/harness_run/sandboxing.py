"""Harness-level sandbox manifest bound into ``onmc run`` plans."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from oh_no_my_claudecode.sandbox import (
    NetworkPolicy,
    SandboxPlanError,
    SandboxRoleCapabilityManifest,
    ScopedSecret,
    default_repo_sandbox,
    docker_run_plan,
    harbor_task_payload,
    sandbox_role_capability_manifest,
)

SandboxProviderName = Literal["docker", "harbor"]

_AGENT_SECRET_ENV: dict[str, tuple[str, ...]] = {
    "claude": ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"),
    "codex": ("OPENAI_API_KEY",),
    "opencode": ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"),
}


@dataclass(frozen=True, slots=True)
class HarnessSandboxManifest:
    """Serializable sandbox plan for agent/verifier execution.

    ``enforced`` remains false until the harness runner executes through this
    provider. This makes the contract useful without pretending current runs are
    already container-isolated.
    """

    requested: bool
    enforced: bool
    validated: bool
    provider: str
    agent_plan: dict[str, Any] | None = None
    verifier_plan: dict[str, Any] | None = None
    agent_capabilities: SandboxRoleCapabilityManifest | None = None
    verifier_capabilities: SandboxRoleCapabilityManifest | None = None
    limitations: tuple[str, ...] = ()
    schema_version: str = "1"

    @property
    def capability_manifest(self) -> dict[str, Any]:
        """Role-scoped network, secret, and filesystem declarations."""
        return {
            "agent": None
            if self.agent_capabilities is None
            else self.agent_capabilities.to_dict(),
            "verifier": None
            if self.verifier_capabilities is None
            else self.verifier_capabilities.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "requested": self.requested,
            "enforced": self.enforced,
            "validated": self.validated,
            "provider": self.provider,
            "agent_plan": self.agent_plan,
            "verifier_plan": self.verifier_plan,
            "capability_manifest": self.capability_manifest,
            "limitations": list(self.limitations),
        }

    def validate_for_execution(self) -> None:
        """Fail closed before a requested autonomous provider is invoked."""
        if not self.requested:
            raise SandboxPlanError("sandbox was not requested")
        if not self.validated:
            raise SandboxPlanError("sandbox capability manifest is not validated")
        if self.agent_plan is None or self.agent_capabilities is None:
            raise SandboxPlanError("sandbox agent capability manifest is missing")
        if self.verifier_plan is None or self.verifier_capabilities is None:
            raise SandboxPlanError("sandbox verifier capability manifest is missing")
        if self.provider == "harbor":
            raise SandboxPlanError(
                "Harbor sandbox is configuration-only for local autonomous execution"
            )
        if self.provider != "docker":
            raise SandboxPlanError(f"sandbox provider {self.provider!r} is not executable")


def harness_sandbox_manifest(
    *,
    requested: bool,
    provider: SandboxProviderName,
    image: str,
    repo_root: Path,
    agent: str,
    verifier_argv: tuple[str, ...],
) -> HarnessSandboxManifest:
    """Build the sandbox manifest attached to a harness run plan."""

    if not requested:
        return HarnessSandboxManifest(
            requested=False,
            enforced=False,
            validated=False,
            provider="none",
            limitations=("No sandbox provider requested for this run.",),
        )

    secrets = tuple(
        ScopedSecret(env_name, roles=("agent",))
        for env_name in _AGENT_SECRET_ENV.get(agent, ())
    )
    agent_spec = default_repo_sandbox(
        repo_root,
        image=image,
        writeable=True,
        network=NetworkPolicy.ALLOW,
        secrets=secrets,
    )
    verifier_spec = default_repo_sandbox(
        repo_root,
        image=image,
        writeable=False,
        network=NetworkPolicy.DENY,
    )
    agent_capabilities = sandbox_role_capability_manifest(agent_spec, role="agent")
    verifier_capabilities = sandbox_role_capability_manifest(verifier_spec, role="verifier")
    agent_command = ("onmc-agent-adapter", agent)
    if provider == "docker":
        agent_plan = docker_run_plan(agent_spec, agent_command, role="agent").to_dict()
        verifier_plan = docker_run_plan(
            verifier_spec,
            verifier_argv,
            role="verifier",
        ).to_dict()
    elif provider == "harbor":
        agent_plan = harbor_task_payload(agent_spec, agent_command, role="agent")
        verifier_plan = harbor_task_payload(
            verifier_spec,
            verifier_argv,
            role="verifier",
        )
    else:
        raise ValueError("sandbox_provider must be docker or harbor")

    return HarnessSandboxManifest(
        requested=True,
        enforced=False,
        validated=True,
        provider=provider,
        agent_plan=agent_plan,
        verifier_plan=verifier_plan,
        agent_capabilities=agent_capabilities,
        verifier_capabilities=verifier_capabilities,
        limitations=(
            "Capability declarations were validated before execution.",
            "The plan remains enforced=false until a provider execution is observed.",
            "Verifier sandbox receives no model-provider secret by default.",
        ),
    )


__all__ = ["HarnessSandboxManifest", "SandboxProviderName", "harness_sandbox_manifest"]
