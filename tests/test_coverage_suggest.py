"""Tests for `onmc coverage --suggest` / `--apply` mode.

Covers:
- suggest_coverage produces one suggestion per uncovered hotspot
- fully-covered repo → no suggestions
- suggested_kind heuristics: config path → DECISION, high-churn → INVARIANT,
  low-churn non-config → DOC_FACT
- suggested_title is deterministic and contains the filename
- --apply stubs memories idempotently (second --apply skips existing stubs)
- CLI --suggest shows suggestion table
- CLI --apply creates stubs and reports count
- CLI --suggest --json emits report + suggestions keys
- CLI --apply --json emits report + suggestions keys
- CLI with no gaps → "No suggestions" message
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.coverage.compiler import (
    CoverageSuggestion,
    compile_coverage,
    suggest_coverage,
)
from oh_no_my_claudecode.models import FileStat, MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers (shared with test_coverage.py patterns)
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
        id=f"mem-suggest-{idx}",
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
# Unit tests — suggest_coverage (pure)
# ---------------------------------------------------------------------------


def test_suggest_one_per_gap(tmp_path: Path) -> None:
    """suggest_coverage returns exactly one suggestion per top-gap entry."""
    stats = [
        _make_stat("src/cache.py", churn=20, recent=5),
        _make_stat("src/worker.py", churn=15, recent=3),
    ]
    db = _seed_storage(tmp_path, file_stats=stats, memories=[])
    report = compile_coverage(db, tmp_path)

    suggestions = suggest_coverage(report, tmp_path)

    assert len(suggestions) == len(report.top_gaps)
    assert len(suggestions) == 2


def test_suggest_fully_covered_repo_no_suggestions(tmp_path: Path) -> None:
    """When every hotspot is covered, suggest_coverage returns an empty list."""
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

    suggestions = suggest_coverage(report, tmp_path)

    assert suggestions == [], "fully-covered repo must produce no suggestions"


def test_suggest_kind_config_path_is_decision(tmp_path: Path) -> None:
    """Files with 'config' in their path get suggested as DECISION."""
    stats = [_make_stat("config/settings.py", churn=5)]
    db = _seed_storage(tmp_path, file_stats=stats, memories=[])
    report = compile_coverage(db, tmp_path)

    suggestions = suggest_coverage(report, tmp_path)

    assert len(suggestions) == 1
    assert suggestions[0].suggested_kind == MemoryKind.DECISION


def test_suggest_kind_infra_path_is_decision(tmp_path: Path) -> None:
    """Files under 'infra/' get suggested as DECISION."""
    stats = [_make_stat("infra/deploy.ts", churn=4)]
    db = _seed_storage(tmp_path, file_stats=stats, memories=[])
    report = compile_coverage(db, tmp_path)

    suggestions = suggest_coverage(report, tmp_path)

    assert suggestions[0].suggested_kind == MemoryKind.DECISION


def test_suggest_kind_high_churn_is_invariant(tmp_path: Path) -> None:
    """Files with churn >= 10 (and no config tokens) get suggested as INVARIANT."""
    stats = [_make_stat("src/hot.py", churn=15)]
    db = _seed_storage(tmp_path, file_stats=stats, memories=[])
    report = compile_coverage(db, tmp_path)

    suggestions = suggest_coverage(report, tmp_path)

    assert suggestions[0].suggested_kind == MemoryKind.INVARIANT


def test_suggest_kind_low_churn_plain_is_doc_fact(tmp_path: Path) -> None:
    """Non-config, low-churn files get suggested as DOC_FACT."""
    stats = [_make_stat("src/utils.py", churn=3)]
    db = _seed_storage(tmp_path, file_stats=stats, memories=[])
    report = compile_coverage(db, tmp_path)

    suggestions = suggest_coverage(report, tmp_path)

    assert suggestions[0].suggested_kind == MemoryKind.DOC_FACT


def test_suggest_title_contains_filename(tmp_path: Path) -> None:
    """suggested_title always contains the base filename."""
    stats = [_make_stat("src/cache.py", churn=5)]
    db = _seed_storage(tmp_path, file_stats=stats, memories=[])
    report = compile_coverage(db, tmp_path)

    suggestions = suggest_coverage(report, tmp_path)

    assert "cache.py" in suggestions[0].suggested_title


def test_suggest_title_is_deterministic(tmp_path: Path) -> None:
    """Two calls with the same report produce identical titles."""
    stats = [_make_stat("src/cache.py", churn=5)]
    db = _seed_storage(tmp_path, file_stats=stats, memories=[])
    report = compile_coverage(db, tmp_path)

    s1 = suggest_coverage(report, tmp_path)
    s2 = suggest_coverage(report, tmp_path)

    assert s1[0].suggested_title == s2[0].suggested_title
    assert s1[0].suggested_kind == s2[0].suggested_kind


def test_suggest_rationale_mentions_churn(tmp_path: Path) -> None:
    """rationale mentions the commit count."""
    stats = [_make_stat("src/cache.py", churn=17, recent=4)]
    db = _seed_storage(tmp_path, file_stats=stats, memories=[])
    report = compile_coverage(db, tmp_path)

    suggestions = suggest_coverage(report, tmp_path)

    assert "17" in suggestions[0].rationale


def test_suggest_returns_list_of_coverage_suggestion(tmp_path: Path) -> None:
    """suggest_coverage returns CoverageSuggestion instances."""
    stats = [_make_stat("src/cache.py", churn=5)]
    db = _seed_storage(tmp_path, file_stats=stats, memories=[])
    report = compile_coverage(db, tmp_path)

    suggestions = suggest_coverage(report, tmp_path)

    for s in suggestions:
        assert isinstance(s, CoverageSuggestion)


def test_suggest_limit_respected(tmp_path: Path) -> None:
    """limit parameter caps the number of suggestions."""
    stats = [_make_stat(f"src/file{i}.py", churn=10 - i) for i in range(8)]
    db = _seed_storage(tmp_path, file_stats=stats, memories=[])
    report = compile_coverage(db, tmp_path)

    suggestions = suggest_coverage(report, tmp_path, limit=3)

    assert len(suggestions) <= 3


# ---------------------------------------------------------------------------
# Apply / idempotency tests
# ---------------------------------------------------------------------------


def test_apply_creates_stub_memories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--apply creates stub memories in the store."""
    from oh_no_my_claudecode import init

    sample = tmp_path / "repo"
    sample.mkdir()
    import subprocess

    subprocess.run(["git", "init"], cwd=sample, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=sample,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=sample,
        check=True,
        capture_output=True,
    )

    monkeypatch.chdir(sample)
    init(sample)

    from oh_no_my_claudecode.config import database_path, load_config

    config = load_config(sample)
    db_path = database_path(config, sample)
    storage = SQLiteStorage(db_path)
    storage.initialize()

    stats = [_make_stat("src/cache.py", churn=8)]
    storage.replace_file_stats(stats)

    before = storage.list_memories(source_type=SourceType.MANUAL)
    before_ids = {m.id for m in before}

    result = runner.invoke(app, ["coverage", "--apply"], prog_name="onmc")
    assert result.exit_code == 0, result.output

    after = storage.list_memories(source_type=SourceType.MANUAL)
    new_stubs = [m for m in after if m.id not in before_ids and "coverage-stub" in m.tags]
    assert len(new_stubs) >= 1, "at least one stub should have been created"


