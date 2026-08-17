"""CLI surface for the ``integrations`` feature — auto-discovered.

Registers ``onmc integrations``: the third-party truth table. ``--probe``
performs real network checks; ``--json`` for machines.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from oh_no_my_claudecode.integrations.matrix import collect_matrix

_MARK = {True: "yes", False: "NO", None: "—"}


def register(app: typer.Typer) -> None:
    @app.command("integrations")
    def integrations(
        probe: Annotated[bool, typer.Option("--probe", help="Run real network probes.")] = False,
        as_json: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    ) -> None:
        """Show every third-party integration: installed / configured / live."""
        rows = collect_matrix(probe=probe)
        if as_json:
            typer.echo(json.dumps([row.to_dict() for row in rows], indent=2))
            return
        width = max(len(row.name) for row in rows)
        typer.echo(f"{'integration':<{width}}  inst  conf  live  detail")
        for row in rows:
            typer.echo(
                f"{row.name:<{width}}  {_MARK[row.installed]:<4}  "
                f"{_MARK[row.configured]:<4}  {_MARK[row.live]:<4}  {row.detail}"
            )
        gaps = [row.name for row in rows if row.configured is False or row.live is False]
        if gaps:
            typer.echo(f"\ngaps: {', '.join(gaps)}")
