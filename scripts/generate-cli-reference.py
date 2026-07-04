from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path
from typing import Any

import typer.main
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "docs" / "cli-reference.md"

# NOTE (the win): there is deliberately NO hardcoded COMMANDS list here.
#
# Commands are auto-discovered from the fully-built Typer ``app`` (see
# ``discover_commands`` below). The ``app`` is built once at import time and
# already has every self-registering feature wired in via
# ``command_registry.register_feature_commands``. A new feature that ships its
# own ``oh_no_my_claudecode/<feat>/commands.py`` therefore appears in this
# reference automatically — WITHOUT editing this generator. This kills the last
# shared-hub file that forced every parallel feature PR to touch one list.


def discover_commands(root_app: typer.Typer) -> list[tuple[str, list[str]]]:
    """Enumerate every command + nested subcommand from a built Typer app.

    Returns a deterministic, sorted list of ``(title, args)`` pairs where
    ``title`` is the human-facing invocation (e.g. ``"onmc swarm plan"``) and
    ``args`` is the argument path to pass to the CLI (e.g. ``["swarm", "plan"]``).
    The root program itself is always emitted first as ``("onmc", [])``.

    Both group nodes (e.g. ``onmc swarm``) and their leaf subcommands
    (e.g. ``onmc swarm plan``) are emitted, matching the previous hand-written
    listing. Sub-groups are recursed into so arbitrarily nested commands are
    covered. Children are walked in sorted order for stable output.
    """
    command: Any = typer.main.get_command(root_app)
    discovered: list[tuple[str, list[str]]] = [("onmc", [])]

    def walk(node: Any, path: list[str]) -> None:
        # A click/typer Group exposes its children via ``.commands``; leaf
        # commands either lack the attribute or expose an empty mapping. We
        # avoid an ``isinstance(node, click.Group)`` check because Typer's
        # group class is not always a ``click.Group`` subclass across versions.
        subcommands = getattr(node, "commands", None)
        if not subcommands:
            return
        for name in sorted(subcommands):
            child_path = [*path, name]
            discovered.append((f"onmc {' '.join(child_path)}", child_path))
            walk(subcommands[name], child_path)

    walk(command, [])
    return discovered


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _clean_help(text: str) -> str:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


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
    for title, args in discover_commands(app):
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
