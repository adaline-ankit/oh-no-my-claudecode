"""CLI surface for the ``sbom`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc sbom`` ships with **zero edits**
to ``cli.py`` or any other shared hub.

``onmc sbom`` generates a CycloneDX 1.5 JSON SBOM of the project's
dependencies. Output goes to stdout or a file (``--out``). By default the raw
CycloneDX JSON is emitted; ``--json`` wraps it in an onmc envelope for
pipeline composition.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.sbom.core import build_sbom


def register(app: typer.Typer) -> None:
    """Register the ``onmc sbom`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("sbom")
    def sbom_command(
        out: Annotated[
            Path | None,
            typer.Option(
                "--out",
                help="Write the SBOM to FILE instead of stdout.",
                metavar="FILE",
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option(
                "--json",
                help=(
                    "Wrap the CycloneDX document in an onmc JSON envelope "
                    "{\"kind\": \"sbom\", \"sbom\": {...}} for pipeline composition."
                ),
            ),
        ] = False,
    ) -> None:
        """Generate a CycloneDX 1.5 SBOM of this project's dependencies.

        Reads ``uv.lock`` (preferred, fully pinned) or falls back to
        ``pyproject.toml`` when no lockfile is present.  Output is
        deterministic: components are sorted alphabetically by name.

        Pure stdlib — no network calls, no new dependencies.

        Examples:

            onmc sbom                       # print to stdout

            onmc sbom --out sbom.json       # write to file

            onmc sbom --json                # onmc envelope (pipeline-friendly)
        """
        try:
            repo_root = discover_repo_root(Path.cwd())
        except RepoDiscoveryError:
            typer.echo("error: no git repository found from the current directory.", err=True)
            raise typer.Exit(code=1) from None

        sbom = build_sbom(repo_root)

        if as_json:
            payload = json.dumps({"kind": "sbom", "sbom": sbom}, indent=2, sort_keys=True)
        else:
            payload = json.dumps(sbom, indent=2, sort_keys=True)

        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(payload, encoding="utf-8")
            typer.echo(f"SBOM written to {out}", err=True)
        else:
            typer.echo(payload)
