#!/usr/bin/env python
"""Export an ONMC portfolio manifest into Harbor task directories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from oh_no_my_claudecode.experiment.contracts import Condition  # noqa: E402
from oh_no_my_claudecode.experiment.harbor_adapter import (  # noqa: E402
    export_portfolio_to_harbor,
    plan_harbor_smoke,
)
from oh_no_my_claudecode.experiment.portfolio import (  # noqa: E402
    PortfolioManifest,
    load_portfolio,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="ONMC portfolio manifest JSON.")
    parser.add_argument("--out", type=Path, required=True, help="Output Harbor dataset dir.")
    parser.add_argument("--limit-tasks", type=int, default=None, help="Export first N tasks.")
    parser.add_argument(
        "--seed-regressions",
        action="store_true",
        help=(
            "Seed supported external-eval regressions into Harbor task images. "
            "Tasks without supported seed material fail closed."
        ),
    )
    parser.add_argument(
        "--smoke-plan",
        action="store_true",
        help="Include local Docker smoke plan.",
    )
    parser.add_argument("--smoke-trials", type=int, default=1)
    parser.add_argument("--max-cells", type=int, default=4)
    parser.add_argument("--agent", default="nop", help="Harbor smoke agent.")
    parser.add_argument("--model", default="local", help="Harbor smoke model label.")
    args = parser.parse_args(argv)

    manifest = _limited_manifest(load_portfolio(args.manifest), args.limit_tasks)
    if args.seed_regressions:
        regression_hunks, removals, planted_files, test_deps = _external_seed_tables()
        summary = export_portfolio_to_harbor(
            manifest,
            args.out,
            regression_hunks=regression_hunks,
            removals=removals,
            planted_files=planted_files,
            test_deps=test_deps,
        )
    else:
        summary = export_portfolio_to_harbor(manifest, args.out)
    payload = {
        "schema_version": "onmc-harbor-export/v1",
        "manifest": str(args.manifest),
        "export": summary.to_dict(),
    }
    if args.smoke_plan:
        smoke = plan_harbor_smoke(
            summary.task_names,
            output_root=args.out,
            conditions=(Condition.BARE_AGENT, Condition.ONMC_CURRENT),
            trials=args.smoke_trials,
            max_cells=args.max_cells,
            agent=args.agent,
            model=args.model,
        )
        payload["smoke_plan"] = smoke.to_dict()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _limited_manifest(manifest: PortfolioManifest, limit: int | None) -> PortfolioManifest:
    if limit is None:
        return manifest
    if limit < 1:
        raise ValueError("--limit-tasks must be positive")
    return PortfolioManifest(
        experiment=manifest.experiment,
        tasks=manifest.tasks[:limit],
        audit_status=manifest.audit_status,
        leakage_notes=manifest.leakage_notes,
    )


def _external_seed_tables() -> tuple[
    dict[str, tuple[tuple[str, str, str], ...]],
    dict[str, tuple[tuple[str, str], ...]],
    dict[str, tuple[tuple[str, str], ...]],
    dict[str, tuple[str, ...]],
]:
    try:
        from run_external_eval import PLANTED_FILES, REGRESSIONS, REMOVALS, REPO_TEST_DEPS
    except ImportError as exc:  # pragma: no cover - environment/config failure
        raise RuntimeError("could not load external eval regression tables") from exc
    return dict(REGRESSIONS), dict(REMOVALS), dict(PLANTED_FILES), dict(REPO_TEST_DEPS)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
