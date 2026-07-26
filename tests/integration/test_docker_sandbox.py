from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from oh_no_my_claudecode.sandbox import (
    SandboxExecutionStatus,
    default_repo_sandbox,
    docker_run_plan,
    execute_docker_plan,
    stage_repository_copy,
)


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        completed = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


@pytest.mark.skipif(not _docker_available(), reason="Docker daemon is unavailable")
def test_docker_executes_repository_copy_without_exposing_host_paths(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    source_marker = source / "marker.txt"
    source_marker.write_text("snapshot", encoding="utf-8")
    staged = stage_repository_copy(source, tmp_path / "sandbox-input" / "repo")
    source_marker.write_text("host-mutated-after-copy", encoding="utf-8")
    (tmp_path / "host-secret.txt").write_text("must-not-be-visible", encoding="utf-8")

    script = (
        "import json; from pathlib import Path; "
        "print(json.dumps({"
        "'cwd': str(Path.cwd()), "
        "'marker': Path('marker.txt').read_text(), "
        "'outside_visible': Path('/host-secret.txt').exists()"
        "}))"
    )
    spec = default_repo_sandbox(
        staged,
        image="python:3.12-slim",
        mount_source="repository-copy",
    )
    plan = docker_run_plan(spec, ("python", "-c", script), role="verifier")

    result = execute_docker_plan(plan)

    assert result.status is SandboxExecutionStatus.SUCCEEDED
    assert json.loads(result.stdout) == {
        "cwd": "/workspace",
        "marker": "snapshot",
        "outside_visible": False,
    }
    assert str(source) not in result.stdout
    assert str(staged) not in result.stdout
    assert str(source) not in repr(plan.to_dict())
    assert str(staged) not in repr(plan.to_dict())
