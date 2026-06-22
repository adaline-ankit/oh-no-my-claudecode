"""Tests for the 'onmc savings' Memory Wrapped feature.

Covers:
- compile_savings returns correct counts (memories, skills, playbooks)
- token-reduction number is present and within valid range
- empty brain → zeroes/defaults gracefully (no divide-by-zero)
- compile_savings is deterministic with injected 'now'
- CLI 'onmc savings' exits 0
- CLI 'onmc savings --json' emits valid JSON with expected keys
- statusline now contains the memory-health segment (skills · ctx saved)
- Uninitialized repo: savings exits non-zero (graceful failure)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, Playbook, Skill, SourceType
from oh_no_my_claudecode.savings.compiler import SavingsResult, compile_savings
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory(*, idx: int, kind: MemoryKind = MemoryKind.DOC_FACT) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=f"mem-{idx}",
        kind=kind,
        title=f"Memory {idx}",
        summary=f"Summary {idx}",
        details=f"Details {idx}",
        source_type=SourceType.DOC,
        source_ref=f"src/file_{idx}.py",
        tags=[],
        confidence=0.8,
        created_at=now,
        updated_at=now,
    )


def _make_skill(*, idx: int) -> Skill:
    now = utc_now()
    return Skill(
        id=f"skill-{idx}",
        name=f"skill_{idx}",
        body=f"Do the thing {idx}.",
        trigger=f"When you need thing {idx}",
        tags=[],
        source_memory_ids=[],
        created_at=now,
        updated_at=now,
    )


def _make_playbook(*, idx: int) -> Playbook:
    now = utc_now()
    return Playbook(
        id=f"pb-{idx}",
        title=f"Playbook {idx}",
        trigger=f"When thing {idx} happens",
        steps=[f"Step {idx}.1", f"Step {idx}.2"],
        grounded_in=[],
        tags=[],
        confidence=0.75,
        created_at=now,
    )


def _seed_storage(
    tmp_path: Path,
    *,
    n_memories: int = 3,
    n_skills: int = 2,
    n_playbooks: int = 1,
) -> tuple[SQLiteStorage, Path]:
    db = SQLiteStorage(tmp_path / "mem.db")
    db.initialize()

    if n_memories > 0:
        db.upsert_memories([_make_memory(idx=i) for i in range(n_memories)])
    for i in range(n_skills):
        db.add_skill(_make_skill(idx=i))
    if n_playbooks > 0:
        db.upsert_playbooks([_make_playbook(idx=i) for i in range(n_playbooks)])

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    return db, repo_root


# ---------------------------------------------------------------------------
# compile_savings — unit tests
# ---------------------------------------------------------------------------


class TestCompileSavings:
    def test_memory_count_matches(self, tmp_path: Path) -> None:
        db, repo_root = _seed_storage(tmp_path, n_memories=4, n_skills=2, n_playbooks=1)
        result = compile_savings(db, repo_root, now="2026-06-23T00:00:00Z")
        assert result.memories_count == 4

    def test_skill_count_matches(self, tmp_path: Path) -> None:
        db, repo_root = _seed_storage(tmp_path, n_memories=2, n_skills=3, n_playbooks=0)
        result = compile_savings(db, repo_root)
        assert result.skills_count == 3

    def test_playbook_count_matches(self, tmp_path: Path) -> None:
        db, repo_root = _seed_storage(tmp_path, n_memories=2, n_skills=1, n_playbooks=2)
        result = compile_savings(db, repo_root)
        assert result.playbooks_count == 2

    def test_context_reduction_in_valid_range(self, tmp_path: Path) -> None:
        db, repo_root = _seed_storage(tmp_path, n_memories=3, n_skills=1, n_playbooks=0)
        result = compile_savings(db, repo_root)
        # Reduction must be between 0% and 100% (inclusive of 0 for empty brain scenarios).
        assert 0.0 <= result.context_tokens_pct_reduction <= 100.0

    def test_deterministic_with_injected_now(self, tmp_path: Path) -> None:
        db, repo_root = _seed_storage(tmp_path, n_memories=3, n_skills=1, n_playbooks=1)
        r1 = compile_savings(db, repo_root, now="2026-01-01T00:00:00Z")
        r2 = compile_savings(db, repo_root, now="2026-01-01T00:00:00Z")
        assert r1.context_tokens_pct_reduction == r2.context_tokens_pct_reduction
        assert r1.wasted_attempts_saved == r2.wasted_attempts_saved
        assert r1.memories_count == r2.memories_count

    def test_now_field_stored(self, tmp_path: Path) -> None:
        db, repo_root = _seed_storage(tmp_path, n_memories=1, n_skills=0, n_playbooks=0)
        result = compile_savings(db, repo_root, now="2026-06-23T12:00:00Z")
        assert result.now == "2026-06-23T12:00:00Z"

    def test_extra_notes_present(self, tmp_path: Path) -> None:
        db, repo_root = _seed_storage(tmp_path, n_memories=1, n_skills=0, n_playbooks=0)
        result = compile_savings(db, repo_root)
        # At least one honesty note must be present.
        assert len(result.extra_notes) >= 1

    def test_result_is_savings_result_type(self, tmp_path: Path) -> None:
        db, repo_root = _seed_storage(tmp_path, n_memories=2, n_skills=1, n_playbooks=0)
        result = compile_savings(db, repo_root)
        assert isinstance(result, SavingsResult)

    # --- empty brain ---

    def test_empty_brain_no_divide_by_zero(self, tmp_path: Path) -> None:
        """Empty memory store must not raise and must return sane zeroes."""
        db, repo_root = _seed_storage(tmp_path, n_memories=0, n_skills=0, n_playbooks=0)
        result = compile_savings(db, repo_root)
        assert result.memories_count == 0
        assert result.skills_count == 0
        assert result.playbooks_count == 0
        assert 0.0 <= result.context_tokens_pct_reduction <= 100.0

    def test_empty_brain_covered_hotspots_zero(self, tmp_path: Path) -> None:
        db, repo_root = _seed_storage(tmp_path, n_memories=0, n_skills=0, n_playbooks=0)
        result = compile_savings(db, repo_root)
        assert result.covered_hotspots == 0
        assert result.total_hotspots == 0

    def test_empty_brain_top_covered_names_empty(self, tmp_path: Path) -> None:
        db, repo_root = _seed_storage(tmp_path, n_memories=0, n_skills=0, n_playbooks=0)
        result = compile_savings(db, repo_root)
        assert result.top_covered_names == []


# ---------------------------------------------------------------------------
# CLI: onmc savings
# ---------------------------------------------------------------------------


class TestSavingsCommand:
    def test_exit_code_0_on_initialized_repo(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        svc = OnmcService(cwd=sample_repo)
        svc.init_project()
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(app, ["savings"], catch_exceptions=False)
        assert result.exit_code == 0

    def test_card_output_contains_wrapped(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        svc = OnmcService(cwd=sample_repo)
        svc.init_project()
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(app, ["savings"], catch_exceptions=False)
        assert result.exit_code == 0
        # Panel title must be present
        assert "Memory Wrapped" in result.output or "memories" in result.output.lower()

    def test_json_output_valid_json(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        svc = OnmcService(cwd=sample_repo)
        svc.init_project()
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(app, ["savings", "--json"], catch_exceptions=False)
        assert result.exit_code == 0
        data = json.loads(result.output)
        # Required keys must be present
        assert "memories_count" in data
        assert "skills_count" in data
        assert "playbooks_count" in data
        assert "context_tokens_pct_reduction" in data
        assert "wasted_attempts_saved" in data

    def test_json_output_types(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        svc = OnmcService(cwd=sample_repo)
        svc.init_project()
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(app, ["savings", "--json"], catch_exceptions=False)
        data = json.loads(result.output)
        assert isinstance(data["memories_count"], int)
        assert isinstance(data["skills_count"], int)
        assert isinstance(data["playbooks_count"], int)
        assert isinstance(data["context_tokens_pct_reduction"], float)
        assert isinstance(data["top_covered_names"], list)

    def test_uninitialized_repo_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["savings"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Statusline: memory-health segment
# ---------------------------------------------------------------------------


class TestStatuslineMemoryHealthSegment:
    def test_statusline_contains_skills(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Statusline must now include 'skills' and 'ctx saved' segment."""
        from oh_no_my_claudecode.core.service import OnmcService

        svc = OnmcService(cwd=sample_repo)
        svc.init_project()
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(app, ["statusline"], catch_exceptions=False)
        assert result.exit_code == 0
        output = result.output.strip()
        # Core existing fields must still be present
        assert "mem" in output
        assert "fresh" in output
        # New memory-health segment
        assert "skills" in output

    def test_statusline_contains_ctx_saved(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        svc = OnmcService(cwd=sample_repo)
        svc.init_project()
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(app, ["statusline"], catch_exceptions=False)
        assert result.exit_code == 0
        output = result.output.strip()
        assert "ctx saved" in output
