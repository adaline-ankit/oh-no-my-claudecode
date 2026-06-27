"""CLI surface for the ``registrydemo`` feature — auto-discovered.

This module follows the auto-discovery convention: it defines a top-level
``register(app)`` callable that the registry (see
:mod:`oh_no_my_claudecode.command_registry`) invokes at CLI build time. The
feature renders its own output inline (no shared rendering hub), so adding it
touched no central file.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

_CONFIRMATION = "registry-demo: self-registered via command auto-discovery"


def register(app: typer.Typer) -> None:
    """Register this feature's commands onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("registry-demo")
    def registry_demo_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the confirmation as JSON."),
        ] = False,
    ) -> None:
        """Proof-of-concept command registered with zero edits to ``cli.py``.

        Demonstrates that a self-contained feature package can add a CLI command
        purely via the auto-discovery hook.
        """
        if as_json:
            typer.echo(json.dumps({"feature": "registrydemo", "message": _CONFIRMATION}))
            return
        typer.echo(_CONFIRMATION)
