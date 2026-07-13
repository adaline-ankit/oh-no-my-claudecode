"""Coverage report for the structural repo code graph.

Computes what fraction of discoverable source files are actually indexed by
:func:`~oh_no_my_claudecode.codegraph.builder.build_codegraph`, and identifies
languages that are present in the repo but *not* indexed — either because the
optional ``tree-sitter`` extra is absent or the language is unsupported.

The main entry points are:

- :func:`codegraph_coverage` — pure, offline, no LLM — walks the filesystem
  and compares against the built graph.
- :func:`emit_coverage_warning` — prints a warning to *stderr* when significant
  coverage is lost because tree-sitter is not installed.  Called automatically
  by :func:`~oh_no_my_claudecode.codegraph.builder.build_codegraph`.
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from oh_no_my_claudecode.codegraph import treesitter_ext

if TYPE_CHECKING:
    from oh_no_my_claudecode.codegraph.models import CodeGraph

# Directories excluded from the filesystem walk — must mirror builder._EXCLUDE_DIRS
# to keep the denominator consistent with what the builder would actually see.
_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".onmc",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        ".tox",
        "build",
        "dist",
        ".eggs",
        "site-packages",
    }
)

# Every extension the graph CAN index given the right setup.
_ALL_INDEXABLE_EXTENSIONS: frozenset[str] = (
    frozenset({".py"}) | treesitter_ext.supported_extensions()
)

# Threshold: warn when unindexed-but-supported files represent at least this
# many files OR this fraction of total discoverable source files.
_WARN_ABS_THRESHOLD: int = 10
_WARN_PCT_THRESHOLD: float = 5.0


@dataclass(slots=True, frozen=True)
class CoverageReport:
    """Coverage breakdown for the structural code graph.

    Attributes
    ----------
    total_source_files:
        Total source files discoverable on disk whose extension is either
        ``.py`` or in :func:`~oh_no_my_claudecode.codegraph.treesitter_ext.supported_extensions`.
        This is the denominator — the *potential* universe the graph could index
        if all optional extras were installed.
    indexed_files:
        Files actually present in the :class:`~oh_no_my_claudecode.codegraph.models.CodeGraph`
        that was built (i.e. ``graph.file_count``).
    treesitter_available:
        Whether the optional ``tree-sitter`` extra is importable at runtime.
    languages_present_but_unindexed:
        Mapping of file extension → count for files that are *on disk* and
        belong to a tree-sitter-supported language, but were NOT indexed because
        tree-sitter is unavailable.  Empty when tree-sitter is installed or when
        the repo has no such files.
    extensions_indexed:
        Mapping of file extension → count for files that WERE indexed (useful
        for the ``--json`` output and the coverage subcommand).
    """

    total_source_files: int
    indexed_files: int
    treesitter_available: bool
    languages_present_but_unindexed: dict[str, int] = field(default_factory=dict)
    extensions_indexed: dict[str, int] = field(default_factory=dict)

    @property
    def coverage_pct(self) -> float:
        """Percentage of total discoverable source files that are indexed (0-100)."""
        if self.total_source_files == 0:
            return 100.0
        return self.indexed_files / self.total_source_files * 100.0

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {
            "total_source_files": self.total_source_files,
            "indexed_files": self.indexed_files,
            "coverage_pct": round(self.coverage_pct, 1),
            "treesitter_available": self.treesitter_available,
            "languages_present_but_unindexed": dict(self.languages_present_but_unindexed),
            "extensions_indexed": dict(self.extensions_indexed),
        }


def codegraph_coverage(
    repo_root: Path,
    graph: CodeGraph | None = None,
) -> CoverageReport:
    """Compute a :class:`CoverageReport` for *repo_root*.

    Walks the filesystem to discover every source file whose extension is in the
    set of *all potentially indexable* extensions (Python always, tree-sitter
    languages always listed even if the extra is absent).  Compares that universe
    against what is actually inside *graph* (or reports indexed_files=0 when no
    graph is provided).

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root.
    graph:
        The built :class:`~oh_no_my_claudecode.codegraph.models.CodeGraph`, used
        to determine how many files were indexed.  When ``None``, ``indexed_files``
        is reported as 0 and ``extensions_indexed`` is empty — useful for running
        the coverage check before or without a build.
    """
    repo_root = repo_root.resolve()
    ts_available = treesitter_ext.treesitter_available()
    ts_supported = treesitter_ext.supported_extensions()  # extensions tree-sitter CAN handle

    # --- Filesystem walk: count files by extension --------------------------
    ext_counts: Counter[str] = Counter()
    for current_root, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in _EXCLUDE_DIRS and not name.startswith(".git")
        )
        for filename in filenames:
            suffix = Path(filename).suffix.lower()
            if suffix in _ALL_INDEXABLE_EXTENSIONS:
                file_path = Path(current_root) / filename
                if not file_path.is_symlink():
                    ext_counts[suffix] += 1

    total_source_files = sum(ext_counts.values())

    # --- Indexed extensions: derived from graph nodes -----------------------
    extensions_indexed: Counter[str] = Counter()
    if graph is not None:
        for rel_path in graph.nodes:
            suffix = Path(rel_path).suffix.lower()
            extensions_indexed[suffix] += 1

    indexed_files = sum(extensions_indexed.values()) if graph is not None else 0

    # --- Languages present but unindexed ------------------------------------
    # An extension is "present but unindexed" when:
    # - it belongs to a tree-sitter-supported language, AND
    # - tree-sitter is NOT available (so the builder skipped it), AND
    # - there are files with that extension on disk.
    languages_present_but_unindexed: dict[str, int] = {}
    if not ts_available:
        for ext, count in ext_counts.items():
            if ext in ts_supported and count > 0:
                languages_present_but_unindexed[ext] = count

    return CoverageReport(
        total_source_files=total_source_files,
        indexed_files=indexed_files,
        treesitter_available=ts_available,
        languages_present_but_unindexed=dict(
            sorted(languages_present_but_unindexed.items(), key=lambda kv: -kv[1])
        ),
        extensions_indexed=dict(
            sorted(extensions_indexed.items(), key=lambda kv: -kv[1])
        ),
    )


def emit_coverage_warning(report: CoverageReport) -> None:
    """Print coverage summary and a prominent warning to *stderr* when needed.

    Always emits a one-line coverage summary.  Emits an additional multi-line
    install-hint warning when a meaningful number of source files are not indexed
    because the ``tree-sitter`` extra is absent.

    The "meaningful" threshold: ≥ :data:`_WARN_ABS_THRESHOLD` unindexed files
    **or** ≥ :data:`_WARN_PCT_THRESHOLD` % of total discoverable source files.
    """
    unindexed_total = sum(report.languages_present_but_unindexed.values())

    # One-line coverage summary — always printed.
    if report.total_source_files == 0:
        summary = f"code graph: indexed {report.indexed_files} files (no source files found)"
    else:
        pct = report.coverage_pct
        lang_detail = ", ".join(
            f"{ext.lstrip('.')} ({cnt})"
            for ext, cnt in report.languages_present_but_unindexed.items()
        )
        if lang_detail:
            summary = (
                f"code graph: indexed {report.indexed_files}/{report.total_source_files} files"
                f" ({pct:.1f}%); unindexed languages: {lang_detail}"
            )
        else:
            summary = (
                f"code graph: indexed {report.indexed_files}/{report.total_source_files} files"
                f" ({pct:.1f}%)"
            )
    print(summary, file=sys.stderr)

    # Loud warning — only when degradation is significant.
    if not report.treesitter_available and unindexed_total > 0:
        pct_unindexed = (
            unindexed_total / report.total_source_files * 100.0
            if report.total_source_files > 0
            else 0.0
        )
        should_warn = (
            unindexed_total >= _WARN_ABS_THRESHOLD
            or pct_unindexed >= _WARN_PCT_THRESHOLD
        )
        if not should_warn:
            return

        top_langs = ", ".join(
            f"{ext.lstrip('.')} ({cnt})"
            for ext, cnt in list(report.languages_present_but_unindexed.items())[:5]
        )
        print(
            "\n"
            "WARNING: code graph is Python-only — non-Python files were NOT indexed.\n"
            f"  Unindexed languages: {top_langs}\n"
            "  This means `onmc context`, `onmc mission`, and blast-radius results\n"
            "  will silently miss these files and return incorrect or empty results.\n"
            "\n"
            "  To index all languages, install the tree-sitter extra:\n"
            "\n"
            '    uv tool install "oh-no-my-claudecode[treesitter]"\n'
            "    # or\n"
            '    pip install "oh-no-my-claudecode[treesitter]"\n',
            file=sys.stderr,
        )