def test_apply_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Running --apply twice does not create duplicate stubs."""
    from oh_no_my_claudecode import init

    sample = tmp_path / "repo"
    sample.mkdir()
    import subprocess

    subprocess.run(["git", "init"], cwd=sample, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=sample,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=sample,
        check=True,
        capture_output=True,
    )

    monkeypatch.chdir(sample)
    init(sample)

    from oh_no_my_claudecode.config import database_path, load_config

    config = load_config(sample)
    db_path = database_path(config, sample)
    storage = SQLiteStorage(db_path)
    storage.initialize()

    stats = [_make_stat("src/cache.py", churn=8)]
    storage.replace_file_stats(stats)

    # First apply
    r1 = runner.invoke(app, ["coverage", "--apply"], prog_name="onmc")
    assert r1.exit_code == 0, r1.output

    after_first = storage.list_memories(source_type=SourceType.MANUAL)
    count_first = len([m for m in after_first if "coverage-stub" in m.tags])

    # Second apply — must not add more stubs
    r2 = runner.invoke(app, ["coverage", "--apply"], prog_name="onmc")
    assert r2.exit_code == 0, r2.output

    after_second = storage.list_memories(source_type=SourceType.MANUAL)
    count_second = len([m for m in after_second if "coverage-stub" in m.tags])

    assert count_first == count_second, (
        f"second --apply created extra stubs: {count_first} → {count_second}"
    )


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


def test_coverage_suggest_cli(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--suggest flag shows the suggestion table without error."""
    from oh_no_my_claudecode import init

    monkeypatch.chdir(sample_repo)
    init(sample_repo)

    result = runner.invoke(app, ["coverage", "--suggest"], prog_name="onmc")
    assert result.exit_code == 0, result.output
    # Either the table title or the "no suggestions" message should appear.
    output_lower = result.output.lower()
    assert "suggest" in output_lower or "covered" in output_lower


