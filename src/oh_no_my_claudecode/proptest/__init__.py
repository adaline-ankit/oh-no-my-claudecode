"""Property/invariant test generator feature.

``onmc proptest init <spec>`` reads an invariant spec for a pure function and
emits a deterministic, fixed-seed sampling test that asserts each declared
invariant over many generated inputs — catching edge cases that hand-written
example tests miss.

No third-party property-testing library is required: the generated test uses
only the standard library (``random`` with a fixed seed) so it is reproducible
and dependency-free.

The feature self-registers via the command auto-discovery hook (see
:mod:`oh_no_my_claudecode.command_registry`); adding it touches no central
``cli.py`` / ``core`` / rendering hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.proptest.generator import (
    GeneratedProptest,
    ProptestSpecError,
    generate_proptest,
)

__all__ = [
    "GeneratedProptest",
    "ProptestSpecError",
    "generate_proptest",
]
