#!/usr/bin/env python
"""Import a Harbor result bundle into ONMC trial-result JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from oh_no_my_claudecode.experiment.harbor_adapter import import_harbor_results  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="Harbor result bundle JSON.")
    parser.add_argument("--experiment-id", required=True, help="ONMC experiment id.")
    parser.add_argument("--out", type=Path, default=None, help="Write normalized JSON here.")
    args = parser.parse_args(argv)

    raw = json.loads(args.bundle.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Harbor bundle root must be an object")
    imported = import_harbor_results(raw, experiment_id=args.experiment_id)
    payload = {
        "schema_version": "onmc-harbor-import/v1",
        "experiment_id": args.experiment_id,
        "trial_count": len(imported),
        "trials": [item.to_dict() for item in imported],
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
