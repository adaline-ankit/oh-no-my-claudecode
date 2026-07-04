"""The ``onmc drift`` feature — institutional-memory *enforcement*.

onmc stores decisions, invariants, and conventions.  ``drift`` makes that memory
*guard* the code: :func:`check_drift` detects where the current source likely
**contradicts** a recorded directive (e.g. an invariant "never use requests" but
``import requests`` appears in the tree) and surfaces those spots as candidates
for human review.

The heuristic is pure, offline, deterministic, and **honest** — every finding is
a *candidate* with a confidence score, never a proof.  See
:mod:`oh_no_my_claudecode.drift.drift` for the scoring model.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``drift.commands``
module exposing ``register(app)`` — zero edits to ``cli.py`` or any shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.drift.drift import (
    DriftFinding,
    DriftReport,
    DriftSignal,
    FileTextProvider,
    check_drift,
    default_file_text_provider,
    extract_signal,
)

__all__ = [
    "DriftFinding",
    "DriftReport",
    "DriftSignal",
    "FileTextProvider",
    "check_drift",
    "default_file_text_provider",
    "extract_signal",
]
