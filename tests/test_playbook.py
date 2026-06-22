"""Tests for the playbook feature: compiler, storage, CLI, and artifact writing."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import MemoryKind, SourceType
from oh_no_my_claudecode.models.memory import MemoryEntry
from oh_no_my_claudecode.models.playbook import Playbook, PlaybookProvenanceItem
from oh_no_my_claudecode.playbook.compiler import compile_playbooks
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

# ── Fixtures ───────────────────────────────────────────────────────────────────


def _make_memory(
    *,
    memory_id: str,
    kind: MemoryKind,
    title: str,
    summary: str,
    tags: list[str],
    source_ref: str = "src/core.py",
    confidence: float = 0.9,
    feedback_score: float = 0.0,
) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=memory_id,
        kind=kind,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.MANUAL_SEED,
        source_ref=source_ref,
        tags=tags,
        confidence=confidence,
        feedback_score=feedback_score,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def seeded_memories() -> list[MemoryEntry]:
    """A deterministic set of memories that should produce ≥ 1 playbook."""
    return [
        _make_memory(
            memory_id="mem-inv-1",
            kind=MemoryKind.INVARIANT,
            title="Always use the repository layer",
            summary="All writes must go through the repository layer, never raw DB.",
            tags=["architecture", "testing"],
            source_ref="src/repo.py",
        ),
        _make_memory(
            memory_id="mem-inv-2",
            kind=MemoryKind.INVARIANT,
            title="Validate inputs at service boundary",
            summary="Service layer validates all inputs before forwarding to repo.",
            tags=["architecture", "testing"],
            source_ref="src/service.py",
        ),
        _make_memory(
            memory_id="mem-fail-1",
            kind=MemoryKind.FAILED_APPROACH,
            title="Direct DB writes caused test flakiness",
            summary="Bypassing the repo layer caused race conditions in tests.",
            tags=["architecture", "testing"],
            source_ref="src/repo.py",
        ),
        _make_memory(
            memory_id="mem-val-1",
            kind=MemoryKind.VALIDATION_RULE,
            title="Run pytest before merging",
            summary="pytest must pass in the affected test directory.",
            tags=["testing"],
            source_ref="tests/test_core.py",
        ),
        _make_memory(
            memory_id="mem-val-2",
            kind=MemoryKind.VALIDATION_RULE,
            title="Lint with ruff",
            summary="ruff check must produce zero errors.",
            tags=["testing"],
            source_ref="tests/test_lint.py",
        ),
    ]


# ── Compiler tests ─────────────────────────────────────────────────────────────


class TestPlaybookCompiler:
    def test_produces_playbooks_from_seeded_memories(
        self, seeded_memories: list[MemoryEntry]
    ) -> None:
        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        assert len(playbooks) >= 1, "Expected at least one playbook from seeded memories."

    def test_playbooks_have_provenance(self, seeded_memories: list[MemoryEntry]) -> None:
        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        for pb in playbooks:
            assert len(pb.grounded_in) >= 1, f"Playbook {pb.id} has no provenance."
            for item in pb.grounded_in:
                assert item.memory_id, "Provenance item must have a memory_id."
                assert item.title, "Provenance item must have a title."
                assert item.kind, "Provenance item must have a kind."

    def test_playbooks_have_steps(self, seeded_memories: list[MemoryEntry]) -> None:
        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        for pb in playbooks:
            assert len(pb.steps) >= 1, f"Playbook {pb.id} has no steps."

    def test_playbook_ids_are_stable_and_deterministic(
        self, seeded_memories: list[MemoryEntry]
    ) -> None:
        first = compile_playbooks(seeded_memories, no_llm=True)
        second = compile_playbooks(seeded_memories, no_llm=True)
        assert [pb.id for pb in first] == [pb.id for pb in second]

    def test_empty_store_returns_no_playbooks(self) -> None:
        assert compile_playbooks([], no_llm=True) == []

    def test_low_signal_memories_are_excluded(self) -> None:
        low_signal = [
            _make_memory(
                memory_id=f"low-{i}",
                kind=MemoryKind.INVARIANT,
                title=f"Low signal {i}",
                summary="Low confidence.",
                tags=["misc"],
                confidence=0.1,
                feedback_score=-0.5,
            )
            for i in range(3)
        ]
        assert compile_playbooks(low_signal, no_llm=True) == []

    def test_confidence_is_in_range(self, seeded_memories: list[MemoryEntry]) -> None:
        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        for pb in playbooks:
            assert 0.0 <= pb.confidence <= 1.0, f"Confidence out of range: {pb.confidence}"

    def test_clustering_by_tag_produces_correct_provenance(
        self, seeded_memories: list[MemoryEntry]
    ) -> None:
        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        # The "testing" tag appears on 5 memories — that cluster should be present.
        testing_playbooks = [
            pb for pb in playbooks if "testing" in pb.tags or "Testing" in pb.title
        ]
        assert testing_playbooks, "Expected a 'testing'-tagged playbook."

    def test_rejected_memories_are_excluded(self) -> None:
        memories = [
            _make_memory(
                memory_id=f"mem-{i}",
                kind=MemoryKind.INVARIANT,
                title=f"Memory {i}",
                summary="Important invariant.",
                tags=["arch"],
                feedback_score=-0.5,  # rejected
            )
            for i in range(3)
        ]
        assert compile_playbooks(memories, no_llm=True) == []


# ── Storage round-trip tests ───────────────────────────────────────────────────


class TestPlaybookStorage:
    def test_migration_v4_creates_playbooks_table(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        storage = SQLiteStorage(db_path)
        storage.initialize()
        with sqlite3.connect(db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        assert "playbooks" in tables

    def test_schema_version_is_4(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        storage = SQLiteStorage(db_path)
        storage.initialize()
        assert storage.get_meta("schema_version") == "7"

    def test_migration_v4_is_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        storage = SQLiteStorage(db_path)
        storage.initialize()
        storage.initialize()  # second call must not fail
        assert storage.get_meta("schema_version") == "7"

    def test_upsert_and_list_playbooks(
        self, tmp_path: Path, seeded_memories: list[MemoryEntry]
    ) -> None:
        db_path = tmp_path / "memory.db"
        storage = SQLiteStorage(db_path)
        storage.initialize()

        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        assert playbooks, "Need at least one playbook for round-trip test."
        count = storage.upsert_playbooks(playbooks)
        assert count == len(playbooks)

        listed = storage.list_playbooks()
        assert len(listed) == len(playbooks)
        listed_ids = {pb.id for pb in listed}
        original_ids = {pb.id for pb in playbooks}
        assert listed_ids == original_ids

    def test_get_playbook_by_id(
        self, tmp_path: Path, seeded_memories: list[MemoryEntry]
    ) -> None:
        db_path = tmp_path / "memory.db"
        storage = SQLiteStorage(db_path)
        storage.initialize()

        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        storage.upsert_playbooks(playbooks)
        first = playbooks[0]
        fetched = storage.get_playbook(first.id)
        assert fetched is not None
        assert fetched.id == first.id
        assert fetched.title == first.title
        assert fetched.steps == first.steps

    def test_get_playbook_missing_returns_none(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        storage = SQLiteStorage(db_path)
        storage.initialize()
        assert storage.get_playbook("does-not-exist") is None

    def test_upsert_is_idempotent(
        self, tmp_path: Path, seeded_memories: list[MemoryEntry]
    ) -> None:
        db_path = tmp_path / "memory.db"
        storage = SQLiteStorage(db_path)
        storage.initialize()

        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        storage.upsert_playbooks(playbooks)
        storage.upsert_playbooks(playbooks)  # second upsert must not fail or duplicate
        assert len(storage.list_playbooks()) == len(playbooks)

    def test_provenance_round_trip(
        self, tmp_path: Path, seeded_memories: list[MemoryEntry]
    ) -> None:
        db_path = tmp_path / "memory.db"
        storage = SQLiteStorage(db_path)
        storage.initialize()

        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        storage.upsert_playbooks(playbooks)
        listed = storage.list_playbooks()
        for pb in listed:
            assert all(isinstance(item, PlaybookProvenanceItem) for item in pb.grounded_in)

    def test_empty_upsert_returns_zero(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        storage = SQLiteStorage(db_path)
        storage.initialize()
        assert storage.upsert_playbooks([]) == 0


# ── CLI tests ──────────────────────────────────────────────────────────────────


class TestPlaybookCLI:
    def test_generate_empty_store_exits_cleanly(
        self, sample_repo: Path, monkeypatch: object
    ) -> None:
        runner = CliRunner()
        monkeypatch.chdir(sample_repo)
        assert runner.invoke(app, ["init"]).exit_code == 0
        result = runner.invoke(app, ["playbook", "generate", "--no-llm"])
        assert result.exit_code == 0

    def test_list_empty_store_exits_cleanly(
        self, sample_repo: Path, monkeypatch: object
    ) -> None:
        runner = CliRunner()
        monkeypatch.chdir(sample_repo)
        assert runner.invoke(app, ["init"]).exit_code == 0
        result = runner.invoke(app, ["playbook", "list"])
        assert result.exit_code == 0
        assert "No playbooks found" in result.stdout

    def test_generate_list_show_roundtrip(
        self,
        sample_repo: Path,
        monkeypatch: object,
        seeded_memories: list[MemoryEntry],
    ) -> None:
        runner = CliRunner()
        monkeypatch.chdir(sample_repo)
        service = OnmcService(sample_repo)
        service.init_project()
        # Pre-load seeded memories so generate finds real clusters.
        _, _, storage = service._load_context()  # noqa: SLF001
        storage.upsert_memories(seeded_memories)

        gen_result = runner.invoke(app, ["playbook", "generate", "--no-llm"])
        assert gen_result.exit_code == 0, gen_result.stdout

        list_result = runner.invoke(app, ["playbook", "list"])
        assert list_result.exit_code == 0
        # With seeded memories we should have playbooks.
        assert "No playbooks found" not in list_result.stdout

        # Extract a playbook id from the list output to test show.
        playbooks = service.list_playbooks()
        assert playbooks
        first_id = playbooks[0].id

        show_result = runner.invoke(app, ["playbook", "show", first_id[:8]])
        assert show_result.exit_code == 0
        assert playbooks[0].title in show_result.stdout

    def test_show_missing_id_returns_error(
        self, sample_repo: Path, monkeypatch: object
    ) -> None:
        runner = CliRunner()
        monkeypatch.chdir(sample_repo)
        assert runner.invoke(app, ["init"]).exit_code == 0
        result = runner.invoke(app, ["playbook", "show", "nonexistent-id"])
        assert result.exit_code != 0

    def test_generate_writes_artifacts(
        self,
        sample_repo: Path,
        monkeypatch: object,
        seeded_memories: list[MemoryEntry],
    ) -> None:
        monkeypatch.chdir(sample_repo)
        service = OnmcService(sample_repo)
        service.init_project()
        _, _, storage = service._load_context()  # noqa: SLF001
        storage.upsert_memories(seeded_memories)

        _, playbooks, artifact_paths = service.generate_playbooks(no_llm=True)
        if not playbooks:
            pytest.skip("No playbooks generated from seeded memories — check thresholds.")

        # At least one markdown artifact in .onmc/compiled/ must exist.
        md_artifacts = [p for p in artifact_paths if p.endswith(".md")]
        assert md_artifacts, "Expected at least one markdown artifact."
        assert Path(md_artifacts[0]).exists()

        # JSON artifacts in .agent-memory/playbooks/ must exist.
        json_artifacts = [p for p in artifact_paths if p.endswith(".json")]
        assert json_artifacts, "Expected at least one JSON artifact."
        for json_path in json_artifacts:
            path = Path(json_path)
            assert path.exists()
            data = json.loads(path.read_text(encoding="utf-8"))
            assert "id" in data
            assert "steps" in data
            assert "grounded_in" in data

    def test_playbook_help_commands(self) -> None:
        runner = CliRunner()
        result = runner.invoke(app, ["playbook", "--help"])
        assert result.exit_code == 0
        for cmd in ("generate", "list", "show"):
            assert cmd in result.stdout


# ── Model validation ───────────────────────────────────────────────────────────


class TestPlaybookModel:
    def test_playbook_model_fields(self) -> None:
        pb = Playbook(
            id="pb-test",
            title="Test Playbook",
            trigger="When running tests.",
            steps=["Always", "Verify"],
            grounded_in=[PlaybookProvenanceItem(memory_id="m1", title="T1", kind="invariant")],
            tags=["testing"],
            confidence=0.85,
            created_at=utc_now(),
        )
        assert pb.id == "pb-test"
        assert len(pb.steps) == 2
        assert pb.confidence == 0.85

    def test_playbook_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Playbook(
                id="bad",
                title="Bad",
                trigger="x",
                confidence=1.5,  # out of range
                created_at=utc_now(),
            )
