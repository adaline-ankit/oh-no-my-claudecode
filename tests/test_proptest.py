"""Tests for the ``onmc proptest`` property/invariant test generator.

Covered behaviour:

- A valid invariant spec produces a deterministic, fixed-seed test whose source
  parses (``ast.parse``) and, when executed against a real pure function, the
  generated test actually asserts the property over sampled inputs (it passes
  for a compliant function and fails for a violating one).
- Generation is deterministic / idempotent: the same spec yields byte-identical
  source on repeated calls.
- Malformed specs raise :class:`ProptestSpecError` (bad JSON, missing fields,
  unsupported invariant kind, bad params).
- The ``onmc proptest init`` CLI command writes a file, refuses to clobber
  without ``--force``, and supports ``--json``.

We deliberately never assert on Rich-rendered ``--help`` text (it is unstable
across terminal widths / Rich versions); CLI behaviour is asserted via exit
codes and JSON / file side effects only.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.proptest import (
    GeneratedProptest,
    ProptestSpecError,
    generate_proptest,
)
from oh_no_my_claudecode.proptest.generator import load_spec

runner = CliRunner()


# --- helpers ---------------------------------------------------------------


def _spec(import_path: str, *, name: str = "score", **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": name,
        "import_path": import_path,
        "seed": 4242,
        "samples": 50,
        "invariants": [
            {"kind": "range", "params": {"low": 0, "high": 1}, "description": "in [0,1]"},
            {
                "kind": "no_substring",
                "params": {"needle": "SECRET"},
                "description": "no secret leak",
            },
            {
                "kind": "monotonic",
                "params": {"direction": "increasing"},
                "description": "non-decreasing",
            },
        ],
    }
    base.update(overrides)
    return base


def _write_target(tmp_path: Path, source: str, module_name: str) -> None:
    """Write a target module into tmp_path and make it importable."""
    path = tmp_path / f"{module_name}.py"
    path.write_text(source, encoding="utf-8")
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))


def _load_module_from_source(source: str, module_name: str, tmp_path: Path) -> ModuleType:
    """Compile generated test source into an importable module object."""
    path = tmp_path / f"{module_name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# --- generator: shape & determinism ---------------------------------------


def test_generate_returns_parseable_source() -> None:
    result = generate_proptest(load_spec(json.dumps(_spec("myapp.scoring:score"))))
    assert isinstance(result, GeneratedProptest)
    # Source must parse as valid Python.
    ast.parse(result.test_source)
    assert result.test_path == Path("test_proptest_score.py")
    # Fixed seed must be embedded so failures are reproducible.
    assert "SEED = 4242" in result.test_source
    assert "from myapp.scoring import score as _TARGET" in result.test_source


def test_generation_is_deterministic_idempotent() -> None:
    spec = load_spec(json.dumps(_spec("myapp.scoring:score")))
    first = generate_proptest(spec)
    second = generate_proptest(load_spec(json.dumps(_spec("myapp.scoring:score"))))
    assert first.test_source == second.test_source
    assert first.test_path == second.test_path


# --- generator: the generated test actually asserts the property -----------


def test_generated_test_passes_for_compliant_function(tmp_path: Path) -> None:
    # A compliant pure function over the sampled domain [-1000, 1000]:
    # output in [0,1], monotonic non-decreasing in x, never emits "SECRET".
    _write_target(
        tmp_path,
        "def score(x):\n"
        "    lo, hi = -1000.0, 1000.0\n"
        "    return (max(lo, min(hi, x)) - lo) / (hi - lo)\n",
        "compliant_mod",
    )
    spec = load_spec(json.dumps(_spec("compliant_mod:score")))
    gen = generate_proptest(spec)
    module = _load_module_from_source(gen.test_source, "gen_test_compliant", tmp_path)
    # Every generated test function must pass for a compliant target.
    test_fns = [getattr(module, n) for n in dir(module) if n.startswith("test_")]
    assert test_fns, "generator emitted no test functions"
    for fn in test_fns:
        fn()


def test_generated_range_test_fails_for_violating_function(tmp_path: Path) -> None:
    # Out-of-range function: returns 5.0, violating the [0,1] range invariant.
    _write_target(tmp_path, "def score(x):\n    return 5.0\n", "outofrange_mod")
    single = _spec("outofrange_mod:score")
    single["invariants"] = [
        {"kind": "range", "params": {"low": 0, "high": 1}, "description": "in [0,1]"}
    ]
    gen = generate_proptest(load_spec(json.dumps(single)))
    module = _load_module_from_source(gen.test_source, "gen_test_oor", tmp_path)
    with pytest.raises(AssertionError):
        module.test_invariants_over_samples()


def test_generated_no_substring_test_fails_when_secret_leaks(tmp_path: Path) -> None:
    _write_target(tmp_path, "def emit(x):\n    return 'has SECRET inside'\n", "leak_mod")
    single = _spec("leak_mod:emit")
    single["invariants"] = [
        {"kind": "no_substring", "params": {"needle": "SECRET"}, "description": "no leak"}
    ]
    gen = generate_proptest(load_spec(json.dumps(single)))
    module = _load_module_from_source(gen.test_source, "gen_test_leak", tmp_path)
    with pytest.raises(AssertionError):
        module.test_invariants_over_samples()


def test_generated_monotonic_test_fails_for_decreasing_function(tmp_path: Path) -> None:
    _write_target(tmp_path, "def f(x):\n    return -x\n", "decreasing_mod")
    single = _spec("decreasing_mod:f")
    single["invariants"] = [
        {"kind": "monotonic", "params": {"direction": "increasing"}, "description": "up"}
    ]
    gen = generate_proptest(load_spec(json.dumps(single)))
    module = _load_module_from_source(gen.test_source, "gen_test_mono", tmp_path)
    with pytest.raises(AssertionError):
        module.test_monotonic_0()


# --- generator: bad specs error -------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",
        "[]",
        json.dumps({"import_path": "m:f", "invariants": [{"kind": "range"}]}),  # no name
        json.dumps({"name": "x", "invariants": [{"kind": "range"}]}),  # no import_path
        json.dumps({"name": "x", "import_path": "no-colon", "invariants": []}),  # bad import
        json.dumps({"name": "x", "import_path": "m:f", "invariants": []}),  # empty invariants
        json.dumps(
            {"name": "x", "import_path": "m:f", "invariants": [{"kind": "bogus"}]}
        ),  # bad kind
        json.dumps(
            {
                "name": "x",
                "import_path": "m:f",
                "invariants": [{"kind": "range", "params": {"low": 2, "high": 1}}],
            }
        ),  # high < low
        json.dumps(
            {
                "name": "x",
                "import_path": "m:f",
                "invariants": [{"kind": "no_substring", "params": {"needle": ""}}],
            }
        ),  # empty needle
        json.dumps(
            {
                "name": "x",
                "import_path": "m:f",
                "seed": "nope",
                "invariants": [{"kind": "range"}],
            }
        ),  # bad seed
    ],
)
def test_bad_spec_raises(raw: str) -> None:
    with pytest.raises(ProptestSpecError):
        load_spec(raw)


# --- CLI -------------------------------------------------------------------


def _write_spec_file(tmp_path: Path, spec: dict[str, object]) -> Path:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def test_cli_init_writes_file(tmp_path: Path) -> None:
    spec_path = _write_spec_file(tmp_path, _spec("myapp.scoring:score"))
    out_dir = tmp_path / "out"
    result = runner.invoke(app, ["proptest", "init", str(spec_path), "--out", str(out_dir)])
    assert result.exit_code == 0, result.stdout
    written = out_dir / "test_proptest_score.py"
    assert written.exists()
    ast.parse(written.read_text(encoding="utf-8"))


def test_cli_init_json(tmp_path: Path) -> None:
    spec_path = _write_spec_file(tmp_path, _spec("myapp.scoring:score"))
    out_dir = tmp_path / "out"
    result = runner.invoke(
        app, ["proptest", "init", str(spec_path), "--out", str(out_dir), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["feature"] == "proptest"
    assert payload["name"] == "score"
    assert payload["seed"] == 4242
    assert set(payload["invariants"]) == {"range", "no_substring", "monotonic"}
    assert payload["path"].endswith("test_proptest_score.py")


def test_cli_init_refuses_overwrite_without_force(tmp_path: Path) -> None:
    spec_path = _write_spec_file(tmp_path, _spec("myapp.scoring:score"))
    out_dir = tmp_path / "out"
    first = runner.invoke(app, ["proptest", "init", str(spec_path), "--out", str(out_dir)])
    assert first.exit_code == 0
    second = runner.invoke(app, ["proptest", "init", str(spec_path), "--out", str(out_dir)])
    assert second.exit_code == 1
    forced = runner.invoke(
        app, ["proptest", "init", str(spec_path), "--out", str(out_dir), "--force"]
    )
    assert forced.exit_code == 0


def test_cli_init_missing_spec_errors(tmp_path: Path) -> None:
    result = runner.invoke(app, ["proptest", "init", str(tmp_path / "nope.json")])
    assert result.exit_code == 1


def test_cli_init_bad_spec_json_error_is_clean(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text("{not json", encoding="utf-8")
    result = runner.invoke(
        app, ["proptest", "init", str(spec_path), "--out", str(tmp_path), "--json"]
    )
    assert result.exit_code == 1
