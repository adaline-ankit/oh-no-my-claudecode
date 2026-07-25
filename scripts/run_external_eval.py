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
from oh_no_my_claudecode.experiment.stats import (  # noqa: E402
    bootstrap_ci,
    derive_seed,
    mean,
    paired_deltas,
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
    cost_usd: float | None = None
    diff_lines: int = 0
    tests_touched: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "condition": self.condition,
            "trial": self.trial,
            "passed": self.passed,
            "latency_ms": round(self.latency_ms, 1),
            "infra_error": self.infra_error,
            "notes": self.notes,
            "cost_usd": None if self.cost_usd is None else round(self.cost_usd, 4),
            "diff_lines": self.diff_lines,
            "tests_touched": self.tests_touched,
        }


@dataclass
class EvalConfig:
    workdir: Path
    trials: int
    dry_run: bool
    timeout_s: int = 900
    verifier_timeout_s: int = 300
    max_iterations: int = 4
    max_cost_usd: float = 1.0
    max_total_usd: float = 10.0
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

    # COMMIT the seeded regression. Leaving it uncommitted made the broken state
    # itself the working diff, so an agent that correctly restored upstream
    # behaviour produced an EMPTY diff versus HEAD — which ONMC's vacuous-pass
    # ChangeProbe reads as "no meaningful change" and blocks. That penalised the
    # treatment arm for being right. With the regression committed, the repair is
    # a real diff in both arms and the arms stay equivalent (rule 6).
    _run(["git", "-c", "user.email=eval@onmc.local", "-c", "user.name=onmc-eval",
          "commit", "--quiet", "--all", "-m", f"seed regression: {task.task_id}"], dest, 120)
    code, out = _run(["git", "status", "--porcelain"], dest, 60)
    if code != 0 or out.strip():
        return f"regression commit left a dirty tree: {out[:200]}"
    return None


def _observed_change(repo: Path) -> tuple[int, bool]:
    """Changed-line count and whether any test file was touched, versus the
    seeded-regression commit. Used to detect a no-op arm and test tampering."""
    code, out = _run(["git", "diff", "--numstat", "HEAD"], repo, 60)
    if code != 0:
        return 0, False
    lines = 0
    touched_tests = False
    for row in out.splitlines():
        parts = row.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        lines += sum(int(v) for v in (added, removed) if v.isdigit())
        base = path.rsplit("/", 1)[-1]
        if base.startswith("test_") or base.endswith("_test.py") or "/tests/" in f"/{path}":
            touched_tests = True
    return lines, touched_tests


def _extract_cost(out: str) -> float | None:
    """Best-effort per-run USD cost from the agent/onmc JSON output.

    Never fabricated: returns ``None`` when the run did not report a cost, so the
    report can say ``n/a`` instead of inventing a number.
    """
    for key in ("total_cost_usd", "cost_usd", "total_cost"):
        marker = f'"{key}"'
        idx = out.rfind(marker)
        while idx != -1:
            tail = out[idx + len(marker) :].lstrip()
            if tail.startswith(":"):
                num = tail[1:].strip()
                buf = ""
                for ch in num:
                    if ch.isdigit() or ch in ".-e+":
                        buf += ch
                    else:
                        break
                try:
                    return float(buf)
                except ValueError:
                    pass
            idx = out.rfind(marker, 0, idx)
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


def run_bare_agent(task: TaskSpec, repo: Path, cfg: EvalConfig) -> tuple[str | None, float | None]:
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
    cost = _extract_cost(out)
    if code == 127:
        return f"agent CLI unavailable: {out[:200]}", cost
    if "[timeout]" in out:
        return "agent timeout", cost
    return None, cost


def run_onmc(task: TaskSpec, repo: Path, cfg: EvalConfig) -> tuple[str | None, float | None]:
    """Treatment arm: the same task through the full `onmc run` vertical path."""
    # ONMC's own runtime state must never count as the agent's repository change,
    # or the vacuous-pass gate could pass on ONMC bookkeeping noise instead of a
    # real fix. The upstream repos do not gitignore `.onmc/`, so exclude it here.
    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write("\n.onmc/\n.agent-memory/\n")
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
    cost = _extract_cost(out)
    if "[timeout]" in out:
        return "onmc run timeout", cost
    if code == 127:
        return f"onmc unavailable: {out[:200]}", cost
    return None, cost


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

    infra, cost = RUNNERS[condition](task, dest, cfg)
    diff_lines, tests_touched = _observed_change(dest)
    passed, out = verify(task, dest, cfg)
    latency = (time.monotonic() - started) * 1000.0
    note = "" if passed else out.strip().splitlines()[-1][:160] if out.strip() else ""
    if passed and tests_touched:
        # The prompt forbids editing tests. A "pass" that edited a test is a
        # false green, not a repair — score it as a failure and say why.
        passed = False
        note = "false green: agent modified a test file"
    return TrialRecord(
        task.task_id,
        condition.value,
        trial,
        passed,
        latency,
        infra_error=infra,
        notes=note,
        cost_usd=cost,
        diff_lines=diff_lines,
        tests_touched=tests_touched,
    )


