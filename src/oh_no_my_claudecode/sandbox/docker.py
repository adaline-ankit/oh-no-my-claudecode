"""Docker planner for ONMC sandbox contracts.

The planner returns the command ONMC would execute. It does not run Docker.
This keeps preflight deterministic and lets tests prove fail-closed behavior
without requiring Docker on the developer machine.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from .contracts import NetworkPolicy, SandboxPlanError, SandboxRole, SandboxSpec


class _DockerRunner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]: ...


class SandboxExecutionStatus(StrEnum):
    """Terminal status for one sandbox command."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed-out"
    UNAVAILABLE = "unavailable"


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


@dataclass(frozen=True, slots=True)
class SandboxExecutionResult:
    """Captured result of one sandbox execution attempt."""

    status: SandboxExecutionStatus
    returncode: int | None
    stdout: str
    stderr: str
    argv_sha256: str
    timeout_seconds: int
    reason: str

    @property
    def succeeded(self) -> bool:
        return self.status is SandboxExecutionStatus.SUCCEEDED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "argv_sha256": self.argv_sha256,
            "timeout_seconds": self.timeout_seconds,
            "reason": self.reason,
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


def _run_subprocess(
    argv: Sequence[str],
    *,
    capture_output: bool,
    text: bool,
    timeout: float,
    env: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
        env=env,
    )


def execute_docker_plan(
    plan: DockerSandboxPlan,
    *,
    env: Mapping[str, str] | None = None,
    runner: _DockerRunner = _run_subprocess,
) -> SandboxExecutionResult:
    """Execute a precompiled Docker sandbox plan with scoped environment."""

    source_env = os.environ if env is None else env
    child_env = _scoped_env(source_env, plan.secret_env)
    argv_hash = hashlib.sha256("\0".join(plan.argv).encode()).hexdigest()
    try:
        completed = runner(
            plan.argv,
            capture_output=True,
            text=True,
            timeout=float(plan.timeout_seconds),
            env=child_env,
        )
    except subprocess.TimeoutExpired as exc:
        return SandboxExecutionResult(
            status=SandboxExecutionStatus.TIMED_OUT,
            returncode=None,
            stdout=_tail(_decode_timeout_output(exc.stdout)),
            stderr=_tail(_decode_timeout_output(exc.stderr)),
            argv_sha256=argv_hash,
            timeout_seconds=plan.timeout_seconds,
            reason="sandbox command timed out",
        )
    except FileNotFoundError as exc:
        return SandboxExecutionResult(
            status=SandboxExecutionStatus.UNAVAILABLE,
            returncode=None,
            stdout="",
            stderr=str(exc),
            argv_sha256=argv_hash,
            timeout_seconds=plan.timeout_seconds,
            reason="docker executable not available",
        )

    status = (
        SandboxExecutionStatus.SUCCEEDED
        if completed.returncode == 0
        else SandboxExecutionStatus.FAILED
    )
    return SandboxExecutionResult(
        status=status,
        returncode=completed.returncode,
        stdout=_tail(completed.stdout),
        stderr=_tail(completed.stderr),
        argv_sha256=argv_hash,
        timeout_seconds=plan.timeout_seconds,
        reason="sandbox command succeeded"
        if status is SandboxExecutionStatus.SUCCEEDED
        else "sandbox command failed",
    )


def _scoped_env(source: Mapping[str, str], secret_env: tuple[str, ...]) -> dict[str, str]:
    allowed = {"PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", *secret_env}
    return {key: value for key, value in source.items() if key in allowed}


def _tail(value: str, *, limit: int = 4096) -> str:
    return value[-limit:]


def _decode_timeout_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


__all__ = [
    "DockerSandboxPlan",
    "SandboxExecutionResult",
    "SandboxExecutionStatus",
    "docker_run_plan",
    "execute_docker_plan",
]
