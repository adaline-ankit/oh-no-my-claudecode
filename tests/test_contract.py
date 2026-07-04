"""Tests for the ``onmc contract`` spec-as-contract generator.

Coverage
--------
- :func:`generate_contract` turns a 3-case spec into a test module with exactly
  three asserting tests and a stub raising ``NotImplementedError`` — both
  artifacts parse as valid Python (verified via :mod:`ast`).
- Generation is deterministic (same spec → byte-identical output).
- Malformed specs raise :class:`ContractSpecError`.
- The ``onmc contract init`` CLI writes both files, is idempotent (re-running
  without ``--force`` skips), respects ``--force`` (overwrites), and supports a
  machine-readable ``--json`` mode. Bad specs exit non-zero.

No Rich ``--help`` text is asserted — the CLI is exercised purely via flags and
the JSON / exit-code / file-content outcomes.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from oh_no_my_claudecode.contract import (
    ContractSpecError,
    GeneratedContract,
    generate_contract,
)
from oh_no_my_claudecode.contract.commands import register

runner = CliRunner()

_THREE_CASE_SPEC = json.dumps(
    {
        "name": "add",
        "summary": "Add two integers.",
        "signature": "add(a, b)",
        "cases": [
            {"given": [1, 2], "expect": 3},
            {"given": [0, 0], "expect": 0},
            {"given": [-1, 1], "expect": 0},
        ],
    }
)


def _count_asserts(source: str) -> int:
    """Return the number of ``assert`` statements in *source* (parsed via ast)."""
    return sum(isinstance(node, ast.Assert) for node in ast.walk(ast.parse(source)))


def _count_test_funcs(source: str) -> int:
    """Return the number of top-level ``test_*`` functions in *source*."""
    return sum(
        isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        for node in ast.walk(ast.parse(source))
    )


# --------------------------------------------------------------------------- #
# generate_contract — pure generation
# --------------------------------------------------------------------------- #


def test_three_case_spec_emits_three_parseable_asserts() -> None:
    """A 3-case spec yields a test module with three asserting tests that parse."""
    generated = generate_contract(_THREE_CASE_SPEC)

    assert isinstance(generated, GeneratedContract)
    assert generated.name == "add"
    assert generated.case_count == 3

    # The generated test source must be valid Python with one assert per case.
    ast.parse(generated.test_source)  # raises SyntaxError if not parseable
    assert _count_asserts(generated.test_source) == 3
    assert _count_test_funcs(generated.test_source) == 3


def test_stub_parses_and_raises_not_implemented() -> None:
    """The stub is valid Python and its function raises ``NotImplementedError``."""
    generated = generate_contract(_THREE_CASE_SPEC)

    module = ast.parse(generated.stub_source)  # raises if not parseable
    func_names = {n.name for n in ast.walk(module) if isinstance(n, ast.FunctionDef)}
    assert "add" in func_names

    namespace: dict[str, object] = {}
    exec(compile(module, generated.stub_path, "exec"), namespace)  # noqa: S102 - test-only
    with pytest.raises(NotImplementedError):
        namespace["add"](1, 2)  # type: ignore[operator]


def test_generation_is_deterministic() -> None:
    """The same spec always produces byte-identical output."""
    first = generate_contract(_THREE_CASE_SPEC)
    second = generate_contract(_THREE_CASE_SPEC)
    assert first == second


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        "[]",  # top level not an object
        json.dumps({"name": "add"}),  # missing cases
        json.dumps({"name": "add", "cases": []}),  # empty cases
        json.dumps({"name": "1bad", "cases": [{"given": [], "expect": 1}]}),  # bad ident
        json.dumps({"name": "class", "cases": [{"given": [], "expect": 1}]}),  # keyword
        json.dumps({"name": "add", "cases": [{"given": [1]}]}),  # case missing expect
        json.dumps({"name": "add", "cases": [{"expect": 1}]}),  # case missing given
    ],
)
def test_malformed_specs_raise(raw: str) -> None:
    """Malformed specs raise ``ContractSpecError``."""
    with pytest.raises(ContractSpecError):
        generate_contract(raw)


# --------------------------------------------------------------------------- #
# onmc contract init — CLI
# --------------------------------------------------------------------------- #


def _cli_app() -> typer.Typer:
    """A fresh Typer app with the ``contract`` group registered + a sentinel.

    Typer collapses a single-command app into a bare CLI; the sentinel keeps
    ``contract`` reachable as a proper subcommand in tests.
    """
    app = typer.Typer()

    @app.command("__sentinel__")
    def _sentinel() -> None:  # pragma: no cover - never invoked
        ...

    register(app)
    return app


def test_init_writes_test_and_stub(tmp_path: Path) -> None:
    """``contract init`` writes a parseable test + stub under ``--out``."""
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(_THREE_CASE_SPEC, encoding="utf-8")
    out = tmp_path / "tests"

    result = runner.invoke(
        _cli_app(),
        ["contract", "init", str(spec_file), "--out", str(out)],
    )

    assert result.exit_code == 0, result.output
    test_file = out / "test_add.py"
    stub_file = out / "add.py"
    assert test_file.exists()
    assert stub_file.exists()
    assert _count_asserts(test_file.read_text(encoding="utf-8")) == 3
    ast.parse(stub_file.read_text(encoding="utf-8"))


def test_init_is_idempotent_without_force(tmp_path: Path) -> None:
    """Re-running without ``--force`` skips and does not clobber existing files."""
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(_THREE_CASE_SPEC, encoding="utf-8")
    out = tmp_path / "tests"

    first = runner.invoke(_cli_app(), ["contract", "init", str(spec_file), "--out", str(out)])
    assert first.exit_code == 0, first.output

    test_file = out / "test_add.py"
    sentinel = "# manually edited - must be preserved\n"
    test_file.write_text(test_file.read_text(encoding="utf-8") + sentinel, encoding="utf-8")

    second = runner.invoke(_cli_app(), ["contract", "init", str(spec_file), "--out", str(out)])
    assert second.exit_code == 0, second.output
    # Skipped: our manual edit survives.
    assert test_file.read_text(encoding="utf-8").endswith(sentinel)


def test_init_force_overwrites(tmp_path: Path) -> None:
    """``--force`` regenerates files byte-identically (deterministic overwrite)."""
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(_THREE_CASE_SPEC, encoding="utf-8")
    out = tmp_path / "tests"

    runner.invoke(_cli_app(), ["contract", "init", str(spec_file), "--out", str(out)])
    test_file = out / "test_add.py"
    pristine = test_file.read_text(encoding="utf-8")
    test_file.write_text("clobbered\n", encoding="utf-8")

    result = runner.invoke(
        _cli_app(),
        ["contract", "init", str(spec_file), "--out", str(out), "--force"],
    )
    assert result.exit_code == 0, result.output
    assert test_file.read_text(encoding="utf-8") == pristine


def test_init_json_output(tmp_path: Path) -> None:
    """``--json`` emits a machine-readable result with the expected fields."""
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(_THREE_CASE_SPEC, encoding="utf-8")
    out = tmp_path / "tests"

    result = runner.invoke(
        _cli_app(),
        ["contract", "init", str(spec_file), "--out", str(out), "--json"],
    )
    assert result.exit_code == 0, result.output

    payload = json.loads(result.stdout)
    assert payload["feature"] == "contract"
    assert payload["name"] == "add"
    assert payload["case_count"] == 3
    assert payload["skipped"] is False


def test_init_bad_spec_exits_nonzero(tmp_path: Path) -> None:
    """An invalid spec exits non-zero rather than writing partial artifacts."""
    spec_file = tmp_path / "spec.json"
    spec_file.write_text("definitely not json", encoding="utf-8")
    out = tmp_path / "tests"

    result = runner.invoke(
        _cli_app(),
        ["contract", "init", str(spec_file), "--out", str(out)],
    )
    assert result.exit_code != 0
    assert not (out / "test_add.py").exists()
