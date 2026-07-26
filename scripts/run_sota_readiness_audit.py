#!/usr/bin/env python3
# ruff: noqa: E501
"""Render an honest R1-R19 SOTA-readiness audit from committed evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPO_ROOT / "docs" / "evidence"


@dataclass(frozen=True, slots=True)
class Requirement:
    req_id: str
    title: str
    status: str
    evidence: tuple[str, ...]
    reason: str
    next_gate: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.req_id,
            "title": self.title,
            "status": self.status,
            "evidence": list(self.evidence),
            "reason": self.reason,
            "next_gate": self.next_gate,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--markdown-out", type=Path, default=None)
    args = parser.parse_args(argv)

    artifact = build_readiness_audit()
    rendered_json = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    rendered_markdown = render_markdown(artifact)

    if args.json_out is None and args.markdown_out is None:
        print(rendered_json, end="")
    _write(args.json_out, rendered_json)
    _write(args.markdown_out, rendered_markdown)
    return 0


def build_readiness_audit() -> dict[str, object]:
    sota = _load(EVIDENCE / "sota-report.json")
    work_plan = _load(EVIDENCE / "publication-work-plan.json")
    runtime = _load(EVIDENCE / "runtime-delegation.json")
    smoke = _load(EVIDENCE / "product-smoke.json")
    verifier = _load(EVIDENCE / "verifier_external_v2_report.json")

    blocked_gates = tuple(_strings(_mapping(sota.get("claim_readiness")).get("blocked_gates")))
    deficits = _mapping(work_plan.get("deficits"))
    module_paths = _repo_paths()

    runtime_ready = runtime.get("ready") is True
    smoke_ready = smoke.get("ready") is True
    publication_ready = sota.get("publication_ready") is True
    product_ready = (
        _mapping(sota.get("product_surface")).get("ready") is True and smoke_ready
    )

    requirements = [
        Requirement(
            "R1",
            "canonical durable execution contract",
            "partial" if runtime_ready and _has(module_paths, "durable_runtime") else "missing",
            ("docs/evidence/runtime-delegation.json", "src/oh_no_my_claudecode/runtime/contracts.py"),
            "mission/wrap/swarm expose valid RunSpec contracts; crash-resume proof is not complete.",
            "fault-injection crash/resume audit across every RunSpec node",
        ),
        Requirement(
            "R2",
            "mission, wrap, swarm delegate to canonical runtime",
            "proven" if runtime_ready else "missing",
            ("docs/evidence/runtime-delegation.json",),
            "runtime delegation audit validates mission, wrap, and swarm RunSpec digests.",
            "keep audit green after each workflow PR",
        ),
        Requirement(
            "R3",
            "side-effect nodes declare controls",
            "partial" if runtime_ready else "missing",
            ("docs/evidence/runtime-delegation.json", "src/oh_no_my_claudecode/runtime/contracts.py"),
            "audited side-effect nodes have idempotency, budget, retry, timeout, and completion conditions; typed I/O gate is not separately proven.",
            "add typed input/output schema audit for every side-effecting node",
        ),
        Requirement(
            "R4",
            "single-agent, fan-out, interrupts, cancellation, crash recovery",
            "partial" if _has(module_paths, "runtime/fanout.py") else "missing",
            ("src/oh_no_my_claudecode/runtime/fanout.py", "src/oh_no_my_claudecode/durable_runtime/store.py"),
            "fan-out and durable state code exist; long soak, cancel, interrupt, and crash-recovery matrix is not proven.",
            "run 24h soak plus fault injection for cancellation and resume",
        ),
        Requirement(
            "R5",
            "no prose/process/vacuous completion",
            "partial" if _has(module_paths, "verifier") else "missing",
            ("src/oh_no_my_claudecode/verifier", "docs/evidence/verifier_external_v2_report.json"),
            "independent verifier modules and external report exist; publication verifier calibration is still blocked.",
            "pass external false-green sensitivity/specificity gate",
        ),
        Requirement(
            "R6",
            "independent evidence and protected-test policy",
            "partial" if verifier else "missing",
            ("docs/evidence/verifier_external_v2_report.json",),
            "verifier evidence exists; publication bundle still blocks verifier calibration.",
            "make verifier calibration ready in publication bundle",
        ),
        Requirement(
            "R7",
            "isolated default for autonomous work",
            "partial" if _has(module_paths, "sandbox") else "missing",
            ("src/oh_no_my_claudecode/sandbox", "src/oh_no_my_claudecode/harness_run/sandboxing.py"),
            "sandbox contracts exist; true default isolation is not proven by release evidence.",
            "add isolation audit artifact proving autonomous runs declare and enforce sandbox mode",
        ),
        Requirement(
            "R8",
            "local tamper-evident receipts",
            "partial" if _has(module_paths, "loop/receipt.py") else "missing",
            ("src/oh_no_my_claudecode/loop/receipt.py",),
            "receipt implementation exists; replay/export audit is not part of publication evidence.",
            "add receipt replay/export audit with hash-chain verification",
        ),
        Requirement(
            "R9",
            "measured retrieval policy",
            "partial" if _has(module_paths, "retrieval_eval") else "missing",
            ("src/oh_no_my_claudecode/retrieval_eval", "src/oh_no_my_claudecode/retrieval"),
            "retrieval policy and eval modules exist; held-out retrieval gate is not publication-ready.",
            "run held-out retrieval eval with recall/nDCG/context-efficiency thresholds",
        ),
        Requirement(
            "R10",
            "context provenance, token cost, confidence, fallback",
            "partial" if _has(module_paths, "retrieval/core.py") else "missing",
            ("src/oh_no_my_claudecode/retrieval/core.py",),
            "context machinery exists; committed report does not prove per-query provenance/confidence/fallback coverage.",
            "add context-selection audit artifact and downstream smoke",
        ),
        Requirement(
            "R11",
            "eval-gated repository learning",
            "partial" if _has(module_paths, "learning/promotion.py") else "missing",
            ("src/oh_no_my_claudecode/learning",),
            "learning promotion code exists; held-out protected-suite promotion proof is absent.",
            "run promote/reject audit on held-out protected suite",
        ),
        Requirement(
            "R12",
            "containerized pinned agent-neutral trials",
            "blocked" if "benchmark_plan" in blocked_gates else "partial",
            ("datasets/experiment/portfolio_external_v4.json", "src/oh_no_my_claudecode/experiment/harbor_adapter.py"),
            "external manifest exists, but publication matrix lacks required arms/seeds/configs.",
            "freeze 50-task, 5-arm, 3-seed, 3-config Harbor manifest",
        ),
        Requirement(
            "R13",
            "complete benchmark report evidence",
            "blocked" if "report_coverage" in blocked_gates else "partial",
            ("docs/evidence/sota-report.json", "docs/evidence/publication-work-plan.json"),
            "report exists but raw trajectories, verifier artifacts, token/cost, failure taxonomy, leakage, and environment coverage are incomplete.",
            "fill all R13 report coverage fields and raw artifact index",
        ),
        Requirement(
            "R14",
            "observed-trajectory model routing",
            "partial" if _has(module_paths, "autoroute/trajectory.py") else "missing",
            ("src/oh_no_my_claudecode/autoroute/trajectory.py", "src/oh_no_my_claudecode/experiment/routing.py"),
            "shadow trajectory routing exists; cost/quality non-inferiority gate is not passed.",
            "run router regret benchmark against static baselines",
        ),
        Requirement(
            "R15",
            "governed self-improvement experiments",
            "partial" if _has(module_paths, "learning/prediction.py") else "missing",
            ("src/oh_no_my_claudecode/learning/prediction.py", "src/oh_no_my_claudecode/experiment/kernel.py"),
            "prediction and experiment kernels exist; repeated autonomous improvement proof is absent.",
            "require prediction-backed experiment manifest before promotion",
        ),
        Requirement(
            "R16",
            "one setup and one task UX",
            "proven" if product_ready else "partial",
            ("docs/evidence/product-smoke.json", "docs/evidence/sota-report.json"),
            "product surface and smoke gates are ready.",
            "keep root help collapsed and validate external activation task",
        ),
        Requirement(
            "R17",
            "same contracts across Claude, Codex, OpenCode",
            "partial" if _has(module_paths, "loop/adapters.py") else "missing",
            ("src/oh_no_my_claudecode/loop/adapters.py", "src/oh_no_my_claudecode/runtime/adapter_capabilities.py"),
            "adapter contracts exist; conformance coverage across agents is not publication-ready.",
            "run adapter conformance suite with honest capability labels",
        ),
        Requirement(
            "R18",
            "Mission Control observed-only runtime view",
            "partial" if _has(module_paths, "missioncontrol/runtime.py") else "missing",
            ("src/oh_no_my_claudecode/missioncontrol/runtime.py",),
            "Mission Control runtime module exists; observed-only UI audit is not committed.",
            "add Mission Control artifact proving no synthetic progress",
        ),
        Requirement(
            "R19",
            "no unpatched critical default dependencies",
            "partial",
            ("pyproject.toml",),
            "release comments quarantine a known optional advisory; default install audit is not emitted as a SOTA evidence artifact.",
            "add dependency-audit artifact for default and recommended extras",
        ),
    ]

    counts = {
        status: sum(1 for req in requirements if req.status == status)
        for status in ("proven", "partial", "blocked", "missing")
    }
    return {
        "schema_version": "onmc-sota-readiness-audit/v1",
        "git_commit": _git("rev-parse", "HEAD"),
        "publication_ready": publication_ready,
        "claim_decision": _mapping(sota.get("claim_readiness")).get("decision", "unknown"),
        "blocked_publication_gates": list(blocked_gates),
        "summary": counts,
        "ready_requirements": counts["proven"],
        "total_requirements": len(requirements),
        "requirements": [req.to_dict() for req in requirements],
        "next_actions": _strings(work_plan.get("next_actions")),
        "deficits": deficits,
    }


def render_markdown(artifact: dict[str, object]) -> str:
    summary = _mapping(artifact.get("summary"))
    lines = [
        "# ONMC SOTA Readiness Audit",
        "",
        f"- commit: `{artifact.get('git_commit', 'unknown')}`",
        f"- publication ready: `{str(artifact.get('publication_ready') is True).lower()}`",
        f"- claim decision: `{artifact.get('claim_decision', 'unknown')}`",
        f"- proven requirements: `{artifact.get('ready_requirements')}/{artifact.get('total_requirements')}`",
        f"- partial: `{summary.get('partial', 0)}`",
        f"- blocked: `{summary.get('blocked', 0)}`",
        f"- missing: `{summary.get('missing', 0)}`",
        "",
        "## Requirements",
        "",
        "| Req | Status | Evidence | Next gate |",
        "|---|---|---|---|",
    ]
    for item in _list(artifact.get("requirements")):
        req = _mapping(item)
        evidence = ", ".join(f"`{path}`" for path in _strings(req.get("evidence")))
        lines.append(
            f"| {req.get('id')} | `{req.get('status')}` | {evidence} | "
            f"{req.get('next_gate')} |"
        )
    lines.extend(["", "## Blocked Publication Gates", ""])
    blocked = _strings(artifact.get("blocked_publication_gates"))
    lines.extend(f"- `{gate}`" for gate in blocked or ["none"])
    lines.append("")
    return "\n".join(lines)


def _repo_paths() -> tuple[str, ...]:
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "src/oh_no_my_claudecode"],
            cwd=REPO_ROOT,
            text=True,
        )
    except subprocess.SubprocessError:
        return ()
    return tuple(line.strip() for line in output.splitlines() if line.strip())


def _has(paths: tuple[str, ...], needle: str) -> bool:
    return any(needle in path for path in paths)


def _load(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: Path | None, content: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()
    except subprocess.SubprocessError:
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
