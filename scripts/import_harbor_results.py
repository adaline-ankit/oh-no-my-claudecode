#!/usr/bin/env python
"""Import a Harbor result bundle into ONMC trial-result JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from oh_no_my_claudecode.experiment.contracts import ArtifactRef, Condition  # noqa: E402
from oh_no_my_claudecode.experiment.harbor_adapter import (  # noqa: E402
    HarborTrialImport,
    import_harbor_native_trial,
    import_harbor_results,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="Harbor result bundle JSON.")
    parser.add_argument("--experiment-id", required=True, help="ONMC experiment id.")
    parser.add_argument("--out", type=Path, default=None, help="Write normalized JSON here.")
    parser.add_argument(
        "--native-trial",
        action="store_true",
        help="Import a Harbor per-trial result.json instead of an ONMC bundle.",
    )
    parser.add_argument("--condition", choices=[c.value for c in Condition], default=None)
    parser.add_argument("--task-id", default=None, help="Override task id for native trial import.")
    parser.add_argument("--trial", type=int, default=0, help="Trial index for native import.")
    parser.add_argument(
        "--trajectory-file",
        type=Path,
        default=None,
        help="ATIF trajectory artifact file required for native import.",
    )
    parser.add_argument(
        "--verifier-file",
        type=Path,
        default=None,
        help="Verifier artifact file required for native import.",
    )
    args = parser.parse_args(argv)

    raw = json.loads(args.bundle.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Harbor bundle root must be an object")
    imported: tuple[HarborTrialImport, ...]
    if args.native_trial:
        if args.condition is None:
            raise ValueError("--condition is required with --native-trial")
        if args.trajectory_file is None:
            raise ValueError("--trajectory-file is required with --native-trial")
        if args.verifier_file is None:
            raise ValueError("--verifier-file is required with --native-trial")
        imported = (
            import_harbor_native_trial(
                raw,
                experiment_id=args.experiment_id,
                condition=Condition(args.condition),
                task_id=args.task_id,
                trial=args.trial,
                trajectory=_atif_artifact(args.trajectory_file),
                verifier=_artifact(args.verifier_file, "application/json"),
            ),
        )
    else:
        imported = import_harbor_results(raw, experiment_id=args.experiment_id)
    payload = {
        "schema_version": "onmc-harbor-import/v1",
        "experiment_id": args.experiment_id,
        "source_format": "harbor-native-trial" if args.native_trial else "onmc-bundle",
        "trial_count": len(imported),
        "trials": [item.to_dict() for item in imported],
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


def _atif_artifact(path: Path) -> dict[str, object]:
    artifact = _artifact(path, "application/json")
    return {"schema": "atif", "path": str(path), **artifact}


def _artifact(path: Path, media_type: str) -> dict[str, object]:
    data = path.read_bytes()
    ref = ArtifactRef(hashlib.sha256(data).hexdigest(), media_type, len(data))
    return ref.to_dict()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
