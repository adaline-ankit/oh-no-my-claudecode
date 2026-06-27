"""Capture and inherit a repository's coding conventions.

This package reads a repo's tooling configuration (``pyproject.toml`` —
``[tool.ruff]`` and ``[tool.mypy]``) plus a fixed set of repo norms and renders
them into ``.onmc/conventions.md``.  The goal is that every spawned agent can
inherit these conventions instead of re-deriving them (or tripping the same
lint/style gotchas) on every run.

Everything here is deterministic and offline: no network, no LLM, no schema
migration.
"""

from __future__ import annotations

from oh_no_my_claudecode.conventions.detector import (
    CONVENTIONS_FILE_NAME,
    Conventions,
    conventions_path,
    detect_conventions,
    render_conventions_markdown,
)

__all__ = [
    "CONVENTIONS_FILE_NAME",
    "Conventions",
    "conventions_path",
    "detect_conventions",
    "render_conventions_markdown",
]
