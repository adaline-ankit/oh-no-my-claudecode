from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "docs" / "cli-reference.md"

COMMANDS: list[tuple[str, list[str]]] = [
    ("onmc", []),
    ("onmc setup", ["setup"]),
    ("onmc init", ["init"]),
    ("onmc ingest", ["ingest"]),
    ("onmc brief", ["brief"]),
    ("onmc status", ["status"]),
    ("onmc sync", ["sync"]),
    ("onmc serve", ["serve"]),
    ("onmc solve", ["solve"]),
    ("onmc review", ["review"]),
    ("onmc teach", ["teach"]),
    ("onmc mine", ["mine"]),
    ("onmc doctor", ["doctor"]),
    ("onmc llm", ["llm"]),
    ("onmc llm status", ["llm", "status"]),
    ("onmc llm configure", ["llm", "configure"]),
    ("onmc hooks", ["hooks"]),
    ("onmc hooks install", ["hooks", "install"]),
    ("onmc hooks uninstall", ["hooks", "uninstall"]),
    ("onmc hooks status", ["hooks", "status"]),
    ("onmc hooks pre-compact", ["hooks", "pre-compact"]),
    ("onmc hooks session-start", ["hooks", "session-start"]),
    ("onmc claude-md", ["claude-md"]),
    ("onmc claude-md generate", ["claude-md", "generate"]),
    ("onmc claude-md update", ["claude-md", "update"]),
    ("onmc claude-md preview", ["claude-md", "preview"]),
    ("onmc memory", ["memory"]),
    ("onmc memory list", ["memory", "list"]),
    ("onmc memory add", ["memory", "add"]),
    ("onmc memory show", ["memory", "show"]),
    ("onmc memory confirm", ["memory", "confirm"]),
    ("onmc memory reject", ["memory", "reject"]),
    ("onmc memory edit", ["memory", "edit"]),
    ("onmc task", ["task"]),
    ("onmc task start", ["task", "start"]),
    ("onmc task list", ["task", "list"]),
    ("onmc task show", ["task", "show"]),
    ("onmc task end", ["task", "end"]),
    ("onmc task status", ["task", "status"]),
    ("onmc attempt", ["attempt"]),
    ("onmc attempt add", ["attempt", "add"]),
    ("onmc attempt list", ["attempt", "list"]),
    ("onmc attempt show", ["attempt", "show"]),
    ("onmc attempt update", ["attempt", "update"]),
]


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _clean_help(text: str) -> str:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return text.strip()


def _help_for(args: list[str]) -> str:
    result = _runner().invoke(
        app,
        [*args, "--help"],
        color=False,
        prog_name="onmc",
        terminal_width=80,
    )
    if result.exit_code != 0:
        message = result.stderr or result.stdout
        raise RuntimeError(f"failed to render help for {' '.join(args) or 'onmc'}:\n{message}")
    return _clean_help(result.stdout)


def render_reference() -> str:
    lines = [
        "# CLI Reference",
        "",
        "This file is generated from Typer help output.",
        "Run `python scripts/generate-cli-reference.py` after changing CLI commands.",
        "",
    ]
    for title, args in COMMANDS:
        lines.extend(
            [
                f"## `{title}`",
                "",
                "```text",
                _help_for(args),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if docs/cli-reference.md is stale.",
    )
    args = parser.parse_args()

    rendered = render_reference()
    if args.check:
        existing = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if existing != rendered:
            diff = difflib.unified_diff(
                existing.splitlines(),
                rendered.splitlines(),
                fromfile=str(OUTPUT_PATH),
                tofile="generated",
                lineterm="",
            )
            sys.stderr.write("\n".join(diff) + "\n")
            return 1
        return 0

    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
