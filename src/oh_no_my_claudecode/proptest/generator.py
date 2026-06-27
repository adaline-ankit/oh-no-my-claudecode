"""Pure generation logic for ``onmc proptest``.

Given an invariant *spec* describing a pure function and the properties it must
satisfy, :func:`generate_proptest` returns a :class:`GeneratedProptest` holding
the destination path and the source of a deterministic, fixed-seed sampling
test. The function is pure: identical input always yields identical output (no
clocks, no randomness, no filesystem access).

Spec shape (JSON)
-----------------
::

    {
      "name": "score",                       # logical name for the test
      "import_path": "myapp.scoring:score",  # module:attr of the function
      "seed": 1234,                          # optional, default 1337
      "samples": 500,                        # optional, default 200
      "invariants": [
        {"kind": "range", "params": {"low": 0, "high": 1},
         "description": "score stays in [0, 1]"},
        {"kind": "no_substring", "params": {"needle": "PASSWORD"},
         "description": "secret never leaks into output"},
        {"kind": "monotonic", "params": {"direction": "increasing"},
         "description": "output is non-decreasing in its input"}
      ]
    }

Supported invariant kinds
-------------------------
``range``
    ``low <= f(x) <= high`` for numeric outputs.
``no_substring``
    ``needle not in str(f(x))`` — useful for secret-leak / redaction checks.
``monotonic``
    For a sorted sequence of numeric inputs, ``f`` is non-decreasing
    (``increasing``) or non-increasing (``decreasing``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_SEED = 1337
DEFAULT_SAMPLES = 200
_VALID_KINDS = ("range", "no_substring", "monotonic")


class ProptestSpecError(ValueError):
    """Raised when an invariant spec is malformed or unsupported."""


@dataclass(frozen=True)
class GeneratedProptest:
    """Result of generating a property test.

    Attributes
    ----------
    test_path:
        Relative path (under the chosen output dir) where the test should be
        written, e.g. ``tests/test_proptest_score.py``.
    test_source:
        The full Python source of the generated test module.
    name:
        The sanitized logical name used in the filename and test ids.
    """

    test_path: Path
    test_source: str
    name: str


def _sanitize(name: str) -> str:
    """Turn an arbitrary spec name into a safe python identifier fragment."""
    cleaned = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in name.strip())
    cleaned = cleaned.strip("_")
    if not cleaned:
        raise ProptestSpecError("spec 'name' must contain at least one alphanumeric character")
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def load_spec(raw: str) -> dict[str, Any]:
    """Parse and validate the raw JSON spec text into a normalized dict.

    Raises :class:`ProptestSpecError` on any structural problem so the CLI can
    surface a clean, non-traceback error.
    """
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProptestSpecError(f"spec is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProptestSpecError("spec must be a JSON object")

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ProptestSpecError("spec 'name' is required and must be a non-empty string")

    import_path = data.get("import_path")
    if not isinstance(import_path, str) or ":" not in import_path:
        raise ProptestSpecError(
            "spec 'import_path' is required and must look like 'module.sub:function'"
        )
    module, _, attr = import_path.partition(":")
    if not module.strip() or not attr.strip():
        raise ProptestSpecError("spec 'import_path' must have both a module and an attribute")

    invariants = data.get("invariants")
    if not isinstance(invariants, list) or not invariants:
        raise ProptestSpecError("spec 'invariants' must be a non-empty list")

    normalized: list[dict[str, Any]] = []
    for idx, inv in enumerate(invariants):
        if not isinstance(inv, dict):
            raise ProptestSpecError(f"invariant #{idx} must be an object")
        kind = inv.get("kind")
        if kind not in _VALID_KINDS:
            raise ProptestSpecError(
                f"invariant #{idx} has unsupported kind {kind!r}; "
                f"supported: {', '.join(_VALID_KINDS)}"
            )
        params = inv.get("params", {})
        if not isinstance(params, dict):
            raise ProptestSpecError(f"invariant #{idx} 'params' must be an object")
        description = inv.get("description")
        if description is not None and not isinstance(description, str):
            raise ProptestSpecError(f"invariant #{idx} 'description' must be a string")
        normalized.append(
            {
                "kind": kind,
                "params": _validate_params(idx, kind, params),
                "description": description or f"{kind} invariant",
            }
        )

    seed = data.get("seed", DEFAULT_SEED)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ProptestSpecError("spec 'seed' must be an integer")
    samples = data.get("samples", DEFAULT_SAMPLES)
    if not isinstance(samples, int) or isinstance(samples, bool) or samples < 1:
        raise ProptestSpecError("spec 'samples' must be a positive integer")

    return {
        "name": name,
        "module": module,
        "attr": attr,
        "import_path": import_path,
        "seed": seed,
        "samples": samples,
        "invariants": normalized,
    }


def _validate_params(idx: int, kind: str, params: dict[str, Any]) -> dict[str, Any]:
    """Validate per-kind params and return a normalized copy."""
    if kind == "range":
        low = params.get("low", 0)
        high = params.get("high", 1)
        if not _is_number(low) or not _is_number(high):
            raise ProptestSpecError(f"invariant #{idx} range 'low'/'high' must be numbers")
        if high < low:
            raise ProptestSpecError(f"invariant #{idx} range 'high' must be >= 'low'")
        return {"low": low, "high": high}
    if kind == "no_substring":
        needle = params.get("needle")
        if not isinstance(needle, str) or needle == "":
            raise ProptestSpecError(
                f"invariant #{idx} no_substring requires a non-empty string 'needle'"
            )
        return {"needle": needle}
    # monotonic
    direction = params.get("direction", "increasing")
    if direction not in ("increasing", "decreasing"):
        raise ProptestSpecError(
            f"invariant #{idx} monotonic 'direction' must be 'increasing' or 'decreasing'"
        )
    return {"direction": direction}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# --- source emission -------------------------------------------------------


def _emit_assertions(invariants: list[dict[str, Any]]) -> str:
    """Render the per-sample assertion block as source lines."""
    lines: list[str] = []
    for inv in invariants:
        kind = inv["kind"]
        params = inv["params"]
        desc = inv["description"]
        if kind == "range":
            lines.append(
                f"        # invariant: {desc}\n"
                f"        result = _TARGET(x)\n"
                f"        assert {params['low']!r} <= result <= {params['high']!r}, (\n"
                f"            f\"range invariant violated for input {{x!r}}: \"\n"
                f"            f\"{{result!r}} not in [{params['low']!r}, {params['high']!r}]\"\n"
                f"        )"
            )
        elif kind == "no_substring":
            lines.append(
                f"        # invariant: {desc}\n"
                f"        result = _TARGET(x)\n"
                f"        assert {params['needle']!r} not in str(result), (\n"
                f"            f\"no_substring invariant violated for input {{x!r}}: \"\n"
                f"            f\"forbidden substring {params['needle']!r} present in output\"\n"
                f"        )"
            )
    return "\n".join(lines)


def _emit_monotonic_tests(invariants: list[dict[str, Any]]) -> str:
    """Render standalone monotonic test functions (operate on sorted inputs)."""
    blocks: list[str] = []
    for idx, inv in enumerate(invariants):
        if inv["kind"] != "monotonic":
            continue
        direction = inv["params"]["direction"]
        desc = inv["description"]
        op = "<=" if direction == "increasing" else ">="
        blocks.append(
            f"def test_monotonic_{idx}() -> None:\n"
            f'    """Property: {desc}."""\n'
            f"    rng = random.Random(SEED + {idx})\n"
            f"    xs = sorted(rng.uniform(-1000.0, 1000.0) for _ in range(SAMPLES))\n"
            f"    outputs = [_TARGET(x) for x in xs]\n"
            f"    for prev, curr, xa, xb in zip(outputs, outputs[1:], xs, xs[1:]):\n"
            f"        assert prev {op} curr, (\n"
            f'            f"monotonic ({direction}) invariant violated between "\n'
            f'            f"inputs {{xa!r}} and {{xb!r}}: {{prev!r}} {op} {{curr!r}} is False"\n'
            f"        )"
        )
    return "\n\n\n".join(blocks)


def generate_proptest(spec: dict[str, Any]) -> GeneratedProptest:
    """Generate a deterministic fixed-seed property test from a normalized spec.

    Parameters
    ----------
    spec:
        A spec dict as returned by :func:`load_spec`. (Passing the raw,
        un-normalized JSON dict also works as long as it carries the expected
        keys; callers should prefer :func:`load_spec` for validation.)

    Returns
    -------
    GeneratedProptest
        The relative test path and the rendered test source.
    """
    # Accept either a pre-normalized spec or a raw dict; normalize defensively.
    if "module" not in spec or "attr" not in spec:
        spec = load_spec(json.dumps(spec))

    name = _sanitize(spec["name"])
    module = spec["module"]
    attr = spec["attr"]
    seed = spec["seed"]
    samples = spec["samples"]
    invariants = spec["invariants"]

    has_sample_invariants = any(i["kind"] in ("range", "no_substring") for i in invariants)
    has_monotonic = any(i["kind"] == "monotonic" for i in invariants)

    sample_block = _emit_assertions(invariants) if has_sample_invariants else ""
    monotonic_block = _emit_monotonic_tests(invariants) if has_monotonic else ""

    parts: list[str] = []
    parts.append(
        f'"""Auto-generated property test for `{spec["import_path"]}`.\n\n'
        f"Generated by `onmc proptest`. Deterministic: a fixed seed ({seed}) drives\n"
        f"all sampling, so failures are reproducible. Regenerate by re-running the\n"
        f'same spec — do not hand-edit unless you also update the spec.\n"""\n'
    )
    parts.append("from __future__ import annotations\n")
    parts.append("import random\n")
    parts.append(f"from {module} import {attr} as _TARGET\n")
    parts.append(f"SEED = {seed}")
    parts.append(f"SAMPLES = {samples}\n")

    if has_sample_invariants:
        body = sample_block if sample_block else "        pass"
        parts.append(
            "def test_invariants_over_samples() -> None:\n"
            '    """Assert per-sample invariants over fixed-seed random inputs."""\n'
            "    rng = random.Random(SEED)\n"
            "    for _ in range(SAMPLES):\n"
            "        x = rng.uniform(-1000.0, 1000.0)\n"
            f"{body}\n"
        )

    if monotonic_block:
        parts.append(monotonic_block + "\n")

    source = "\n".join(parts)
    test_path = Path(f"test_proptest_{name}.py")
    return GeneratedProptest(test_path=test_path, test_source=source, name=name)
