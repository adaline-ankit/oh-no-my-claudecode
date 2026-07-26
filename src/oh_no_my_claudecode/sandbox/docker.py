"""Docker planner for ONMC sandbox contracts.

The planner returns the command ONMC would execute. It does not run Docker.
This keeps preflight deterministic and lets tests prove fail-closed behavior
without requiring Docker on the developer machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import NetworkPolicy, SandboxPlanError, SandboxRole, SandboxSpec


@dataclass(frozen=True, slots=True)
class DockerSandboxPlan:
    """A Docker command plus redacted execution metadata."""

    argv: tuple[str, ...]
    role: SandboxRole
    secret_env: tuple[str, ...]
    network: NetworkPolicy
    timeout_seconds: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": "docker",
            "argv": list(self.argv),
            "role": self.role,
            "secret_env": list(self.secret_env),
            "network": self.network.value,
            "timeout_seconds": self.timeout_seconds,
        }


def docker_run_plan(
    spec: SandboxSpec,
    command: tuple[str, ...],
    *,
    role: SandboxRole = "agent",
) -> DockerSandboxPlan:
    """Compile a sandbox spec into a fail-closed ``docker run`` command."""

    if not command:
        raise SandboxPlanError("docker command must not be empty")
    if spec.network is NetworkPolicy.ALLOWLIST:
        raise SandboxPlanError("docker provider cannot enforce egress allowlist")

    argv: list[str] = ["docker", "run", "--rm", "--workdir", spec.workdir]
    argv.extend(["--label", "onmc.sandbox=true"])
    argv.extend(["--label", f"onmc.sandbox.role={role}"])

    if spec.network is NetworkPolicy.DENY:
        argv.extend(["--network", "none"])
    elif spec.network is NetworkPolicy.ALLOW:
        argv.extend(["--network", "bridge"])

    if spec.cpus is not None:
        argv.extend(["--cpus", str(spec.cpus)])
    if spec.memory_mb is not None:
        argv.extend(["--memory", f"{spec.memory_mb}m"])

    for mount in spec.mounts:
        mode = "ro" if mount.read_only else "rw"
        argv.extend(["--volume", f"{mount.host_path}:{mount.container_path}:{mode}"])

    secret_env = spec.secret_env_for(role)
    for env_name in secret_env:
        argv.extend(["--env", env_name])

    argv.append(spec.image)
    argv.extend(command)
    return DockerSandboxPlan(
        argv=tuple(argv),
        role=role,
        secret_env=secret_env,
        network=spec.network,
        timeout_seconds=spec.timeout_seconds,
    )


__all__ = ["DockerSandboxPlan", "docker_run_plan"]
