#!/usr/bin/env python3
"""Fail closed when proposed benchmark language outruns its evidence bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from oh_no_my_claudecode.experiment.claim import (  # noqa: E402
    ClaimLanguageDecision,
    gate_claim_language,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--claim", required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    raw = json.loads(args.bundle.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("publication bundle JSON root must be an object")
    readiness = raw.get("claim_readiness")
    coverage = raw.get("report_coverage")
    if not isinstance(readiness, dict) or not isinstance(coverage, dict):
        raise ValueError("bundle must contain claim_readiness and report_coverage objects")
    decision = gate_claim_language(
        args.claim,
        readiness,
        report_coverage=coverage,
    )
    rendered = json.dumps(decision.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if decision.decision is ClaimLanguageDecision.ALLOW else 2


if __name__ == "__main__":
    raise SystemExit(main())
