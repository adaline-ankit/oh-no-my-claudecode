#!/usr/bin/env python3
"""Install the built ONMC wheel and run a deterministic, zero-model-call smoke."""

from __future__ import annotations

import argparse
import json
import site
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def select_wheel(dist_dir: Path) -> Path:
    wheels = sorted(dist_dir.glob("oh_no_my_claudecode-*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"expected exactly one ONMC wheel in {dist_dir}, found {len(wheels)}")
    return wheels[0]


def validate_fixture_payload(payload: dict[str, Any]) -> None:
    if payload.get("fixture") is not True:
        raise ValueError("release smoke must use the offline fixture path")
    if payload.get("total_tasks") != 1:
        raise ValueError("release smoke expected exactly one fixture task")
    comparisons = payload.get("comparisons")
    if not isinstance(comparisons, list) or len(comparisons) != 1:
        raise ValueError("release smoke expected one comparison")
    comparison = comparisons[0]
    if not isinstance(comparison, dict):
        raise ValueError("release smoke comparison must be an object")
    treatment = comparison.get("onmc")
    if not isinstance(treatment, dict) or treatment.get("passed") is not True:
        raise ValueError("release smoke treatment fixture did not pass")
    if treatment.get("evidence_kind") != "fixture":
        raise ValueError("release smoke must remain explicitly labelled fixture evidence")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Use system site packages and install the wheel with --no-deps. "
            "The caller must preinstall runtime dependencies."
        ),
    )
    args = parser.parse_args(argv)
    wheel = select_wheel(args.dist_dir.resolve())

    with tempfile.TemporaryDirectory(prefix="onmc-release-smoke-") as temp_dir:
        root = Path(temp_dir)
        venv_dir = root / "venv"
        venv_args = [sys.executable, "-m", "venv"]
        if args.offline:
            venv_args.append("--system-site-packages")
        _run([*venv_args, str(venv_dir)], cwd=root)
        bin_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
        python = bin_dir / ("python.exe" if sys.platform == "win32" else "python")
        onmc = bin_dir / ("onmc.exe" if sys.platform == "win32" else "onmc")
        if args.offline:
            _expose_caller_site_packages(python, cwd=root)
        install = [str(python), "-m", "pip", "install", "--force-reinstall"]
        if args.offline:
            install.append("--no-deps")
        _run([*install, str(wheel)], cwd=root)
        version = _run([str(onmc), "--version"], cwd=root)
        fixture = _run(
            [
                str(onmc),
                "eval",
                "ab",
                "--fixture",
                "--task",
                "list_slice_fix",
                "--json",
            ],
            cwd=root,
        )
        payload = json.loads(fixture)
        if not isinstance(payload, dict):
            raise ValueError("release smoke output must be a JSON object")
        validate_fixture_payload(payload)
        print(
            json.dumps(
                {
                    "schema_version": "onmc-release-artifact-smoke/v1",
                    "wheel": wheel.name,
                    "version_output": version.strip(),
                    "fixture_task": "list_slice_fix",
                    "fixture_passed": True,
                    "network_used_by_smoke": not args.offline,
                    "model_calls": 0,
                    "claim_scope": (
                        "packaging and offline fixture execution only; "
                        "not external benchmark evidence"
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


def _expose_caller_site_packages(python: Path, *, cwd: Path) -> None:
    """Make already-installed caller dependencies visible without resolving packages."""

    caller_sites = [Path(item).resolve() for item in site.getsitepackages()]
    child_site = Path(
        _run(
            [
                str(python),
                "-c",
                "import sysconfig; print(sysconfig.get_paths()['purelib'])",
            ],
            cwd=cwd,
        ).strip()
    )
    child_site.mkdir(parents=True, exist_ok=True)
    (child_site / "onmc-release-smoke-dependencies.pth").write_text(
        "".join(f"{path}\n" for path in caller_sites),
        encoding="utf-8",
    )


def _run(argv: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(argv)}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return completed.stdout


if __name__ == "__main__":
    raise SystemExit(main())
