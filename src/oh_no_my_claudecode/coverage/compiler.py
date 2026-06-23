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

Suggestions (--suggest)
-----------------------
:func:`suggest_coverage` layers a deterministic action-item pass over a
:class:`CoverageReport`.  For each uncovered hotspot in ``report.top_gaps``
it produces a :class:`CoverageSuggestion` with:

- a deterministic ``suggested_title`` phrased in plain English
- a heuristic ``suggested_kind`` derived from the file path and churn
- a ``rationale`` string explaining why this file was chosen
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.core.repo import path_bucket
from oh_no_my_claudecode.models import FileStat, MemoryEntry, MemoryKind
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


@dataclass(slots=True)
class CoverageSuggestion:
    """An actionable documentation suggestion for one uncovered hotspot file.

    Fields
    ------
    file:
        Repo-relative path of the uncovered hotspot file.
    subsystem:
        Top-level directory bucket (mirrors :class:`UncoveredHotspot`).
    suggested_title:
        Deterministic, human-readable title for the memory stub to create.
    suggested_kind:
        Heuristic :class:`~oh_no_my_claudecode.models.MemoryKind` to assign —
        ``DECISION`` for config/infra, ``INVARIANT`` for core hot files,
        ``DOC_FACT`` otherwise.
    rationale:
        Short explanation of why this file was selected (e.g. churn count).
    churn:
        Total commit count for the file (mirrors :attr:`UncoveredHotspot.churn`).
    """

    file: str
    subsystem: str
    suggested_title: str
    suggested_kind: MemoryKind
    rationale: str
    churn: int


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


def suggest_coverage(
    report: CoverageReport,
    repo_root: Path,  # noqa: ARG001  (reserved for future per-file heuristics)
    *,
    limit: int = 10,
) -> list[CoverageSuggestion]:
    """Produce deterministic documentation suggestions for the top uncovered hotspots.

    Pure calculation — reads from *report*; writes nothing.

    For each :class:`UncoveredHotspot` in ``report.top_gaps`` (up to *limit*)
    the function derives:

    - ``suggested_kind``: :attr:`~MemoryKind.DECISION` when the path contains
      config/infra/deploy/settings tokens; :attr:`~MemoryKind.INVARIANT` when
      the file has very high churn (≥ ``_HIGH_CHURN_INVARIANT``);
      :attr:`~MemoryKind.NOTE` otherwise.
    - ``suggested_title``: a plain-English sentence that names the file.
    - ``rationale``: why the file was chosen (commit counts).

    Returns an empty list when ``report.top_gaps`` is empty.

    Parameters
    ----------
    report:
        A :class:`CoverageReport` previously produced by :func:`compile_coverage`.
    repo_root:
        Absolute path to the repo root (reserved for future file-content heuristics).
    limit:
        Maximum number of suggestions to return.  Defaults to 10.
    """
    suggestions: list[CoverageSuggestion] = []
    for hotspot in report.top_gaps[:limit]:
        kind = _suggest_kind(hotspot)
        title = _suggest_title(hotspot, kind)
        rationale = _suggest_rationale(hotspot)
        suggestions.append(
            CoverageSuggestion(
                file=hotspot.path,
                subsystem=hotspot.subsystem,
                suggested_title=title,
                suggested_kind=kind,
                rationale=rationale,
                churn=hotspot.churn,
            )
        )
    return suggestions


# Churn threshold above which a file is treated as invariant-worthy (very hot).
_HIGH_CHURN_INVARIANT = 10

# Path tokens that indicate a configuration / infrastructure / deployment file.
_CONFIG_TOKENS = frozenset(
    {
        "config",
        "conf",
        "settings",
        "infra",
        "deploy",
        "deployment",
        "ci",
        "workflow",
        "workflows",
        "env",
        "environment",
        "terraform",
        "helm",
        "k8s",
        "kubernetes",
        "docker",
        "compose",
        "pulumi",
        "ansible",
        "makefile",
    }
)


def _suggest_kind(hotspot: UncoveredHotspot) -> MemoryKind:
    """Heuristic: derive a MemoryKind from path tokens and churn."""
    path_lower = hotspot.path.lower()
    # Split on path separators and common punctuation for token matching.
    path_tokens = frozenset(
        token
        for part in Path(path_lower).parts
        for token in part.replace("-", "_").replace(".", "_").split("_")
        if token
    )
    if path_tokens & _CONFIG_TOKENS:
        return MemoryKind.DECISION
    if hotspot.churn >= _HIGH_CHURN_INVARIANT:
        return MemoryKind.INVARIANT
    return MemoryKind.DOC_FACT


def _suggest_title(hotspot: UncoveredHotspot, kind: MemoryKind) -> str:
    """Produce a deterministic plain-English title for a coverage stub."""
    filename = Path(hotspot.path).name
    if kind == MemoryKind.DECISION:
        return f"Document why {filename} changes so often"
    if kind == MemoryKind.INVARIANT:
        return f"Record the invariant governing {filename}"
    return f"Add a note explaining {filename}"


def _suggest_rationale(hotspot: UncoveredHotspot) -> str:
    """One-sentence rationale for why this file needs documentation."""
    recent_clause = (
        f", {hotspot.recent_churn} in the last 30 days" if hotspot.recent_churn else ""
    )
    return (
        f"{hotspot.churn} commits in window{recent_clause}, 0 memories — "
        "high-churn file with no recorded knowledge."
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
