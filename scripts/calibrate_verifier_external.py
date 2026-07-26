#!/usr/bin/env python
"""Render the frozen external verifier calibration report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from oh_no_my_claudecode.verifier.calibration import (  # noqa: E402
    DEFAULT_EXTERNAL_CORPUS_PATH,
    calibrate_external_corpus,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_EXTERNAL_CORPUS_PATH)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--require-claim-ready",
        action="store_true",
        help="return exit 2 when the confidence-bound publication gate is not met",
    )
    args = parser.parse_args(argv)

    report = calibrate_external_corpus(args.corpus)
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 2 if args.require_claim_ready and not report.claim_ready else 0


if __name__ == "__main__":
    raise SystemExit(main())
