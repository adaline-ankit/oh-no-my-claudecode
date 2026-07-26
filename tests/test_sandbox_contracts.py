from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from oh_no_my_claudecode.sandbox import (
    NetworkPolicy,
    SandboxExecutionStatus,
    SandboxPlanError,
    SandboxSpec,
    ScopedSecret,
    default_repo_sandbox,
    docker_run_plan,
    execute_docker_plan,
    harbor_task_payload,
)


def test_default_repo_sandbox_denies_host_paths_outside_mount(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("host secret", encoding="utf-8")

    spec = default_repo_sandbox(repo)

    assert spec.allows_host_path(repo / "src" / "app.py") is True
    assert spec.allows_host_path(outside) is False
    assert spec.network is NetworkPolicy.DENY
    assert spec.mounts[0].read_only is True


def test_docker_plan_uses_network_none_and_redacts_secret_values(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec = default_repo_sandbox(
        repo,
        secrets=(ScopedSecret("ANTHROPIC_API_KEY", roles=("agent",)),),
    )

    plan = docker_run_plan(spec, ("python", "-m", "pytest"), role="agent")

    assert "--network" in plan.argv
    assert "none" in plan.argv
    assert "--env" in plan.argv
    assert "ANTHROPIC_API_KEY" in plan.argv
    assert not any("sk-" in item for item in plan.argv)


def test_verifier_role_receives_no_agent_provider_secret(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec = default_repo_sandbox(
        repo,
        secrets=(ScopedSecret("ANTHROPIC_API_KEY", roles=("agent",)),),
    )

    plan = docker_run_plan(spec, ("python", "-m", "pytest"), role="verifier")

    assert plan.secret_env == ()
    assert "ANTHROPIC_API_KEY" not in plan.argv


def test_docker_fails_closed_when_allowlist_cannot_be_enforced(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    base = default_repo_sandbox(repo)
    spec = SandboxSpec(
        image=base.image,
        mounts=base.mounts,
        network=NetworkPolicy.ALLOWLIST,
        egress_allowlist=("pypi.org",),
    )

    with pytest.raises(SandboxPlanError, match="cannot enforce egress allowlist"):
        docker_run_plan(spec, ("python", "-V"))


def test_harbor_payload_preserves_boundary_without_secret_values(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec = default_repo_sandbox(
        repo,
        secrets=(
            ScopedSecret("ANTHROPIC_API_KEY", roles=("agent",)),
            ScopedSecret("PYPI_TOKEN", roles=("setup",)),
        ),
    )

    payload = harbor_task_payload(spec, ("python", "-m", "pytest"), role="agent")

    assert payload["provider"] == "harbor"
    assert payload["network"] == "deny"
    assert payload["secret_env"] == ["ANTHROPIC_API_KEY"]
    rendered = repr(payload)
    assert "PYPI_TOKEN" not in payload["secret_env"]
    assert "sk-" not in rendered


def test_execute_docker_plan_scopes_environment_and_captures_success(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    spec = default_repo_sandbox(
        repo,
        secrets=(ScopedSecret("ANTHROPIC_API_KEY", roles=("agent",)),),
    )
    plan = docker_run_plan(spec, ("python", "-V"), role="agent")
    home = str(tmp_path / "home")
    seen: dict[str, object] = {}

    def runner(
        argv: Sequence[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        seen.update(
            {
                "argv": tuple(argv),
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
                "env": dict(env),
            }
        )
        return subprocess.CompletedProcess(list(argv), 0, "ok", "")

    result = execute_docker_plan(
        plan,
        env={
            "PATH": "/bin",
            "HOME": home,
            "ANTHROPIC_API_KEY": "secret-value",
            "OPENAI_API_KEY": "must-not-leak",
        },
        runner=runner,
    )

    assert result.status is SandboxExecutionStatus.SUCCEEDED
    assert result.succeeded is True
    assert result.returncode == 0
    assert result.stdout == "ok"
    assert seen["timeout"] == float(plan.timeout_seconds)
    assert seen["env"] == {
        "PATH": "/bin",
        "HOME": home,
        "ANTHROPIC_API_KEY": "secret-value",
    }
    assert "must-not-leak" not in repr(result.to_dict())


def test_execute_docker_plan_classifies_failure_timeout_and_missing_docker(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plan = docker_run_plan(default_repo_sandbox(repo), ("python", "-m", "pytest"))

    def fail_runner(
        argv: Sequence[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, timeout, env
        return subprocess.CompletedProcess(list(argv), 2, "", "failed")

    failed = execute_docker_plan(plan, env={}, runner=fail_runner)
    assert failed.status is SandboxExecutionStatus.FAILED
    assert failed.returncode == 2
    assert failed.stderr == "failed"

    def timeout_runner(
        argv: Sequence[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, timeout, env
        raise subprocess.TimeoutExpired(list(argv), timeout=1, output=b"out", stderr=b"err")

    timed_out = execute_docker_plan(plan, env={}, runner=timeout_runner)
    assert timed_out.status is SandboxExecutionStatus.TIMED_OUT
    assert timed_out.stdout == "out"
    assert timed_out.stderr == "err"

    def missing_runner(
        argv: Sequence[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        del argv, capture_output, text, timeout, env
        raise FileNotFoundError("docker")

    unavailable = execute_docker_plan(plan, env={}, runner=missing_runner)
    assert unavailable.status is SandboxExecutionStatus.UNAVAILABLE
    assert unavailable.returncode is None
