"""Provider-neutral sandbox contracts for autonomous ONMC execution.

This module is deliberately about enforceable boundaries, not marketing.
Worktrees isolate repository changes; a sandbox isolates process, filesystem,
network, and secrets. Providers such as Docker or Harbor compile this contract
into their own execution shape.
"""

from __future__ import annotations

import shutil
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
    source: str = "repository"

    def __post_init__(self) -> None:
        if not self.container_path.startswith("/"):
            raise SandboxPlanError("mount.container_path must be absolute")
        if self.container_path == "/":
            raise SandboxPlanError("mount.container_path must not be container root")
        if not str(self.host_path):
            raise SandboxPlanError("mount.host_path must not be empty")
        if not self.source or any(char.isspace() for char in self.source):
            raise SandboxPlanError("mount.source must be a non-empty identifier")

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
            "source": self.source,
        }

    def capability_dict(self) -> dict[str, object]:
        """Return the portable declaration without serializing a host path."""
        return {
            "source": self.source,
            "container_path": self.container_path,
            "access": "read-only" if self.read_only else "read-write",
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
        if len(set(self.roles)) != len(self.roles):
            raise SandboxPlanError("secret.roles must not contain duplicates")
        if any(role not in {"agent", "verifier", "setup"} for role in self.roles):
            raise SandboxPlanError("secret.roles contains an unsupported role")

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


@dataclass(frozen=True, slots=True)
class SandboxRoleCapabilityManifest:
    """Portable, enforceable capability declaration for one sandbox role."""

    role: SandboxRole
    filesystem: tuple[dict[str, object], ...]
    network: NetworkPolicy
    egress_allowlist: tuple[str, ...]
    secret_env: tuple[str, ...]
    timeout_seconds: int
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if self.role not in {"agent", "verifier", "setup"}:
            raise SandboxPlanError("sandbox role is unsupported")
        if not self.filesystem:
            raise SandboxPlanError(f"{self.role} filesystem declaration must not be empty")
        if self.role in {"verifier", "setup"}:
            if any(item.get("access") != "read-only" for item in self.filesystem):
                raise SandboxPlanError(f"{self.role} filesystem must be read-only")
            if self.network is not NetworkPolicy.DENY:
                raise SandboxPlanError(f"{self.role} network must be denied")
            if self.secret_env:
                raise SandboxPlanError(f"{self.role} secrets must be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "role": self.role,
            "filesystem": [dict(item) for item in self.filesystem],
            "network": self.network.value,
            "egress_allowlist": list(self.egress_allowlist),
            "secret_env": list(self.secret_env),
            "timeout_seconds": self.timeout_seconds,
        }


def sandbox_role_capability_manifest(
    spec: SandboxSpec,
    *,
    role: SandboxRole,
) -> SandboxRoleCapabilityManifest:
    """Compile and validate the capability boundary for *role*."""

    return SandboxRoleCapabilityManifest(
        role=role,
        filesystem=tuple(mount.capability_dict() for mount in spec.mounts),
        network=spec.network,
        egress_allowlist=spec.egress_allowlist,
        secret_env=spec.secret_env_for(role),
        timeout_seconds=spec.timeout_seconds,
    )


def default_repo_sandbox(
    repo_root: Path,
    *,
    image: str = "python:3.12-slim",
    writeable: bool = False,
    network: NetworkPolicy = NetworkPolicy.DENY,
    secrets: Iterable[ScopedSecret] = (),
    timeout_seconds: int = 600,
    mount_source: str = "repository",
) -> SandboxSpec:
    """Build ONMC's conservative local repo sandbox contract."""

    return SandboxSpec(
        image=image,
        mounts=(
            SandboxMount(
                host_path=repo_root,
                container_path="/workspace",
                read_only=not writeable,
                source=mount_source,
            ),
        ),
        workdir="/workspace",
        network=network,
        secrets=tuple(secrets),
        timeout_seconds=timeout_seconds,
    )


def stage_repository_copy(source_root: Path, destination_root: Path) -> Path:
    """Create an immutable-input repository snapshot for sandbox execution.

    The destination must be new and outside the source tree. Provider payloads
    identify this mount as ``repository-copy`` and never serialize its host path.
    """

    source = source_root.resolve()
    destination = destination_root.resolve()
    if not source.is_dir():
        raise SandboxPlanError("repository copy source must be an existing directory")
    if destination == source or source in destination.parents:
        raise SandboxPlanError("repository copy destination must be outside the source tree")
    if destination.exists():
        raise SandboxPlanError("repository copy destination must not already exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True)
    return destination


__all__ = [
    "NetworkPolicy",
    "SandboxMount",
    "SandboxPlanError",
    "SandboxRole",
    "SandboxRoleCapabilityManifest",
    "SandboxSpec",
    "ScopedSecret",
    "default_repo_sandbox",
    "sandbox_role_capability_manifest",
    "stage_repository_copy",
]
