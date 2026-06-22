"""Shared dataclasses for the ``onmc import`` subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImportResult:
    """Summary of one ``onmc import`` run."""

    source: str
    """Human-readable source label (e.g. ``"omc"``, ``"hermes"``, ``"/path/to/file.md"``)."""

    as_kind: str
    """Whether items were imported as ``"skill"`` or ``"memory"``."""

    imported: int
    """Number of new items written to the store."""

    skipped: int
    """Number of items already present (dedup by stable id) — skipped."""

    dry_run: bool
    """True when no writes were performed (parse + report only)."""

    items: list[str] = field(default_factory=list)
    """Names / titles of items that were imported (or would be imported on dry-run)."""
