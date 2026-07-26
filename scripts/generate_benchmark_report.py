#!/usr/bin/env python3
"""Generate deterministic ONMC benchmark evidence and raw-artifact indexes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from oh_no_my_claudecode.experiment.publication import (  # noqa: E402
    build_publication_bundle,
    build_publication_work_plan,
    render_publication_markdown,
)

_DEFAULT_CLAIM = (
    "ONMC improves coding-agent quality and lowers cost versus plain coding agents."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, default=None)
    parser.add_argument("--claim", default=_DEFAULT_CLAIM)
    parser.add_argument("--product-smoke", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--markdown-out", type=Path, default=None)
    parser.add_argument("--artifact-index-out", type=Path, default=None)
    parser.add_argument("--work-plan-out", type=Path, default=None)
    parser.add_argument(
        "--require-publication-ready",
        action="store_true",
        help="Exit 2 when the generated evidence does not satisfy every publication gate.",
    )
    args = parser.parse_args(argv)

    report = _load_object(args.report, "report")
    manifest = _load_object(args.manifest, "manifest")
    product_smoke = (
        _load_object(args.product_smoke, "product smoke")
        if args.product_smoke is not None
        else None
    )
    bundle = build_publication_bundle(
        report,
        manifest,
        proposed_claim=args.claim,
        artifact_root=args.report.parent if args.artifact_root is None else args.artifact_root,
        product_surface=_live_product_surface(),
        product_smoke=product_smoke,
    )
    rendered_json = json.dumps(bundle, indent=2, sort_keys=True) + "\n"
    rendered_markdown = render_publication_markdown(bundle)

    _write(args.json_out, rendered_json)
    _write(args.markdown_out, rendered_markdown)
    if args.artifact_index_out is not None:
        artifact_index = bundle["raw_artifact_index"]
        _write(
            args.artifact_index_out,
            json.dumps(artifact_index, indent=2, sort_keys=True) + "\n",
        )
    if args.work_plan_out is not None:
        work_plan = build_publication_work_plan(bundle)
        _write(
            args.work_plan_out,
            json.dumps(work_plan, indent=2, sort_keys=True) + "\n",
        )
    if args.json_out is None and args.markdown_out is None:
        print(rendered_json, end="")
    if args.require_publication_ready and bundle["publication_ready"] is not True:
        return 2
    return 0


def _load_object(path: Path, label: str) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} JSON root must be an object")
    return value


def _write(path: Path | None, content: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _live_product_surface() -> dict[str, object]:
    """Collect the live root-help surface for publication evidence.

    This keeps product coherence in the same evidence bundle as benchmark rigor:
    a report can no longer look publication-ready while the CLI has drifted back
    into a broad command catalog.
    """
    from oh_no_my_claudecode.cli import app
    from oh_no_my_claudecode.command_registry import _command_name, _registered_names
    from oh_no_my_claudecode.commands_help.core import audit_command_surface

    visible: list[str] = []
    for raw_info in (*app.registered_commands, *app.registered_groups):
        callback = getattr(raw_info, "callback", None)
        raw_name = getattr(raw_info, "name", None)
        name = _command_name(raw_name, callback)
        if name is not None and not getattr(raw_info, "hidden", False):
            visible.append(name)
    return audit_command_surface(
        sorted(set(_registered_names(app))),
        sorted(set(visible)),
    ).to_dict()


if __name__ == "__main__":
    raise SystemExit(main())
