"""CLI surface for the ``contract`` feature — auto-discovered.

Defines a top-level ``register(app)`` callable that the registry
(:mod:`oh_no_my_claudecode.command_registry`) invokes at CLI build time, so the
feature ships with **zero edits** to ``cli.py`` or any shared rendering hub. All
output is rendered inline here.

Exposes ``onmc contract init <spec>`` — read a JSON contract spec and write a
failing pytest skeleton plus a ``NotImplementedError`` stub. Idempotent: writing
the same spec twice produces byte-identical files; existing files are not
clobbered unless ``--force`` is given.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from oh_no_my_claudecode.contract.generator import (
    ContractSpecError,
    GeneratedContract,
    generate_contract,
)


def register(app: typer.Typer) -> None:
    """Register the ``contract`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    contract_app = typer.Typer(
        help="Spec-as-contract: generate a failing test + stub from an interface spec.",
        no_args_is_help=True,
    )

    @contract_app.command("init")
    def init(
        spec: Annotated[
            Path,
            typer.Argument(help="Path to the JSON contract spec file."),
        ],
        out: Annotated[
            Path,
            typer.Option("--out", help="Directory the test file is written under."),
        ] = Path("tests"),
        force: Annotated[
            bool,
            typer.Option("--force", help="Overwrite existing test/stub files."),
        ] = False,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit a machine-readable JSON result."),
        ] = False,
    ) -> None:
        """Emit a failing pytest skeleton + a stub module from a contract spec.

        The generated test fails until the stub is implemented — TDD by
        construction. Re-running with the same spec is idempotent.
        """
        try:
            raw = spec.read_text(encoding="utf-8")
        except OSError as exc:
            _fail(f"could not read spec {spec}: {exc}", as_json)

        try:
            generated = generate_contract(raw)
        except ContractSpecError as exc:
            _fail(f"invalid contract spec: {exc}", as_json)

        # The test path's filename is honored under --out; the stub sits beside it.
        test_path = out / Path(generated.test_path).name
        stub_path = out / generated.stub_path

        skipped = _write_artifacts(generated, test_path, stub_path, force=force, as_json=as_json)

        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "feature": "contract",
                        "name": generated.name,
                        "test_path": str(test_path),
                        "stub_path": str(stub_path),
                        "case_count": generated.case_count,
                        "skipped": skipped,
                    }
                )
            )
            return

        verb = "skipped (use --force)" if skipped else "wrote"
        typer.echo(
            f"contract: {verb} {test_path} + {stub_path} "
            f"({generated.case_count} failing case(s) for '{generated.name}')"
        )

    app.add_typer(contract_app, name="contract")


def _write_artifacts(
    generated: GeneratedContract,
    test_path: Path,
    stub_path: Path,
    *,
    force: bool,
    as_json: bool,
) -> bool:
    """Write the test + stub files. Return ``True`` if writing was skipped.

    Skips (without error) when either target already exists and ``force`` is
    False — keeping ``init`` safe to re-run. Idempotent: identical content writes
    are byte-for-byte stable.
    """
    targets = [(test_path, generated.test_source), (stub_path, generated.stub_source)]

    if not force:
        for path, _ in targets:
            if path.exists():
                return True

    try:
        for path, source in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
    except OSError as exc:
        _fail(f"could not write contract artifacts: {exc}", as_json)

    return False


def _fail(message: str, as_json: bool) -> NoReturn:
    """Emit an error (JSON or plain) on stderr and exit non-zero."""
    if as_json:
        typer.echo(json.dumps({"feature": "contract", "error": message}), err=True)
    else:
        typer.echo(f"contract: error: {message}", err=True)
    raise typer.Exit(code=1)