def summarize(
    records: list[TrialRecord], conditions: list[Condition], *, seed: int
) -> dict[str, object]:
    summary: dict[str, object] = {}
    for cond in conditions:
        rows = [r for r in records if r.condition == cond.value]
        usable = [r for r in rows if r.infra_error is None]
        outcomes = [1.0 if r.passed else 0.0 for r in usable]
        costs = [r.cost_usd for r in usable if r.cost_usd is not None]
        ci: tuple[float, float] | None = None
        if outcomes:
            ci = bootstrap_ci(outcomes, seed=derive_seed(seed, cond.value, "pass"))
        summary[cond.value] = {
            "cells": len(rows),
            "usable": len(usable),
            "infra_failures": len(rows) - len(usable),
            "passed": int(sum(outcomes)),
            "pass_at_1": round(mean(outcomes), 4) if outcomes else None,
            "pass_at_1_ci95": None if ci is None else [round(ci[0], 4), round(ci[1], 4)],
            "pass_hat_k": _pass_hat_k(usable),
            "mean_latency_ms": (
                round(mean([r.latency_ms for r in usable]), 1) if usable else None
            ),
            "mean_cost_usd": round(mean(costs), 4) if costs else None,
            "cost_reported_cells": len(costs),
            "false_greens_blocked": sum(1 for r in rows if r.tests_touched),
        }
    return summary


def _pass_hat_k(rows: list[TrialRecord]) -> float | None:
    """Consistency: the fraction of tasks that passed on EVERY usable trial."""
    by_task: dict[str, list[bool]] = {}
    for row in rows:
        by_task.setdefault(row.task_id, []).append(row.passed)
    if not by_task:
        return None
    return round(mean([1.0 if all(v) else 0.0 for v in by_task.values()]), 4)


def paired_analysis(
    records: list[TrialRecord], baseline: Condition, treatment: Condition, *, seed: int
) -> dict[str, object]:
    """Per-task paired delta with a bootstrap CI over the per-task deltas.

    Pairing is per TASK (mean pass-rate across that task's usable trials), so a
    task that is easy or hard for both arms cannot drive the delta.
    """

    def rates(cond: Condition) -> dict[str, float]:
        buckets: dict[str, list[float]] = {}
        for row in records:
            if row.condition != cond.value or row.infra_error is not None:
                continue
            buckets.setdefault(row.task_id, []).append(1.0 if row.passed else 0.0)
        return {task: mean(vals) for task, vals in buckets.items() if vals}

    base_rates, treat_rates = rates(baseline), rates(treatment)
    deltas = paired_deltas(base_rates, treat_rates)
    if not deltas:
        return {"paired_tasks": 0, "mean_delta": None, "delta_ci95": None}
    values = [deltas[key] for key in sorted(deltas)]
    low, high = bootstrap_ci(values, seed=derive_seed(seed, "paired", "delta"))
    return {
        "baseline": baseline.value,
        "treatment": treatment.value,
        "paired_tasks": len(values),
        "per_task_delta": {key: round(deltas[key], 4) for key in sorted(deltas)},
        "mean_delta": round(mean(values), 4),
        "delta_ci95": [round(low, 4), round(high, 4)],
        "significant": bool(low > 0.0 or high < 0.0),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trials", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--max-total-usd",
        type=float,
        default=10.0,
        help="Hard spend ceiling. Remaining cells are recorded as budget-stopped, never dropped.",
    )
    ap.add_argument("--max-cost-usd", type=float, default=1.0, help="Per-run agent cost cap.")
    args = ap.parse_args()

    manifest = PortfolioManifest.from_dict(json.loads(Path(args.manifest).read_text()))
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    cache_root = workdir / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)

    trials = args.trials or manifest.experiment.trials
    conditions = list(manifest.experiment.conditions)
    cfg = EvalConfig(
        workdir=workdir,
        trials=trials,
        dry_run=args.dry_run,
        max_cost_usd=args.max_cost_usd,
        max_total_usd=args.max_total_usd,
    )

    cells: list[tuple[TaskSpec, Condition, int]] = [
        (task, cond, t)
        for task in manifest.tasks
        for cond in conditions
        for t in range(1, trials + 1)
    ]
    rng = random.Random(manifest.experiment.seed)  # noqa: S311 - shuffling trial order, not crypto
    rng.shuffle(cells)  # randomized condition order (rule 7)

    records: list[TrialRecord] = []
    spent = 0.0
    budget_stopped = 0
    for idx, (task, cond, trial) in enumerate(cells, start=1):
        if spent >= cfg.max_total_usd:
            budget_stopped += 1
            records.append(
                TrialRecord(
                    task.task_id,
                    cond.value,
                    trial,
                    False,
                    0.0,
                    infra_error=f"budget-stopped at ${spent:.2f} of ${cfg.max_total_usd:.2f}",
                )
            )
            continue
        rec = run_cell(task, cond, trial, cfg, cache_root)
        records.append(rec)
        spent += rec.cost_usd or 0.0
        print(
            f"[{idx}/{len(cells)}] {rec.task_id} {rec.condition} t{rec.trial}: "
            f"passed={rec.passed} cost=${rec.cost_usd or 0.0:.3f} spent=${spent:.2f} "
            f"infra={rec.infra_error or '-'}",
            flush=True,
        )

    seed = manifest.experiment.seed
    report = {
        "experiment_id": manifest.experiment.experiment_id.value,
        "task_set_revision": manifest.experiment.task_set_revision,
        "audit_status": manifest.audit_status.value,
        "code_sha": manifest.experiment.environment.code_sha,
        "trials_per_cell": trials,
        "conditions": [c.value for c in conditions],
        "repos": sorted({t.repo.name for t in manifest.tasks}),
        "metric_label": MetricLabel.MEASURED.value,
        "total_cost_usd": round(spent, 4),
        "budget_ceiling_usd": cfg.max_total_usd,
        "budget_stopped_cells": budget_stopped,
        "summary": summarize(records, conditions, seed=seed),
        "paired": (
            paired_analysis(records, conditions[0], conditions[1], seed=seed)
            if len(conditions) >= 2
            else {}
        ),
        "records": [r.to_dict() for r in records],
    }
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    headline = {"summary": report["summary"], "paired": report["paired"]}
    print(json.dumps(headline, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
