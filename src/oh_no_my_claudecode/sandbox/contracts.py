"""Provider-neutral sandbox contracts for autonomous ONMC execution.

This module is deliberately about enforceable boundaries, not marketing.
Worktrees isolate repository changes; a sandbox isolates process, filesystem,
network, and secrets. Providers such as Docker or Harbor compile this contract
into their own execution shape.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

SandboxRole = Literal["agent", "verifier", "setup"]


class SandboxPlanError(ValueError):
    """Raised when a sandbox plan cannot enforce the requested boundary."""


class NetworkPolicy(StrEnum):
    """Network boundary requested for the sandbox."""

    DENY = "deny"
    ALLOW = "allow"
    ALLOWLIST = "allowlist"


@dataclass(frozen=True, slots=True)
class SandboxMount:
    """One host path exposed inside a sandbox."""

    host_path: Path
    container_path: str
    read_only: bool = True

    def __post_init__(self) -> None:
        if not self.container_path.startswith("/"):
            raise SandboxPlanError("mount.container_path must be absolute")
        if self.container_path == "/":
            raise SandboxPlanError("mount.container_path must not be container root")
        if not str(self.host_path):
            raise SandboxPlanError("mount.host_path must not be empty")

    def host_contains(self, path: Path) -> bool:
        """True when *path* is inside this mount's host boundary."""
        root = self.host_path.resolve()
        target = path.resolve()
        return target == root or root in target.parents

    def to_dict(self) -> dict[str, object]:
        return {
            "host_path": str(self.host_path),
            "container_path": self.container_path,
            "read_only": self.read_only,
        }


@dataclass(frozen=True, slots=True)
class ScopedSecret:
    """A secret exposed by environment name only, never by value."""

    env_name: str
    roles: tuple[SandboxRole, ...] = ("agent",)

    def __post_init__(self) -> None:
        if not self.env_name or "=" in self.env_name:
            raise SandboxPlanError("secret.env_name must be a non-empty environment name")
        if not self.roles:
            raise SandboxPlanError("secret.roles must not be empty")

    def exposed_to(self, role: SandboxRole) -> bool:
        return role in self.roles

    def to_dict(self) -> dict[str, object]:
        return {
            "env_name": self.env_name,
            "roles": list(self.roles),
        }


@dataclass(frozen=True, slots=True)
class SandboxSpec:
    """Pre-execution sandbox boundary for one autonomous run node."""

    image: str
    mounts: tuple[SandboxMount, ...]
    workdir: str = "/workspace"
    network: NetworkPolicy = NetworkPolicy.DENY
    egress_allowlist: tuple[str, ...] = ()
    secrets: tuple[ScopedSecret, ...] = ()
    timeout_seconds: int = 600
    cpus: float | None = None
    memory_mb: int | None = None
    image_digest: str | None = None
    provider: str = "docker"
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if not self.image:
            raise SandboxPlanError("sandbox.image must not be empty")
        if not self.workdir.startswith("/"):
            raise SandboxPlanError("sandbox.workdir must be absolute")
        if not self.mounts:
            raise SandboxPlanError("sandbox.mounts must include at least one mount")
        if self.network is NetworkPolicy.DENY and self.egress_allowlist:
            raise SandboxPlanError("egress_allowlist requires network=allowlist")
        if self.network is NetworkPolicy.ALLOWLIST and not self.egress_allowlist:
            raise SandboxPlanError("network=allowlist requires at least one host")
        if self.timeout_seconds <= 0:
            raise SandboxPlanError("sandbox.timeout_seconds must be positive")
        if self.cpus is not None and self.cpus <= 0:
            raise SandboxPlanError("sandbox.cpus must be positive")
        if self.memory_mb is not None and self.memory_mb <= 0:
            raise SandboxPlanError("sandbox.memory_mb must be positive")

    def allows_host_path(self, path: Path) -> bool:
        """True when *path* is within a declared host mount."""
        return any(mount.host_contains(path) for mount in self.mounts)

    def secret_env_for(self, role: SandboxRole) -> tuple[str, ...]:
        """Secret env names exposed to *role*. Values remain outside the plan."""
        return tuple(secret.env_name for secret in self.secrets if secret.exposed_to(role))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "image": self.image,
            "image_digest": self.image_digest,
            "workdir": self.workdir,
            "network": self.network.value,
            "egress_allowlist": list(self.egress_allowlist),
            "timeout_seconds": self.timeout_seconds,
            "cpus": self.cpus,
            "memory_mb": self.memory_mb,
            "mounts": [mount.to_dict() for mount in self.mounts],
            "secrets": [secret.to_dict() for secret in self.secrets],
        }


def default_repo_sandbox(
    repo_root: Path,
    *,
    image: str = "python:3.12-slim",
    writeable: bool = False,
    secrets: Iterable[ScopedSecret] = (),
) -> SandboxSpec:
    """Build ONMC's conservative local repo sandbox contract."""

    return SandboxSpec(
        image=image,
        mounts=(
            SandboxMount(
                host_path=repo_root,
                container_path="/workspace",
                read_only=not writeable,
            ),
        ),
        workdir="/workspace",
        network=NetworkPolicy.DENY,
        secrets=tuple(secrets),
    )


__all__ = [
    "NetworkPolicy",
    "SandboxMount",
    "SandboxPlanError",
    "SandboxRole",
    "SandboxSpec",
    "ScopedSecret",
    "default_repo_sandbox",
]
