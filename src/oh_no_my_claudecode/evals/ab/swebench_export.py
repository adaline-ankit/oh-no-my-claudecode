"""E7 — export repo-bench tasks in the SWE-bench task-instance format.

SWE-bench's jsonl instance format is the lingua franca of harness research —
every agent paper's tooling loads it. Exporting our mined tasks in that shape
means a private repo-bench corpus runs under any standard harness with zero
adaptation.

Field mapping (theirs ← ours):
- ``patch`` (the gold fix) ← the REVERSE of our ``setup_patch`` (ours re-plants
  the bug at the fix commit; its inverse is the fix itself).
- ``test_patch`` ← empty: repo-bench keeps the commit's own tests in the tree
  rather than applying them as a patch; the gate command carries them.
- ``FAIL_TO_PASS`` ← the gate command's test paths (fail with bug, pass fixed).
- ``base_commit`` ← the fix commit (with our setup patch applied on top, the
  tree is pre-fix — noted in ``environment_setup_commit`` semantics).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from oh_no_my_claudecode.evals.ab.models import ABTask


def _reverse_patch(patch: str) -> str:
    """Invert a unified diff textually (swap +/- and old/new headers).

    ponytail: textual inversion covers the plain hunks git produces for
    repo-bench source diffs; renames/mode changes would need `git apply -R`,
    which consumers can always run on ``onmc_setup_patch`` instead.
    """
    out: list[str] = []
    for line in patch.splitlines():
        if line.startswith("--- "):
            out.append("+++ " + line[4:])
        elif line.startswith("+++ "):
            out.append("--- " + line[4:])
        elif line.startswith("+") and not line.startswith("+++"):
            out.append("-" + line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            out.append("+" + line[1:])
        else:
            out.append(line)
    return "\n".join(out) + ("\n" if patch.endswith("\n") else "")


def to_swebench_instance(task: ABTask, *, repo: str) -> dict[str, object]:
    """One SWE-bench-shaped instance dict from one repo-bench task."""
    gate_parts = task.gate_command.split()
    fail_to_pass = [part for part in gate_parts if part.endswith(".py") and "test" in part]
    return {
        "instance_id": task.id,
        "repo": repo,
        "base_commit": task.repo_commit or "",
        "problem_statement": task.description,
        "patch": _reverse_patch(task.setup_patch) if task.setup_patch else "",
        "test_patch": "",  # tests live in-tree at base_commit; the gate runs them
        "FAIL_TO_PASS": fail_to_pass,
        "PASS_TO_PASS": [],
        "version": "onmc-repo-bench-1",
        # Extension keys (standard loaders ignore unknowns):
        "onmc_gate_command": task.gate_command,
        "onmc_setup_patch": task.setup_patch,
        "onmc_protected_paths": list(task.protected_paths),
    }


def export_swebench_jsonl(tasks: Sequence[ABTask], destination: Path, *, repo: str) -> int:
    """Write tasks as SWE-bench jsonl; returns the instance count."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for task in tasks:
            handle.write(json.dumps(to_swebench_instance(task, repo=repo), sort_keys=True) + "\n")
    return len(tasks)


__all__ = ["export_swebench_jsonl", "to_swebench_instance"]
