"""Portable on-disk schema introspection (``onmc formats``).

Emits a versioned specification of onmc's stable portable formats — the run
receipt, the attestation, and the exported memory record + federation
manifest — derived live from the real dataclasses/models via introspection
(see :mod:`oh_no_my_claudecode.formats.formats`) so the spec can never drift
from what onmc actually writes to disk.
"""

from __future__ import annotations

from oh_no_my_claudecode.formats.formats import (
    SCHEMA_NAMES,
    SPEC_DOCUMENT_VERSION,
    FieldSpec,
    SchemaSpec,
    SpecDocument,
    build_spec,
    render_text,
    to_json_dict,
)

__all__ = [
    "SCHEMA_NAMES",
    "SPEC_DOCUMENT_VERSION",
    "FieldSpec",
    "SchemaSpec",
    "SpecDocument",
    "build_spec",
    "render_text",
    "to_json_dict",
]
