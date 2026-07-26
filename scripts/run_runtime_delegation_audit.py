#!/usr/bin/env python3
"""Audit that product workflows expose canonical runtime contracts.

This is a zero-cost structural audit. It creates a throwaway repository and
checks that mission, wrap, and inline swarm produce valid ``RunSpec`` contracts
without spawning an agent, calling a model, or using the network.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from oh_no_my_claudecode import init  # noqa: E402
from oh_no_my_claudecode.mission.pipeline import run_mission  # noqa: E402
from oh_no_my_claudecode.runtime.contracts import RunSpec  # noqa: E402
from oh_no_my_claudecode.swarm.inline import plan_inline_swarm  # noqa: E402
from oh_no_my_claudecode.wrap.runtime import arm_mission  # noqa: E402

_SCHEMA_VERSION = "onmc-runtime-delegation-audit/v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)

    artifact = run_runtime_delegation_audit()
    rendered = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    if args.json_out is None:
        print(rendered, end="")
    else:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    return 0 if artifact["ready"] is True else 1


def run_runtime_delegation_audit() -> dict[str, object]:
    start = time.monotonic()
    blockers: list[str] = []
    views: dict[str, dict[str, object]] = {}

    with tempfile.TemporaryDirectory(prefix="onmc-runtime-delegation-") as tmp:
        repo = Path(tmp)
        _seed_repo(repo)
        handle = init(repo)
        handle.ingest()
        _, _, storage = handle._service._load_context()

        views["mission"] = _audit_mission(storage, repo)
        views["wrap"] = _audit_wrap(repo)
        views["swarm"] = _audit_swarm(repo)

    for name, view in sorted(views.items()):
        if view.get("ready") is not True:
            blockers.append(f"{name} runtime delegation is not ready")
        blockers.extend(str(item) for item in _list(view.get("blockers")))

    return {
        "schema_version": _SCHEMA_VERSION,
        "ready": not blockers,
        "evaluated": True,
        "canonical_contract": "RunSpec",
        "model_calls": 0,
        "network_used": False,
        "agent_execution_attempted": False,
        "views": views,
        "duration_ms": int((time.monotonic() - start) * 1000),
        "blockers": blockers,
    }


def _seed_repo(repo: Path) -> None:
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "src" / "app.py").write_text(
        "def add(left: int, right: int) -> int:\n    return left + right\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_app.py").write_text(
        "from src.app import add\n\n\ndef test_add() -> None:\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    (repo / "pyproject.toml").write_text(
        "[project]\nname = \"onmc-runtime-audit-fixture\"\nversion = \"0.0.0\"\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)


def _audit_mission(storage: Any, repo: Path) -> dict[str, object]:
    try:
        mission = run_mission(
            storage,
            repo,
            "fix add function",
            execute=False,
            verifier="pytest tests",
        )
        return _view(
            "mission",
            "mission.run_mission -> HarnessController.run(plan_only=True)",
            mission.runtime_contract,
            mission.runtime_contract_digest,
        )
    except Exception as exc:  # pragma: no cover - defensive artifact detail
        return _failed_view("mission", str(exc))


def _audit_wrap(repo: Path) -> dict[str, object]:
    try:
        mission = arm_mission(
            repo,
            "runtime-delegation-audit",
            "fix add function",
            strict=True,
            verifier="pytest tests",
            fingerprint_reader=lambda _repo: "baseline",
        )
        if mission is None:
            return _failed_view("wrap", "wrap did not arm an actionable coding mission")
        return _view(
            "wrap",
            "wrap.arm_mission -> HarnessController.run(plan_only=True)",
            mission.runtime_contract,
            mission.runtime_contract_digest,
        )
    except Exception as exc:  # pragma: no cover - defensive artifact detail
        return _failed_view("wrap", str(exc))


def _audit_swarm(repo: Path) -> dict[str, object]:
    try:
        plan = plan_inline_swarm(
            repo,
            ["fix src/app.py", "verify tests/test_app.py"],
            concurrency=2,
            swarm_id="runtime-audit",
            agent="claude-code-subagent",
            claim_paths=[["src/app.py"], ["tests/test_app.py"]],
        )
        return _view(
            "swarm",
            "swarm.plan_inline_swarm -> swarm.runtime_contract.build_swarm_run_spec",
            _mapping(plan.get("runtime_contract")),
            str(plan.get("runtime_contract_digest", "")),
        )
    except Exception as exc:  # pragma: no cover - defensive artifact detail
        return _failed_view("swarm", str(exc))


def _view(
    name: str,
    delegates_to: str,
    contract: dict[str, object] | None,
    digest: str | None,
) -> dict[str, object]:
    blockers: list[str] = []
    spec: RunSpec | None = None
    digest_validated = False
    node_kinds: list[str] = []
    side_effect_nodes_complete = False

    if not contract:
        blockers.append(f"{name} did not expose a runtime contract")
    else:
        try:
            spec = RunSpec.from_dict(contract)
            digest_validated = bool(digest) and spec.digest == digest
            node_kinds = sorted({node.kind for node in spec.nodes})
            side_effect_nodes = [node for node in spec.nodes if node.side_effecting]
            side_effect_nodes_complete = all(
                node.idempotency_key
                and node.budget is not None
                and node.retry_policy is not None
                and node.timeout_seconds is not None
                and node.completion_condition
                for node in side_effect_nodes
            )
        except Exception as exc:
            blockers.append(f"{name} runtime contract is invalid: {exc}")

    if contract and not digest_validated:
        blockers.append(f"{name} runtime contract digest was not validated")
    if spec is not None and not side_effect_nodes_complete:
        blockers.append(f"{name} side-effect nodes are missing runtime controls")

    return {
        "ready": not blockers,
        "delegates_to": delegates_to,
        "runtime_contract_present": contract is not None,
        "runtime_contract_digest": digest or "",
        "digest_validated": digest_validated,
        "run_id": spec.run_id if spec is not None else "",
        "node_count": len(spec.nodes) if spec is not None else 0,
        "node_kinds": node_kinds,
        "side_effect_nodes_complete": side_effect_nodes_complete,
        "blockers": blockers,
    }


def _failed_view(name: str, error: str) -> dict[str, object]:
    return {
        "ready": False,
        "delegates_to": "unknown",
        "runtime_contract_present": False,
        "runtime_contract_digest": "",
        "digest_validated": False,
        "run_id": "",
        "node_count": 0,
        "node_kinds": [],
        "side_effect_nodes_complete": False,
        "blockers": [f"{name} audit failed: {error}"],
    }


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


if __name__ == "__main__":
    raise SystemExit(main())
