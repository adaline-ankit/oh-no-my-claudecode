#!/usr/bin/env python3
"""Run a zero-cost ONMC product smoke in a throwaway git repository."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from oh_no_my_claudecode import __version__  # noqa: E402
from oh_no_my_claudecode.cli import app  # noqa: E402

_SCHEMA_VERSION = "onmc-product-smoke/v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)

    artifact = run_product_smoke()
    rendered = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    if args.json_out is None:
        print(rendered, end="")
    else:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    return 0 if artifact["ready"] is True else 1


def run_product_smoke() -> dict[str, object]:
    start = time.monotonic()
    blockers: list[str] = []

    with tempfile.TemporaryDirectory(prefix="onmc-product-smoke-") as tmp:
        repo = Path(tmp)
        git = subprocess.run(
            ["git", "init", "-q"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )
        if git.returncode != 0:
            blockers.append("temporary git repository could not be initialized")

        runner = CliRunner()
        previous_cwd = Path.cwd()
        try:
            os.chdir(repo)
            init_result = runner.invoke(app, ["init"], catch_exceptions=False, env={})
            commands_result = runner.invoke(
                app,
                ["commands", "--json"],
                catch_exceptions=False,
                env={},
            )
            run_result = runner.invoke(
                app,
                [
                    "run",
                    "Product smoke: plan a safe repository change",
                    "--plan-only",
                    "--json",
                ],
                catch_exceptions=False,
                env={},
            )
        finally:
            os.chdir(previous_cwd)

        commands_payload = _load_json(commands_result.stdout)
        run_payload = _load_json(run_result.stdout)
        plan = _mapping(run_payload.get("plan"))

        surface = _mapping(commands_payload.get("surface"))
        init_verified = (
            init_result.exit_code == 0
            and (repo / ".onmc" / "memory.db").exists()
            and (repo / ".onmc" / "config.yaml").exists()
        )
        commands_surface_ready = (
            commands_result.exit_code == 0
            and "run" in _string_list(commands_payload.get("core"))
            and surface.get("ready") is True
            and surface.get("canonical_entrypoint") == "run"
        )
        plan_only_verified = (
            run_result.exit_code == 0
            and run_payload.get("status") == "planned"
            and run_payload.get("stop_reason") == "plan-only"
            and run_payload.get("iterations") is None
            and run_payload.get("receipt") is None
            and _mapping(plan.get("resume")).get("supported") is True
        )

        if not init_verified:
            blockers.append("onmc init did not create usable repo-local state")
        if not commands_surface_ready:
            blockers.append("onmc commands --json did not confirm the primary surface")
        if not plan_only_verified:
            blockers.append("onmc run --plan-only --json did not return a valid plan")

        artifact: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "ready": not blockers,
            "evaluated": True,
            "mode": "in-process-typer-cli",
            "package_version": _source_version(),
            "installed_metadata_version": __version__,
            "canonical_entrypoint": "run",
            "temporary_repo_initialized": git.returncode == 0,
            "init_exit_code": init_result.exit_code,
            "commands_exit_code": commands_result.exit_code,
            "run_exit_code": run_result.exit_code,
            "init_verified": init_verified,
            "commands_surface_ready": commands_surface_ready,
            "visible_core_commands": _string_list(commands_payload.get("core")),
            "run_id": _mapping(plan).get("run_id"),
            "run_status": run_payload.get("status", "unknown"),
            "run_stop_reason": run_payload.get("stop_reason", "unknown"),
            "plan_only_verified": plan_only_verified,
            "model_calls": 0,
            "network_used": False,
            "agent_execution_attempted": False,
            "receipt_written": run_payload.get("receipt") is not None,
            "duration_ms": int((time.monotonic() - start) * 1000),
            "blockers": blockers,
        }
        return artifact


def _load_json(raw: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(str(item) for item in value if isinstance(item, str))


def _source_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data.get("project")
    if isinstance(project, dict):
        version = project.get("version")
        if isinstance(version, str):
            return version
    return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
