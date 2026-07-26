#!/usr/bin/env python
"""Run and fail-closed import a bounded nop/local Harbor Docker smoke."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from export_harbor_tasks import _external_seed_tables  # noqa: E402

from oh_no_my_claudecode.experiment.contracts import Condition  # noqa: E402
from oh_no_my_claudecode.experiment.harbor_adapter import (  # noqa: E402
    export_portfolio_to_harbor,
    plan_harbor_smoke,
    run_harbor_smoke,
    validate_harbor_seed_manifest,
)
from oh_no_my_claudecode.experiment.portfolio import (  # noqa: E402
    PortfolioManifest,
    load_portfolio,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="ONMC portfolio manifest JSON.")
    parser.add_argument("--out", type=Path, required=True, help="Fresh Harbor task directory.")
    parser.add_argument("--jobs-dir", type=Path, required=True, help="Fresh Harbor jobs directory.")
    parser.add_argument(
        "--receipt",
        type=Path,
        required=True,
        help="Write batch receipt JSON here.",
    )
    parser.add_argument(
        "--task-id",
        action="append",
        default=[],
        help="Task id to include; repeat to select an explicit smoke slice.",
    )
    parser.add_argument(
        "--limit-tasks",
        type=int,
        default=2,
        help="Use the first N tasks when --task-id is omitted.",
    )
    parser.add_argument(
        "--condition",
        action="append",
        choices=[condition.value for condition in Condition],
        default=[],
        help="Condition label; repeat as needed. Defaults to both control labels.",
    )
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--max-cells", type=int, default=4)
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Execute nop/local Docker cells. Without this flag only preflight and plan are written."
        ),
    )
    args = parser.parse_args(argv)

    if args.out.exists():
        raise ValueError(f"--out must not already exist: {args.out}")
    if args.jobs_dir.exists():
        raise ValueError(f"--jobs-dir must not already exist: {args.jobs_dir}")

    full_manifest = load_portfolio(args.manifest)
    regression_hunks, removals, planted_files, test_deps = _external_seed_tables()
    seed_validation = validate_harbor_seed_manifest(
        full_manifest,
        regression_hunks=regression_hunks,
        removals=removals,
        planted_files=planted_files,
        test_deps=test_deps,
    )
    seed_validation.require_complete()
    manifest = _select_tasks(full_manifest, args.task_id, args.limit_tasks)
    summary = export_portfolio_to_harbor(
        manifest,
        args.out,
        regression_hunks=regression_hunks,
        removals=removals,
        planted_files=planted_files,
        test_deps=test_deps,
    )
    condition_values = (
        tuple(Condition(value) for value in args.condition)
        if args.condition
        else (Condition.BARE_AGENT, Condition.ONMC_CURRENT)
    )
    plan = plan_harbor_smoke(
        summary.task_names,
        output_root=args.out,
        conditions=condition_values,
        trials=args.trials,
        max_cells=args.max_cells,
        agent="nop",
        model="local",
        jobs_dir=args.jobs_dir,
    )
    payload: dict[str, object] = {
        "schema_version": "onmc-harbor-smoke-run/v1",
        "executed": args.execute,
        "full_seed_validation": seed_validation.to_dict(),
        "export": summary.to_dict(),
        "smoke_plan": plan.to_dict(),
        "claim_eligible": False,
        "limitations": list(plan.limitations),
    }
    if args.execute:
        imported = run_harbor_smoke(
            plan,
            experiment_id=manifest.experiment.experiment_id.value,
        )
        payload["batch_import"] = imported.to_dict()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


def _select_tasks(
    manifest: PortfolioManifest,
    task_ids: list[str],
    limit: int,
) -> PortfolioManifest:
    if task_ids:
        requested = set(task_ids)
        available = {task.task_id for task in manifest.tasks}
        unknown = sorted(requested - available)
        if unknown:
            raise ValueError("unknown --task-id value(s): " + ", ".join(unknown))
        tasks = tuple(task for task in manifest.tasks if task.task_id in requested)
    else:
        if limit < 1:
            raise ValueError("--limit-tasks must be positive")
        tasks = manifest.tasks[:limit]
    return PortfolioManifest(
        experiment=manifest.experiment,
        tasks=tasks,
        audit_status=manifest.audit_status,
        leakage_notes=manifest.leakage_notes,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
