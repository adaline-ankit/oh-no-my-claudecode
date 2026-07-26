"""Harness-level sandbox manifest bound into ``onmc run`` plans."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from oh_no_my_claudecode.sandbox import (
    ScopedSecret,
    default_repo_sandbox,
    docker_run_plan,
    harbor_task_payload,
)

SandboxProviderName = Literal["docker", "harbor"]

_AGENT_SECRET_ENV: dict[str, tuple[str, ...]] = {
    "claude": ("ANTHROPIC_API_KEY",),
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
    provider: str
    agent_plan: dict[str, Any] | None = None
    verifier_plan: dict[str, Any] | None = None
    limitations: tuple[str, ...] = ()
    schema_version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "requested": self.requested,
            "enforced": self.enforced,
            "provider": self.provider,
            "agent_plan": self.agent_plan,
            "verifier_plan": self.verifier_plan,
            "limitations": list(self.limitations),
        }


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
            provider="none",
            limitations=("No sandbox provider requested for this run.",),
        )

    secrets = tuple(
        ScopedSecret(env_name, roles=("agent",))
        for env_name in _AGENT_SECRET_ENV.get(agent, ())
    )
    spec = default_repo_sandbox(repo_root, image=image, writeable=True, secrets=secrets)
    agent_command = ("onmc-agent-adapter", agent)
    if provider == "docker":
        agent_plan = docker_run_plan(spec, agent_command, role="agent").to_dict()
        verifier_plan = docker_run_plan(spec, verifier_argv, role="verifier").to_dict()
    elif provider == "harbor":
        agent_plan = harbor_task_payload(spec, agent_command, role="agent")
        verifier_plan = harbor_task_payload(spec, verifier_argv, role="verifier")
    else:
        raise ValueError("sandbox_provider must be docker or harbor")

    return HarnessSandboxManifest(
        requested=True,
        enforced=False,
        provider=provider,
        agent_plan=agent_plan,
        verifier_plan=verifier_plan,
        limitations=(
            "Sandbox provider payload is planned but not yet used by the harness runner.",
            "Current execution still uses the existing agent/verifier path unless a future "
            "runner executes this provider plan.",
            "Verifier sandbox receives no model-provider secret by default.",
        ),
    )


__all__ = ["HarnessSandboxManifest", "SandboxProviderName", "harness_sandbox_manifest"]
