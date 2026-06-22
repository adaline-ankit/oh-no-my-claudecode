"""Knowledge-gap dashboard compiler for ONMC.

Pure, typed functions — no side effects beyond reads from storage.

Design
------
Coverage asks: "which parts of this repo does stored memory actually cover,
and where are the blind spots?"

The killer insight is surfacing **hotspot files / subsystems** (high-churn,
high-risk) that have **zero or thin memory coverage** — those are landmines.

A memory "covers" a file when the memory's ``source_ref`` contains the file
path.  The ``source_ref`` field can hold either a single path or a
pipe-separated list of paths (as written by git_history helpers), so we
split on ``|`` before matching.

Grouping
--------
Per-file is too granular for large repos.  We bucket files into their
top-level directories (mirrors :func:`path_bucket`) and report
per-subsystem rows, then call out the worst individual hotspot files.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.core.repo import path_bucket
from oh_no_my_claudecode.models import FileStat, MemoryEntry
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

# Maximum hotspot files to call out in the top-gaps list.
_MAX_GAP_FILES = 10
# Minimum churn count for a file to be considered a "hotspot" worth flagging.
_MIN_CHURN_FOR_HOTSPOT = 2


@dataclass(slots=True)
class UncoveredHotspot:
    """A high-churn file with no (or thin) memory coverage."""

    path: str
    churn: int
    recent_churn: int
    subsystem: str


@dataclass(slots=True)
class SubsystemRow:
    """Per-subsystem coverage summary."""

    subsystem: str
    total_files: int
    covered_files: int
    coverage_pct: float
    total_churn: int


@dataclass(slots=True)
class CoverageReport:
    """Knowledge-gap dashboard: overall coverage + per-subsystem breakdown + top gaps.

    Fields
    ------
    overall_coverage_pct:
        Percentage of tracked files that have ≥1 related memory.
    covered_files:
        Number of files with ≥1 memory.
    uncovered_files:
        Number of files with zero memory coverage.
    total_files:
        Total tracked files in the repo index.
    subsystem_rows:
        Per-subsystem coverage rows, sorted by ascending ``coverage_pct``
        (worst-covered subsystems first).
    top_gaps:
        Hotspot files (high churn) with zero memory coverage — the actionable
        landmines.  Sorted by descending ``churn``.
    memory_count:
        Total memories consulted for this report.
    """

    overall_coverage_pct: float
    covered_files: int
    uncovered_files: int
    total_files: int
    subsystem_rows: list[SubsystemRow] = field(default_factory=list)
    top_gaps: list[UncoveredHotspot] = field(default_factory=list)
    memory_count: int = 0


def compile_coverage(
    storage: SQLiteStorage,
    repo_root: Path,  # noqa: ARG001  (reserved for future file-existence checks)
) -> CoverageReport:
    """Compute a :class:`CoverageReport` for this repo.

    Pure calculation — reads from storage; writes nothing.

    Parameters
    ----------
    storage:
        Initialised SQLiteStorage for the repo.
    repo_root:
        Absolute path to the repository root.  Currently used only as a
        placeholder for future file-existence staleness checks.
    """
    memories = storage.list_memories()
    file_stats = storage.list_file_stats()

    if not file_stats:
        return CoverageReport(
            overall_coverage_pct=0.0,
            covered_files=0,
            uncovered_files=0,
            total_files=0,
            memory_count=len(memories),
        )

    # Build the set of all paths that have at least one memory reference.
    memory_refs: set[str] = _collect_memory_refs(memories)

    # Per-file coverage.
    covered_paths: set[str] = set()
    uncovered_hotspots: list[FileStat] = []

    for stat in file_stats:
        if stat.path in memory_refs:
            covered_paths.add(stat.path)
        elif stat.change_count >= _MIN_CHURN_FOR_HOTSPOT:
            uncovered_hotspots.append(stat)

    total = len(file_stats)
    covered = len(covered_paths)
    uncovered = total - covered
    pct = round(covered / total * 100.0, 1) if total > 0 else 0.0

    # Per-subsystem rows.
    subsystem_rows = _build_subsystem_rows(file_stats, covered_paths)

    # Top gaps: hotspot files with no memory, sorted by churn descending.
    top_gaps = _build_top_gaps(uncovered_hotspots)

    return CoverageReport(
        overall_coverage_pct=pct,
        covered_files=covered,
        uncovered_files=uncovered,
        total_files=total,
        subsystem_rows=subsystem_rows,
        top_gaps=top_gaps,
        memory_count=len(memories),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _collect_memory_refs(memories: list[MemoryEntry]) -> set[str]:
    """Return every path token mentioned across all memory source_refs."""
    refs: set[str] = set()
    for mem in memories:
        for token in mem.source_ref.split("|"):
            stripped = token.strip()
            if stripped:
                refs.add(stripped)
    return refs


def _build_subsystem_rows(
    file_stats: list[FileStat],
    covered_paths: set[str],
) -> list[SubsystemRow]:
    """Aggregate per-file stats into per-subsystem rows."""
    # subsystem → {total, covered, churn}
    totals: dict[str, int] = defaultdict(int)
    covered_counts: dict[str, int] = defaultdict(int)
    churn_totals: dict[str, int] = defaultdict(int)

    for stat in file_stats:
        bucket = path_bucket(stat.path) or "."
        totals[bucket] += 1
        churn_totals[bucket] += stat.change_count
        if stat.path in covered_paths:
            covered_counts[bucket] += 1

    rows: list[SubsystemRow] = []
    for subsystem, total in sorted(totals.items()):
        cov = covered_counts[subsystem]
        pct = round(cov / total * 100.0, 1) if total > 0 else 0.0
        rows.append(
            SubsystemRow(
                subsystem=subsystem,
                total_files=total,
                covered_files=cov,
                coverage_pct=pct,
                total_churn=churn_totals[subsystem],
            )
        )

    # Sort by coverage ascending (worst-covered first), then by churn desc.
    rows.sort(key=lambda r: (r.coverage_pct, -r.total_churn))
    return rows


def _build_top_gaps(uncovered_hotspots: list[FileStat]) -> list[UncoveredHotspot]:
    """Return top-N uncovered hotspot files sorted by churn descending."""
    sorted_hotspots = sorted(
        uncovered_hotspots,
        key=lambda s: (-s.change_count, -s.recent_change_count, s.path),
    )
    return [
        UncoveredHotspot(
            path=stat.path,
            churn=stat.change_count,
            recent_churn=stat.recent_change_count,
            subsystem=path_bucket(stat.path) or ".",
        )
        for stat in sorted_hotspots[:_MAX_GAP_FILES]
    ]
