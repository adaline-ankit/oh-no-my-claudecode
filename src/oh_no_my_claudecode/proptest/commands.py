"""CLI surface for the ``proptest`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): a top-level ``register(app)``
callable wires the feature's commands onto the root ``onmc`` app with **zero**
edits to ``cli.py`` / ``core`` / the rendering hub. The feature renders its own
output inline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from oh_no_my_claudecode.proptest.generator import (
    GeneratedProptest,
    ProptestSpecError,
    generate_proptest,
    load_spec,
)


def register(app: typer.Typer) -> None:
    """Register the ``proptest`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    proptest_app = typer.Typer(
        name="proptest",
        help="Generate property/invariant tests for pure functions.",
        no_args_is_help=True,
    )

    @proptest_app.command("init")
    def init_command(
        spec: Annotated[
            Path,
            typer.Argument(help="Path to the invariant spec JSON file."),
        ],
        out: Annotated[
            Path,
            typer.Option("--out", help="Directory to write the generated test into."),
        ] = Path("tests"),
        force: Annotated[
            bool,
            typer.Option("--force", help="Overwrite an existing test file."),
        ] = False,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit a JSON result instead of human text."),
        ] = False,
    ) -> None:
        """Generate a fixed-seed property test from an invariant SPEC.

        The spec is a JSON file describing a pure function (``import_path``) and
        the invariants it must satisfy (``range`` / ``no_substring`` /
        ``monotonic``). The generated test samples inputs with a fixed seed so
        runs are deterministic and reproducible.
        """
        if not spec.exists():
            _fail(f"spec file not found: {spec}", as_json)

        try:
            raw = spec.read_text(encoding="utf-8")
        except OSError as exc:
            _fail(f"could not read spec file {spec}: {exc}", as_json)

        try:
            normalized = load_spec(raw)
            generated: GeneratedProptest = generate_proptest(normalized)
        except ProptestSpecError as exc:
            _fail(str(exc), as_json)

        dest = out / generated.test_path
        if dest.exists() and not force:
            _fail(
                f"refusing to overwrite existing file {dest} (use --force)",
                as_json,
            )

        out.mkdir(parents=True, exist_ok=True)
        dest.write_text(generated.test_source, encoding="utf-8")

        invariant_kinds = [inv["kind"] for inv in normalized["invariants"]]
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "feature": "proptest",
                        "name": generated.name,
                        "path": str(dest),
                        "import_path": normalized["import_path"],
                        "seed": normalized["seed"],
                        "samples": normalized["samples"],
                        "invariants": invariant_kinds,
                    }
                )
            )
            return
        typer.echo(f"proptest: wrote {dest}")
        typer.echo(
            f"  target={normalized['import_path']} seed={normalized['seed']} "
            f"samples={normalized['samples']}"
        )
        typer.echo(f"  invariants: {', '.join(invariant_kinds)}")

    app.add_typer(proptest_app, name="proptest")


def _fail(message: str, as_json: bool) -> NoReturn:
    """Emit an error (JSON or text) and exit non-zero without a traceback."""
    if as_json:
        typer.echo(json.dumps({"feature": "proptest", "error": message}), err=True)
    else:
        typer.echo(f"proptest: error: {message}", err=True)
    raise typer.Exit(code=1)