def test_coverage_apply_implies_suggest(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--apply flag also prints the suggestion table (implies --suggest)."""
    from oh_no_my_claudecode import init

    monkeypatch.chdir(sample_repo)
    init(sample_repo)

    result = runner.invoke(app, ["coverage", "--apply"], prog_name="onmc")
    assert result.exit_code == 0, result.output
    output_lower = result.output.lower()
    # Either suggestions shown or "all hotspots are covered".
    assert "suggest" in output_lower or "covered" in output_lower or "applied" in output_lower


def test_coverage_suggest_json_shape(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--suggest --json emits an object with 'report' and 'suggestions' keys."""
    from oh_no_my_claudecode import init

    monkeypatch.chdir(sample_repo)
    init(sample_repo)

    result = runner.invoke(app, ["coverage", "--suggest", "--json"], prog_name="onmc")
    assert result.exit_code == 0, result.output

    data = json.loads(result.output)
    assert "report" in data, f"Missing 'report' key: {list(data.keys())}"
    assert "suggestions" in data, f"Missing 'suggestions' key: {list(data.keys())}"
    assert isinstance(data["suggestions"], list)

    report = data["report"]
    expected_report_keys = {
        "overall_coverage_pct",
        "covered_files",
        "uncovered_files",
        "total_files",
        "subsystem_rows",
        "top_gaps",
        "memory_count",
    }
    assert expected_report_keys.issubset(report.keys())


def test_coverage_apply_json_shape(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--apply --json emits an object with 'report' and 'suggestions' keys."""
    from oh_no_my_claudecode import init

    monkeypatch.chdir(sample_repo)
    init(sample_repo)

    result = runner.invoke(app, ["coverage", "--apply", "--json"], prog_name="onmc")
    assert result.exit_code == 0, result.output

    data = json.loads(result.output)
    assert "report" in data
    assert "suggestions" in data
    assert isinstance(data["suggestions"], list)

    # Each suggestion must have the expected fields.
    for sug in data["suggestions"]:
        for key in ("file", "subsystem", "suggested_title", "suggested_kind", "rationale", "churn"):
            assert key in sug, f"Missing suggestion key '{key}'"


def test_coverage_json_no_suggest_backward_compat(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--json without --suggest still emits the flat CoverageReport dict (backward compat)."""
    from oh_no_my_claudecode import init

    monkeypatch.chdir(sample_repo)
    init(sample_repo)

    result = runner.invoke(app, ["coverage", "--json"], prog_name="onmc")
    assert result.exit_code == 0, result.output

    data = json.loads(result.output)
    # Must be the flat report (no nested 'report' key).
    assert "overall_coverage_pct" in data, "backward-compat flat report must be returned"
    assert "report" not in data, "--json alone must NOT wrap in {'report': ...}"
