"""Pure, deterministic generation of a failing-test contract from a spec.

A *contract spec* is a small JSON document describing one callable:

.. code-block:: json

    {
      "name": "add",
      "summary": "Add two integers.",
      "signature": "add(a, b)",
      "cases": [
        {"given": [1, 2], "expect": 3},
        {"given": [0, 0], "expect": 0}
      ]
    }

:func:`generate_contract` turns that into two source artifacts:

- ``tests/test_<name>.py`` — one asserting test per case (``output == expect``
  for the given args), importing the stub.
- ``<name>.py`` — a stub whose function raises :class:`NotImplementedError`.

The generated test file therefore *fails* until the stub is implemented: this is
TDD enforced by construction. Generation is pure (no I/O) and deterministic — the
same spec always yields byte-identical output.
"""

from __future__ import annotations

import json
import keyword
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

__all__ = [
    "ContractSpecError",
    "GeneratedContract",
    "generate_contract",
    "parse_spec",
]

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class ContractSpecError(ValueError):
    """Raised when a contract spec is malformed or missing required fields."""


@dataclass(frozen=True)
class GeneratedContract:
    """The two source files produced from a contract spec.

    Attributes
    ----------
    name:
        The validated callable name (a valid Python identifier).
    test_path:
        POSIX-style relative path for the generated test (e.g.
        ``tests/test_add.py``).
    test_source:
        Full source of the generated pytest module.
    stub_path:
        POSIX-style relative path for the generated stub (e.g. ``add.py``).
    stub_source:
        Full source of the generated stub module.
    case_count:
        Number of asserting tests emitted (one per spec case).
    """

    name: str
    test_path: str
    test_source: str
    stub_path: str
    stub_source: str
    case_count: int


def parse_spec(raw: str) -> dict[str, Any]:
    """Parse and validate a raw JSON contract spec string.

    Parameters
    ----------
    raw:
        The JSON text of the spec.

    Returns
    -------
    dict
        The validated spec mapping.

    Raises
    ------
    ContractSpecError
        If the JSON is invalid, the top level is not an object, the ``name`` is
        not a valid identifier, or ``cases`` is missing/empty/malformed.
    """
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractSpecError(f"spec is not valid JSON: {exc}") from exc

    if not isinstance(spec, dict):
        raise ContractSpecError("spec must be a JSON object")

    name = spec.get("name")
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name) or keyword.iskeyword(name):
        raise ContractSpecError(
            "spec 'name' must be a valid (non-keyword) Python identifier"
        )

    cases = spec.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ContractSpecError("spec 'cases' must be a non-empty list")

    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ContractSpecError(f"case {index} must be an object")
        if "given" not in case:
            raise ContractSpecError(f"case {index} is missing 'given'")
        if "expect" not in case:
            raise ContractSpecError(f"case {index} is missing 'expect'")

    return spec


def _call_args(given: Any) -> str:
    """Render ``given`` as a positional-args string for a call expression.

    A list is spread as positional args; anything else is passed as a single arg.
    Values are rendered with :func:`repr`, which is deterministic for JSON
    scalars and containers.
    """
    if isinstance(given, list):
        return ", ".join(repr(arg) for arg in given)
    return repr(given)


def generate_contract(raw: str) -> GeneratedContract:
    """Generate a failing test + stub from a raw JSON contract spec.

    Parameters
    ----------
    raw:
        The JSON text of the contract spec.

    Returns
    -------
    GeneratedContract
        The generated test and stub sources together with their relative paths.

    Raises
    ------
    ContractSpecError
        If the spec is malformed (see :func:`parse_spec`).
    """
    spec = parse_spec(raw)
    name = str(spec["name"])
    cases: list[dict[str, Any]] = list(spec["cases"])
    summary = spec.get("summary")
    signature = spec.get("signature")

    test_path = PurePosixPath("tests") / f"test_{name}.py"
    stub_path = PurePosixPath(f"{name}.py")

    test_source = _render_test(name, summary, signature, cases)
    stub_source = _render_stub(name, summary, signature)

    return GeneratedContract(
        name=name,
        test_path=str(test_path),
        test_source=test_source,
        stub_path=str(stub_path),
        stub_source=stub_source,
        case_count=len(cases),
    )


def _render_stub(name: str, summary: Any, signature: Any) -> str:
    """Render the stub module source (a function raising ``NotImplementedError``)."""
    doc_lines = ['"""Stub generated by `onmc contract`. Implement me to go green.']
    if isinstance(summary, str) and summary.strip():
        doc_lines.extend(["", summary.strip()])
    if isinstance(signature, str) and signature.strip():
        doc_lines.extend(["", f"Signature: {signature.strip()}"])
    doc_lines.append('"""')
    module_doc = "\n".join(doc_lines)

    return (
        f"{module_doc}\n"
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "from typing import Any\n"
        "\n"
        "\n"
        f"def {name}(*args: Any, **kwargs: Any) -> Any:\n"
        f'    """Not yet implemented — replace this body to satisfy the contract."""\n'
        f'    raise NotImplementedError("{name} is not implemented yet")\n'
    )


def _render_test(
    name: str,
    summary: Any,
    signature: Any,
    cases: list[dict[str, Any]],
) -> str:
    """Render the pytest module source with one asserting test per case."""
    header_lines = [
        f'"""Contract tests for `{name}` generated by `onmc contract`.']
    if isinstance(summary, str) and summary.strip():
        header_lines.extend(["", summary.strip()])
    if isinstance(signature, str) and signature.strip():
        header_lines.extend(["", f"Signature: {signature.strip()}"])
    header_lines.extend(
        [
            "",
            "These tests FAIL until the stub is implemented; make them green.",
            '"""',
        ]
    )
    module_doc = "\n".join(header_lines)

    parts = [
        module_doc,
        "",
        "from __future__ import annotations",
        "",
        f"from {name} import {name}",
        "",
    ]

    for index, case in enumerate(cases):
        call = _call_args(case["given"])
        expected = repr(case["expect"])
        parts.extend(
            [
                "",
                f"def test_{name}_case_{index}() -> None:",
                f"    assert {name}({call}) == {expected}",
            ]
        )

    return "\n".join(parts) + "\n"
