#!/usr/bin/env python
"""Run the M6 external-proof portfolio against real repositories.

Design (blueprint truth rules):

* **Real external repos, pinned SHAs.** Each trial clones a fresh copy of the
  upstream repository at a pinned commit — no shared mutable state between
  trials or conditions.
* **Seeded regression, real verifier.** A single upstream function is reverted to
  a broken state. The task is adjudicated by the repository's OWN upstream test
  suite, which was confirmed passing at the pinned SHA (validity gate). So a
  pass means real upstream behaviour was restored, never the agent's own word
  (rule 8: grade repository outcome, not agent prose).
* **Real controls.** ``bare-agent`` invokes the same agent CLI directly with the
  same prompt, model, permissions and verifier — it is a real execution, never a
  simulated empty condition (rule 5).
* **Equivalence.** Both arms get the same task, repo revision, verifier argv and
  timeout (rule 6).
* **Uncertainty.** Multiple trials with randomized condition order; every
  infrastructure failure is recorded, never silently dropped (rule 13).

Usage::

    python scripts/run_external_eval.py --manifest datasets/experiment/portfolio_external_v1.json \
        --workdir /tmp/eval --out /tmp/eval/report.json [--trials 3] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import random
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from oh_no_my_claudecode.experiment.contracts import (  # noqa: E402
    Condition,
    MetricLabel,
)
from oh_no_my_claudecode.experiment.portfolio import (  # noqa: E402
    PortfolioManifest,
    TaskSpec,
)

#: Seeded regressions: (task_id) -> (relative file, exact old text, broken text).
#: Each is a single-function revert whose repair is adjudicated by upstream tests.
REGRESSIONS: dict[str, tuple[str, str, str]] = {
    "six-bugfix-integer-types": (
        "six.py",
        "    integer_types = int,",
        "    integer_types = (str,)  # REGRESSION",
    ),
    "tenacity-bugfix-find-ordinal": (
        "tenacity/_utils.py",
        '    if pos_num == 1:\n        return "st"',
        '    if pos_num == 1:\n        return "th"  # REGRESSION',
    ),
    "attrs-bugfix-asdict-recurse": (
        "src/attr/_funcs.py",
        "        if filter is not None and not filter(a, v):\n            continue",
        "        if False:  # REGRESSION\n            continue",
    ),
}


@dataclass
class TrialRecord:
    task_id: str
    condition: str
    trial: int
    passed: bool
    latency_ms: float
    infra_error: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "condition": self.condition,
            "trial": self.trial,
            "passed": self.passed,
            "latency_ms": round(self.latency_ms, 1),
            "infra_error": self.infra_error,
            "notes": self.notes,
        }


@dataclass
class EvalConfig:
    workdir: Path
    trials: int
    dry_run: bool
    timeout_s: int = 900
    verifier_timeout_s: int = 300
    max_iterations: int = 4
    max_cost_usd: float = 3.0
    extra_env: dict[str, str] = field(default_factory=dict)


def _run(argv: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    try:
        proc = subprocess.run(  # noqa: S603
            argv, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return 124, "[timeout]"
    except OSError as exc:
        return 127, f"[oserror] {exc}"
    return proc.returncode, (proc.stdout + proc.stderr)[-4000:]


def prepare_clone(task: TaskSpec, dest: Path, cache: Path) -> str | None:
    """Clone the pinned repo into *dest* and inject the seeded regression."""
    if not cache.exists():
        code, out = _run(
            ["git", "clone", "--quiet", task.repo.url, str(cache)], cache.parent, 600
        )
        if code != 0:
            return f"clone failed: {out[-300:]}"
    code, out = _run(["git", "clone", "--quiet", str(cache), str(dest)], dest.parent, 600)
    if code != 0:
        return f"local clone failed: {out[-300:]}"
    code, out = _run(["git", "checkout", "--quiet", task.repo.pinned_sha], dest, 120)
    if code != 0:
        return f"checkout {task.repo.pinned_sha[:8]} failed: {out[-300:]}"

    rel, old, new = REGRESSIONS[task.task_id]
    target = dest / rel
    text = target.read_text(encoding="utf-8")
    if old not in text:
        return f"regression anchor not found in {rel}"
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return None


def verify(task: TaskSpec, repo: Path, cfg: EvalConfig) -> tuple[bool, str]:
    """Adjudicate with the repository's own upstream test suite."""
    code, out = _run(list(task.verifier_argv), repo, cfg.verifier_timeout_s)
    return code == 0, out


def guard_regression_active(task: TaskSpec, repo: Path, cfg: EvalConfig) -> str | None:
    """The verifier MUST fail before the agent runs, or the task proves nothing."""
    passed, out = verify(task, repo, cfg)
    if passed:
        return "regression did not break the verifier (task would be vacuous)"
    if "[timeout]" in out or "[oserror]" in out:
        return f"verifier infrastructure failure: {out[:200]}"
    return None


