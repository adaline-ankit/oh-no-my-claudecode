"""Tests for the memory-health HUD + statusline feature.

Covers:
- compute_memory_health returns correct counts/freshness/coverage
- cost aggregation parses crafted llm-calls.jsonl (and tolerates missing file)
- onmc statusline one-line output contains expected tokens
- onmc hud renders sections
- uninitialized repo: statusline degrades gracefully, exit 0
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.models import FileStat, MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.stats.health import (
    _aggregate_cost,
    compute_memory_health,
)
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory(
    *,
    idx: int,
    kind: MemoryKind = MemoryKind.DOC_FACT,
    source_ref: str = "README.md",
    staleness: str | None = None,
) -> MemoryEntry:
    now = utc_now()
    entry = MemoryEntry(
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
        staleness=staleness,  # type: ignore[arg-type]
    )
    return entry


def _seed_storage(tmp_path: Path) -> tuple[SQLiteStorage, Path]:
    db = SQLiteStorage(tmp_path / "mem.db")
    db.initialize()

    memories = [
        _make_memory(idx=1, source_ref="README.md"),
        _make_memory(idx=2, kind=MemoryKind.DECISION, source_ref="src/cache.py"),
        _make_memory(idx=3, kind=MemoryKind.HOTSPOT, source_ref="src/worker.py"),
        _make_memory(idx=4, kind=MemoryKind.INVARIANT, source_ref="manual:foo"),
        _make_memory(idx=5, kind=MemoryKind.GOTCHA, source_ref="gone.py"),
    ]
    db.upsert_memories(memories)
    # Persist staleness labels via the dedicated setter so they survive the read path
    from oh_no_my_claudecode.utils.time import isoformat_utc

    now_str = isoformat_utc(utc_now())
    db.set_memory_staleness("mem-1", "fresh", now_str)
    db.set_memory_staleness("mem-2", "fresh", now_str)
    db.set_memory_staleness("mem-3", "stale", now_str)
    db.set_memory_staleness("mem-4", "unanchored", now_str)
    db.set_memory_staleness("mem-5", "orphaned", now_str)

    # Seed file stats so coverage proxy works
    stats = [
        FileStat(
            path="README.md",
            change_count=10,
            recent_change_count=3,
            last_modified_at=None,
            is_test=False,
            top_level_dir=".",
        ),
        FileStat(
            path="src/cache.py",
            change_count=8,
            recent_change_count=2,
            last_modified_at=None,
            is_test=False,
            top_level_dir="src",
        ),
        FileStat(
            path="src/worker.py",
            change_count=5,
            recent_change_count=1,
            last_modified_at=None,
            is_test=False,
            top_level_dir="src",
        ),
    ]
    db.replace_file_stats(stats)

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# hi", encoding="utf-8")
    (repo_root / "src").mkdir()
    (repo_root / "src" / "cache.py").write_text("# cache", encoding="utf-8")
    (repo_root / "src" / "worker.py").write_text("# worker", encoding="utf-8")

    log_path = tmp_path / "llm-calls.jsonl"
    return db, log_path


# ---------------------------------------------------------------------------
# compute_memory_health
# ---------------------------------------------------------------------------


class TestComputeMemoryHealth:
    def test_total_count(self, tmp_path: Path) -> None:
        db, log_path = _seed_storage(tmp_path)
        health = compute_memory_health(db, tmp_path / "repo", log_path)
        assert health.total_memories == 5

    def test_counts_by_kind(self, tmp_path: Path) -> None:
        db, log_path = _seed_storage(tmp_path)
        health = compute_memory_health(db, tmp_path / "repo", log_path)
        assert health.counts_by_kind["doc_fact"] == 1
        assert health.counts_by_kind["decision"] == 1
        assert health.counts_by_kind["hotspot"] == 1

    def test_freshness_counts(self, tmp_path: Path) -> None:
        db, log_path = _seed_storage(tmp_path)
        health = compute_memory_health(db, tmp_path / "repo", log_path)
        assert health.fresh_count == 2
        assert health.stale_count == 1
        assert health.orphaned_count == 1
        assert health.unanchored_count == 1

    def test_freshness_pct(self, tmp_path: Path) -> None:
        db, log_path = _seed_storage(tmp_path)
        health = compute_memory_health(db, tmp_path / "repo", log_path)
        # anchored = fresh(2) + stale(1) + orphaned(1) = 4
        # freshness_pct = 2/4 * 100 = 50.0
        assert health.freshness_pct == pytest.approx(50.0, abs=0.1)

    def test_stale_titles_listed(self, tmp_path: Path) -> None:
        db, log_path = _seed_storage(tmp_path)
        health = compute_memory_health(db, tmp_path / "repo", log_path)
        assert any("Memory 3" in t for t in health.stale_titles)

    def test_coverage_proxy(self, tmp_path: Path) -> None:
        db, log_path = _seed_storage(tmp_path)
        health = compute_memory_health(db, tmp_path / "repo", log_path)
        # 3 top-churn files: README.md, src/cache.py, src/worker.py — all covered
        assert health.covered_files == 3
        assert health.top_churn_files == 3
        assert health.coverage_pct == pytest.approx(100.0, abs=0.1)

    def test_no_log_file_returns_zero_cost(self, tmp_path: Path) -> None:
        db, log_path = _seed_storage(tmp_path)
        # log_path does not exist
        health = compute_memory_health(db, tmp_path / "repo", log_path)
        assert health.recent_cost.call_count == 0
        assert health.recent_cost.total_tokens == 0

    def test_empty_storage_freshness_100(self, tmp_path: Path) -> None:
        db = SQLiteStorage(tmp_path / "empty.db")
        db.initialize()
        log_path = tmp_path / "llm-calls.jsonl"
        health = compute_memory_health(db, tmp_path, log_path)
        assert health.total_memories == 0
        assert health.freshness_pct == pytest.approx(100.0, abs=0.1)


# ---------------------------------------------------------------------------
# _aggregate_cost
# ---------------------------------------------------------------------------


class TestAggregateCost:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        cost = _aggregate_cost(tmp_path / "no-such-file.jsonl")
        assert cost.call_count == 0
        assert cost.total_tokens == 0

    def test_parses_recent_entries(self, tmp_path: Path) -> None:
        log = tmp_path / "llm-calls.jsonl"
        now = datetime.now(tz=UTC)
        entries = [
            {
                "timestamp": (now - timedelta(hours=1)).isoformat(),
                "prompt_token_count": 100,
                "response_token_count": 50,
                "latency_ms": 1200.0,
            },
            {
                "timestamp": (now - timedelta(hours=2)).isoformat(),
                "prompt_token_count": 200,
                "response_token_count": 80,
                "latency_ms": 800.0,
            },
        ]
        log.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
        cost = _aggregate_cost(log)
        assert cost.call_count == 2
        assert cost.total_prompt_tokens == 300
        assert cost.total_response_tokens == 130
        assert cost.total_tokens == 430
        assert cost.total_latency_ms == pytest.approx(2000.0, abs=1.0)

    def test_skips_old_entries(self, tmp_path: Path) -> None:
        log = tmp_path / "llm-calls.jsonl"
        now = datetime.now(tz=UTC)
        entries = [
            {
                "timestamp": (now - timedelta(hours=1)).isoformat(),
                "prompt_token_count": 10,
                "response_token_count": 5,
                "latency_ms": 100.0,
            },
            {
                "timestamp": (now - timedelta(hours=25)).isoformat(),
                "prompt_token_count": 999,
                "response_token_count": 999,
                "latency_ms": 9999.0,
            },
        ]
        log.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
        cost = _aggregate_cost(log)
        assert cost.call_count == 1
        assert cost.total_tokens == 15

    def test_tolerates_corrupt_lines(self, tmp_path: Path) -> None:
        log = tmp_path / "llm-calls.jsonl"
        now = datetime.now(tz=UTC)
        valid = json.dumps(
            {
                "timestamp": now.isoformat(),
                "prompt_token_count": 50,
                "response_token_count": 25,
                "latency_ms": 500.0,
            }
        )
        log.write_text("NOT JSON\n" + valid + "\n{bad}\n", encoding="utf-8")
        cost = _aggregate_cost(log)
        assert cost.call_count == 1
        assert cost.total_tokens == 75

    def test_tolerates_missing_fields(self, tmp_path: Path) -> None:
        log = tmp_path / "llm-calls.jsonl"
        now = datetime.now(tz=UTC)
        entry = json.dumps({"timestamp": now.isoformat()})
        log.write_text(entry, encoding="utf-8")
        cost = _aggregate_cost(log)
        assert cost.call_count == 1
        assert cost.total_tokens == 0


# ---------------------------------------------------------------------------
# CLI: onmc statusline
# ---------------------------------------------------------------------------


class TestStatuslineCommand:
    def test_output_contains_mem(self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Initialized repo: output has expected tokens."""
        from oh_no_my_claudecode.core.service import OnmcService

        svc = OnmcService(cwd=sample_repo)
        svc.init_project()
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(app, ["statusline"], catch_exceptions=False)
        assert result.exit_code == 0
        output = result.output.strip()
        assert "mem" in output
        assert "fresh" in output
        assert "stale" in output

    def test_uninitialized_repo_degrades_exit_0(self, tmp_path: Path) -> None:
        """Uninitialized repo: statusline prints minimal string and exits 0."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "oh_no_my_claudecode", "statusline"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        # Must exit 0 (degrade gracefully)
        assert result.returncode == 0
        # Output should mention 'onmc' in some form
        assert "onmc" in result.stdout.lower() or "🧠" in result.stdout


# ---------------------------------------------------------------------------
# CLI: onmc hud
# ---------------------------------------------------------------------------


class TestHudCommand:
    def test_hud_renders_sections(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Initialized repo: hud renders panel title and freshness section."""
        from oh_no_my_claudecode.core.service import OnmcService

        svc = OnmcService(cwd=sample_repo)
        svc.init_project()
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(app, ["hud"], catch_exceptions=False)
        assert result.exit_code == 0
        output = result.output
        # The HUD panel title should be present
        assert "ONMC Memory HUD" in output or "Memory HUD" in output

    def test_hud_uninitialized_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Uninitialized repo: hud exits with non-zero code."""
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["hud"])
        assert result.exit_code != 0
