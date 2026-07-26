"""Harbor export surface for ONMC sandbox contracts."""

from __future__ import annotations

from typing import Any

from .contracts import SandboxPlanError, SandboxRole, SandboxSpec


def harbor_task_payload(
    spec: SandboxSpec,
    command: tuple[str, ...],
    *,
    role: SandboxRole = "agent",
) -> dict[str, Any]:
    """Return a Harbor-style task payload without leaking secret values."""

    if not command:
        raise SandboxPlanError("harbor command must not be empty")
    return {
        "provider": "harbor",
        "role": role,
        "image": spec.image,
        "image_digest": spec.image_digest,
        "workdir": spec.workdir,
        "command": list(command),
        "network": spec.network.value,
        "egress_allowlist": list(spec.egress_allowlist),
        "timeout_seconds": spec.timeout_seconds,
        "resources": {
            "cpus": spec.cpus,
            "memory_mb": spec.memory_mb,
        },
        "mounts": [mount.to_dict() for mount in spec.mounts],
        "secret_env": list(spec.secret_env_for(role)),
    }


__all__ = ["harbor_task_payload"]