def run_bare_agent(task: TaskSpec, repo: Path, cfg: EvalConfig) -> str | None:
    """Control arm: the agent CLI directly, same prompt/permissions/verifier."""
    argv = [
        "claude",
        "-p",
        f"{task.prompt}\n\nThe adjudicating test command is: "
        f"{shlex.join(task.verifier_argv)}",
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
    ]
    code, out = _run(argv, repo, cfg.timeout_s)
    if code == 127:
        return f"agent CLI unavailable: {out[:200]}"
    if "[timeout]" in out:
        return "agent timeout"
    return None


def run_onmc(task: TaskSpec, repo: Path, cfg: EvalConfig) -> str | None:
    """Treatment arm: the same task through the full `onmc run` vertical path."""
    if not (repo / ".git").exists():
        code, out = _run(["git", "init", "--quiet"], repo, 60)
    else:
        code, out = 0, ""
    if code != 0:
        return f"git init failed: {out[:200]}"
    _run(["uv", "run", "--project", str(REPO_ROOT), "onmc", "init"], repo, 300)
    argv = [
        "uv",
        "run",
        "--project",
        str(REPO_ROOT),
        "onmc",
        "run",
        task.prompt,
        "--execute",
        "--agent",
        "claude",
        "--max-iterations",
        str(cfg.max_iterations),
        "--max-cost-usd",
        str(cfg.max_cost_usd),
        "--verifier",
        shlex.join(task.verifier_argv),
        "--json",
    ]
    code, out = _run(argv, repo, cfg.timeout_s)
    if "[timeout]" in out:
        return "onmc run timeout"
    if code == 127:
        return f"onmc unavailable: {out[:200]}"
    return None


RUNNERS = {
    Condition.BARE_AGENT: run_bare_agent,
    Condition.ONMC_CURRENT: run_onmc,
}


def run_cell(
    task: TaskSpec, condition: Condition, trial: int, cfg: EvalConfig, cache_root: Path
) -> TrialRecord:
    slug = f"{task.task_id}.{condition.value}.t{trial}"
    dest = cfg.workdir / "runs" / slug
    dest.parent.mkdir(parents=True, exist_ok=True)
    cache = cache_root / task.repo.name

    started = time.monotonic()
    err = prepare_clone(task, dest, cache)
    if err:
        return TrialRecord(task.task_id, condition.value, trial, False, 0.0, infra_error=err)

    err = guard_regression_active(task, dest, cfg)
    if err:
        return TrialRecord(task.task_id, condition.value, trial, False, 0.0, infra_error=err)

    if cfg.dry_run:
        return TrialRecord(
            task.task_id, condition.value, trial, False, 0.0, notes="dry-run: agent not invoked"
        )

    infra = RUNNERS[condition](task, dest, cfg)
    passed, out = verify(task, dest, cfg)
    latency = (time.monotonic() - started) * 1000.0
    note = "" if passed else out.strip().splitlines()[-1][:160] if out.strip() else ""
    return TrialRecord(
        task.task_id, condition.value, trial, passed, latency, infra_error=infra, notes=note
    )


def summarize(records: list[TrialRecord], conditions: list[Condition]) -> dict[str, object]:
    summary: dict[str, object] = {}
    for cond in conditions:
        rows = [r for r in records if r.condition == cond.value]
        usable = [r for r in rows if r.infra_error is None]
        passed = sum(1 for r in usable if r.passed)
        summary[cond.value] = {
            "cells": len(rows),
            "usable": len(usable),
            "infra_failures": len(rows) - len(usable),
            "passed": passed,
            "pass_at_1": round(passed / len(usable), 4) if usable else None,
            "mean_latency_ms": (
                round(sum(r.latency_ms for r in usable) / len(usable), 1) if usable else None
            ),
        }
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trials", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    manifest = PortfolioManifest.from_dict(json.loads(Path(args.manifest).read_text()))
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    cache_root = workdir / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)

    trials = args.trials or manifest.experiment.trials
    conditions = list(manifest.experiment.conditions)
    cfg = EvalConfig(workdir=workdir, trials=trials, dry_run=args.dry_run)

    cells: list[tuple[TaskSpec, Condition, int]] = [
        (task, cond, t)
        for task in manifest.tasks
        for cond in conditions
        for t in range(1, trials + 1)
    ]
    rng = random.Random(manifest.experiment.seed)  # noqa: S311 - shuffling trial order, not crypto
    rng.shuffle(cells)  # randomized condition order (rule 7)

    records: list[TrialRecord] = []
    for idx, (task, cond, trial) in enumerate(cells, start=1):
        rec = run_cell(task, cond, trial, cfg, cache_root)
        records.append(rec)
        print(
            f"[{idx}/{len(cells)}] {rec.task_id} {rec.condition} t{rec.trial}: "
            f"passed={rec.passed} infra={rec.infra_error or '-'}",
            flush=True,
        )

    report = {
        "experiment_id": manifest.experiment.experiment_id.value,
        "task_set_revision": manifest.experiment.task_set_revision,
        "audit_status": manifest.audit_status.value,
        "code_sha": manifest.experiment.environment.code_sha,
        "trials_per_cell": trials,
        "conditions": [c.value for c in conditions],
        "repos": sorted({t.repo.name for t in manifest.tasks}),
        "metric_label": MetricLabel.MEASURED.value,
        "summary": summarize(records, conditions),
        "records": [r.to_dict() for r in records],
    }
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
