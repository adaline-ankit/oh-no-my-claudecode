#!/usr/bin/env python3
"""Validate an ONMC portfolio manifest without launching benchmark cells."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from oh_no_my_claudecode.experiment.publication import (  # noqa: E402
    validate_benchmark_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--require-publication-ready",
        action="store_true",
        help="Exit 2 when structural validation passes but U14 publication gates do not.",
    )
    args = parser.parse_args(argv)

    raw = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manifest JSON root must be an object")
    validation = validate_benchmark_manifest(raw)
    payload = validation.to_dict()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not validation.structurally_valid:
        return 1
    if args.require_publication_ready and not validation.publication_ready:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
