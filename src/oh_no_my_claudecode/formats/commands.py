"""CLI surface for the ``formats`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time.

Named ``onmc formats`` rather than ``onmc spec`` because ``spec`` is already a
top-level command group (``onmc spec print`` / ``onmc spec validate`` — the
Agent Memory Format Specification validator in
:mod:`oh_no_my_claudecode.spec.validator`). That command documents and checks
the on-disk memory/task export directory shape; this one documents onmc's
portable interop schemas (receipt, attestation, memory + federation manifest)
derived live from the real dataclasses/models, for OTHER tools/agents to
consume. The two are complementary, not overlapping — this module is purely
additive.

Read-only, deterministic, no network/LLM calls, no filesystem or clock reads:
:func:`~oh_no_my_claudecode.formats.formats.build_spec` only imports Python
types and introspects their fields.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from oh_no_my_claudecode.formats.formats import (
    SCHEMA_NAMES,
    build_spec,
    render_text,
    to_json_dict,
)


def register(app: typer.Typer) -> None:
    """Register the ``formats`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("formats")
    def formats_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the spec as machine-readable JSON."),
        ] = False,
        schema: Annotated[
            str | None,
            typer.Option(
                "--schema",
                help=(
                    "Only emit one schema: 'receipt', 'attestation', or 'memory'. "
                    "Default: all three."
                ),
            ),
        ] = None,
    ) -> None:
        """Emit the spec of onmc's portable, open on-disk schemas.

        Describes the run receipt, the attestation, and the exported memory
        record + federation manifest — the stable JSON shapes onmc writes to
        disk that other tools/agents can read directly. Every field list is
        derived live from the real dataclasses/models (never hand-copied), so
        this can never silently drift from what onmc actually writes.

        Read-only and deterministic: no filesystem, network, or clock reads.
        """
        if schema is not None and schema not in SCHEMA_NAMES:
            valid = ", ".join(SCHEMA_NAMES)
            typer.echo(f"--schema must be one of: {valid} (got {schema!r})", err=True)
            raise typer.Exit(code=1)

        names = (schema,) if schema is not None else SCHEMA_NAMES
        doc = build_spec(names)

        if as_json:
            typer.echo(json.dumps(to_json_dict(doc)))
            return

        typer.echo(render_text(doc), nl=False)
