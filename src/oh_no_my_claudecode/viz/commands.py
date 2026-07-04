"""CLI surface for the ``viz`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc viz`` ships with **zero edits**
to ``cli.py`` or any other shared hub. Rendering is done inline here.

``onmc viz memory`` prints a diagram of the memory relationship graph;
``onmc viz code [<target>]`` prints a diagram of the code-graph blast radius.
Both emit plain diagram text (Mermaid ``graph TD`` by default, or D2 when
``--format d2`` is passed) — no server, no dependency. Distinct from the live
``onmc missioncontrol`` dashboard.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.viz.d2 import code_d2, memory_d2
from oh_no_my_claudecode.viz.mermaid import (
    DEFAULT_MEMORY_LIMIT,
    code_mermaid,
    memory_mermaid,
)

viz_app = typer.Typer(
    help="Render onmc graphs as shareable diagrams (Mermaid or D2, no server, no dep).",
    no_args_is_help=True,
)


class DiagramFormat(StrEnum):
    """Supported output diagram formats."""

    MERMAID = "mermaid"
    D2 = "d2"


def register(app: typer.Typer) -> None:
    """Register the ``onmc viz`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(viz_app, name="viz")


@viz_app.command("memory")
def viz_memory_command(
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            help="Maximum number of memory nodes to render (most recent first).",
        ),
    ] = DEFAULT_MEMORY_LIMIT,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Wrap the diagram text in a JSON envelope."),
    ] = False,
    fmt: Annotated[
        DiagramFormat,
        typer.Option(
            "--format",
            help="Output diagram format: mermaid (default) or d2.",
        ),
    ] = DiagramFormat.MERMAID,
) -> None:
    """Print the memory relationship graph as a diagram.

    Nodes are memory entries grouped by kind; edges are the recorded
    ``memory_edges`` relationships (supersedes / contradicts / relates /
    duplicate_of). Use ``--format d2`` for D2 (terrastruct.com/d2) output
    instead of the default Mermaid ``graph TD``. Deterministic and offline.
    """
    service = OnmcService(Path.cwd())
    try:
        _repo_root, _config, storage = service._load_context()
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if fmt == DiagramFormat.D2:
        diagram = memory_d2(storage, limit=limit)
        if as_json:
            typer.echo(
                json.dumps(
                    {"kind": "memory", "format": "d2", "d2": diagram},
                    indent=2,
                    sort_keys=True,
                )
            )
            return
    else:
        diagram = memory_mermaid(storage, limit=limit)
        if as_json:
            typer.echo(
                json.dumps(
                    {"kind": "memory", "mermaid": diagram},
                    indent=2,
                    sort_keys=True,
                )
            )
            return
    typer.echo(diagram)


@viz_app.command("code")
def viz_code_command(
    target: Annotated[
        str,
        typer.Argument(
            help="Repo-relative file path or bare symbol name to graph the blast radius of.",
        ),
    ],
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Wrap the diagram text in a JSON envelope."),
    ] = False,
    fmt: Annotated[
        DiagramFormat,
        typer.Option(
            "--format",
            help="Output diagram format: mermaid (default) or d2.",
        ),
    ] = DiagramFormat.MERMAID,
) -> None:
    """Print the code-graph blast radius of *target* as a diagram.

    The target file(s) sit in the centre; importers/dependents flow in, the
    target's own imports flow out, and related tests are shown as a group.
    Use ``--format d2`` for D2 (terrastruct.com/d2) output instead of the
    default Mermaid ``graph TD``. Deterministic and offline.
    """
    service = OnmcService(Path.cwd())
    try:
        repo_root, _config, _storage = service._load_context()
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if fmt == DiagramFormat.D2:
        diagram = code_d2(repo_root, target)
        if as_json:
            typer.echo(
                json.dumps(
                    {"kind": "code", "format": "d2", "target": target, "d2": diagram},
                    indent=2,
                    sort_keys=True,
                )
            )
            return
    else:
        diagram = code_mermaid(repo_root, target)
        if as_json:
            typer.echo(
                json.dumps(
                    {"kind": "code", "target": target, "mermaid": diagram},
                    indent=2,
                    sort_keys=True,
                )
            )
            return
    typer.echo(diagram)
