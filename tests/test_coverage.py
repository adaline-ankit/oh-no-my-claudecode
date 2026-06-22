"""Tests for the `onmc coverage` knowledge-gap dashboard.

Covers:
- coverage % is computed correctly on a seeded repo + memories
- uncovered hotspot files surface in top-gaps
- a fully-covered repo shows no gaps
- --json emits a valid CoverageReport-shaped dict
- empty store (no file stats) returns 0% gracefully
- subsystem rows are sorted worst-first
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.coverage.compiler import (
    CoverageReport,
    compile_coverage,
)
from oh_no_my_claudecode.models import FileStat, MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

runner = CliRunner()


def _make_memory(
    *,
    idx: int,
    source_ref: str,
    kind: MemoryKind = MemoryKind.DOC_FACT,
) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=f"mem-{idx}",
        kind=kind,
        title=f"Memory {idx}",
        summary=f"Summary for memory {idx}",
        details=f"Details for memory {idx}",
        source_type=SourceType.DOC,
        source_ref=source_ref,
        tags=[],
        confidence=0.8,
        created_at=now,
        updated_at=now,
    )


def _make_stat(
    path: str,
    *,
    churn: int = 5,
    recent: int = 2,
) -> FileStat:
    return FileStat(
        path=path,
        change_count=churn,
        recent_change_count=recent,
        last_modified_at=None,
        is_test=False,
        top_level_dir=path.split("/")[0] if "/" in path else ".",
    )


def _seed_storage(
    tmp_path: Path,
    *,
    file_stats: list[FileStat],
    memories: list[MemoryEntry],
) -> SQLiteStorage:
    db = SQLiteStorage(tmp_path / "mem.db")
    db.initialize()
    db.replace_file_stats(file_stats)
    db.upsert_memories(memories)
    return db


# ---------------------------------------------------------------------------
# Unit tests — compile_coverage (pure)
# ---------------------------------------------------------------------------


def test_coverage_partial(tmp_path: Path) -> None:
    """2-of-4 files covered → 50 % overall coverage."""
    stats = [
        _make_stat("src/cache.py", churn=10),
        _make_stat("src/worker.py", churn=8),
        _make_stat("src/auth.py", churn=3),
        _make_stat("README.md", churn=1),
    ]
    memories = [
        _make_memory(idx=1, source_ref="src/cache.py"),
        _make_memory(idx=2, source_ref="src/worker.py"),
    ]
    db = _seed_storage(tmp_path, file_stats=stats, memories=memories)
    report = compile_coverage(db, tmp_path)

    assert report.total_files == 4
    assert report.covered_files == 2
    assert report.uncovered_files == 2
    assert report.overall_coverage_pct == 50.0
    assert report.memory_count == 2


def test_coverage_hotspot_surfaces_in_top_gaps(tmp_path: Path) -> None:
    """High-churn files with no memory appear in top_gaps."""
    stats = [
        _make_stat("src/cache.py", churn=20, recent=5),  # hotspot, uncovered
        _make_stat("src/worker.py", churn=15, recent=3),  # hotspot, uncovered
        _make_stat("src/stable.py", churn=1),             # low churn, ignored
    ]
    memories = []  # no memories at all
    db = _seed_storage(tmp_path, file_stats=stats, memories=memories)
    report = compile_coverage(db, tmp_path)

    gap_paths = [gap.path for gap in report.top_gaps]
    assert "src/cache.py" in gap_paths, "highest-churn uncovered file must be a top gap"
    assert "src/worker.py" in gap_paths
    # Low-churn file does NOT appear in gaps (churn < _MIN_CHURN_FOR_HOTSPOT=2)
    assert "src/stable.py" not in gap_paths


def test_coverage_full_coverage_no_gaps(tmp_path: Path) -> None:
    """When every tracked file has a memory, top_gaps is empty."""
    stats = [
        _make_stat("src/cache.py", churn=10),
        _make_stat("src/worker.py", churn=8),
    ]
    memories = [
        _make_memory(idx=1, source_ref="src/cache.py"),
        _make_memory(idx=2, source_ref="src/worker.py"),
    ]
    db = _seed_storage(tmp_path, file_stats=stats, memories=memories)
    report = compile_coverage(db, tmp_path)

    assert report.overall_coverage_pct == 100.0
    assert report.top_gaps == [], "fully-covered repo must have no gaps"
    assert report.covered_files == 2


def test_coverage_empty_store_returns_zero(tmp_path: Path) -> None:
    """No file stats → 0% coverage without errors."""
    db = SQLiteStorage(tmp_path / "mem.db")
    db.initialize()
    report = compile_coverage(db, tmp_path)

    assert isinstance(report, CoverageReport)
    assert report.overall_coverage_pct == 0.0
    assert report.total_files == 0
    assert report.covered_files == 0
    assert report.top_gaps == []
    assert report.subsystem_rows == []


def test_coverage_subsystem_rows_worst_first(tmp_path: Path) -> None:
    """Subsystem rows are sorted ascending by coverage_pct (worst first)."""
    stats = [
        _make_stat("src/a.py", churn=5),
        _make_stat("src/b.py", churn=5),
        _make_stat("lib/x.py", churn=5),
        _make_stat("lib/y.py", churn=5),
    ]
    # Cover lib fully, leave src at 50%
    memories = [
        _make_memory(idx=1, source_ref="lib/x.py"),
        _make_memory(idx=2, source_ref="lib/y.py"),
        _make_memory(idx=3, source_ref="src/a.py"),
        # src/b.py uncovered
    ]
    db = _seed_storage(tmp_path, file_stats=stats, memories=memories)
    report = compile_coverage(db, tmp_path)

    assert len(report.subsystem_rows) >= 2
    # First row must be the worst-covered subsystem (src at 50%, lib at 100%)
    first_subsystem = report.subsystem_rows[0].subsystem
    assert first_subsystem == "src", (
        f"Expected 'src' (50%) to be worst, got '{first_subsystem}'"
    )


def test_coverage_pipe_separated_source_ref(tmp_path: Path) -> None:
    """A pipe-separated source_ref covers multiple files from one memory."""
    stats = [
        _make_stat("src/a.py", churn=5),
        _make_stat("src/b.py", churn=5),
        _make_stat("src/c.py", churn=5),
    ]
    # One memory references two files via pipe
    memories = [
        _make_memory(idx=1, source_ref="src/a.py|src/b.py"),
    ]
    db = _seed_storage(tmp_path, file_stats=stats, memories=memories)
    report = compile_coverage(db, tmp_path)

    # a.py and b.py are covered; c.py is not
    assert report.covered_files == 2
    assert report.uncovered_files == 1


def test_coverage_top_gaps_sorted_by_churn(tmp_path: Path) -> None:
    """top_gaps list is sorted by churn descending."""
    stats = [
        _make_stat("src/low.py", churn=3),
        _make_stat("src/high.py", churn=30),
        _make_stat("src/mid.py", churn=12),
    ]
    db = _seed_storage(tmp_path, file_stats=stats, memories=[])
    report = compile_coverage(db, tmp_path)

    churns = [gap.churn for gap in report.top_gaps]
    assert churns == sorted(churns, reverse=True), "top_gaps must be sorted by churn descending"
    assert report.top_gaps[0].path == "src/high.py"


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


def test_coverage_cli_json_shape(sample_repo: Path, monkeypatch: object) -> None:
    """--json emits a dict with all expected CoverageReport keys."""
    from oh_no_my_claudecode import init

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    init(sample_repo)

    result = runner.invoke(app, ["coverage", "--json"], prog_name="onmc")
    assert result.exit_code == 0, result.output

    data = json.loads(result.output)
    expected_keys = {
        "overall_coverage_pct",
        "covered_files",
        "uncovered_files",
        "total_files",
        "subsystem_rows",
        "top_gaps",
        "memory_count",
    }
    assert expected_keys.issubset(data.keys()), (
        f"Missing keys: {expected_keys - data.keys()}"
    )
    assert isinstance(data["overall_coverage_pct"], float)
    assert isinstance(data["subsystem_rows"], list)
    assert isinstance(data["top_gaps"], list)


def test_coverage_cli_human_output(sample_repo: Path, monkeypatch: object) -> None:
    """Human output (no --json) runs without error and mentions coverage."""
    from oh_no_my_claudecode import init

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    init(sample_repo)

    result = runner.invoke(app, ["coverage"], prog_name="onmc")
    assert result.exit_code == 0, result.output
    # The Coverage Report panel title or coverage % should appear
    output_lower = result.output.lower()
    assert "coverage" in output_lower


def test_coverage_cli_uninitialised(tmp_path: Path, monkeypatch: object) -> None:
    """coverage command exits non-zero when onmc is not initialized."""
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    import subprocess

    repo = tmp_path / "bare-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["coverage"], prog_name="onmc")
    assert result.exit_code != 0
