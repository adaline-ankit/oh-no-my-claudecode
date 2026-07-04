"""Adversarial diff-level verification gate for onmc verify-diff."""

from __future__ import annotations

from oh_no_my_claudecode.verifydiff.checker import (
    AddedLine,
    Coverage,
    DiffFinding,
    StructuralDiffRunner,
    StructuralResult,
    VerifyReport,
    collect_diff,
    difftastic_available,
    make_difftastic_runner,
    verify_diff,
)

__all__ = [
    "AddedLine",
    "Coverage",
    "DiffFinding",
    "StructuralDiffRunner",
    "StructuralResult",
    "VerifyReport",
    "collect_diff",
    "difftastic_available",
    "make_difftastic_runner",
    "verify_diff",
]
