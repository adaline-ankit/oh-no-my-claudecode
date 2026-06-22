"""Tests for the skill feature: migration, model, storage CRUD, promoter, service, CLI."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import MemoryKind, Skill, SourceType
from oh_no_my_claudecode.models.memory import MemoryEntry
from oh_no_my_claudecode.playbook.compiler import compile_playbooks
from oh_no_my_claudecode.skill.promoter import (
    auto_promote_recurring,
    promote_playbook_to_skill,
    rank_skills,
)
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

# ── Helpers ────────────────────────────────────────────────────────────────────

_runner = CliRunner()


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


def _make_skill(
    *,
    skill_id: str = "sk_test1234",
    name: str = "Test Skill",
    body: str = "1. Do the thing.",
    trigger: str = "When testing things.",
    tags: list[str] | None = None,
    files: list[str] | None = None,
    confidence: float = 0.8,
    use_count: int = 0,
    success_count: int = 0,
    auto_inject: bool = True,
) -> Skill:
    now = utc_now()
    return Skill(
        id=skill_id,
        name=name,
        body=body,
        trigger=trigger,
        tags=tags or ["testing"],
        files=files or ["src/"],
        source_memory_ids=["mem-1"],
        use_count=use_count,
        success_count=success_count,
        confidence=confidence,
        auto_inject=auto_inject,
        created_at=now,
        updated_at=now,
        last_used_at=None,
    )


@pytest.fixture
def seeded_memories() -> list[MemoryEntry]:
    """A deterministic set of memories that produce playbooks and skills."""
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


@pytest.fixture
def initialized_repo(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialize ONMC in sample_repo and return the path."""
    monkeypatch.chdir(sample_repo)
    svc = OnmcService(sample_repo)
    svc.init_project()
    return sample_repo


# ── Migration tests ────────────────────────────────────────────────────────────


class TestMigrationV7:
    def test_creates_skills_table(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        storage = SQLiteStorage(db_path)
        storage.initialize()
        with sqlite3.connect(db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        assert "skills" in tables

    def test_schema_version_is_7(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        storage = SQLiteStorage(db_path)
        storage.initialize()
        assert storage.get_meta("schema_version") == "7"

    def test_migration_v7_is_idempotent(self, tmp_path: Path) -> None:
        """Re-initializing must not fail or duplicate the table."""
        db_path = tmp_path / "memory.db"
        storage = SQLiteStorage(db_path)
        storage.initialize()
        storage.initialize()  # second call must be a no-op
        assert storage.get_meta("schema_version") == "7"

    def test_skills_table_columns(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        storage = SQLiteStorage(db_path)
        storage.initialize()
        with sqlite3.connect(db_path) as conn:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(skills)")
            }
        expected = {
            "id", "name", "body", "trigger", "tags_json", "files_json",
            "source_memory_ids_json", "use_count", "success_count",
            "confidence", "auto_inject", "created_at", "updated_at", "last_used_at",
        }
        assert expected.issubset(columns)


# ── Storage CRUD tests ─────────────────────────────────────────────────────────


class TestSkillStorage:
    def test_add_and_get_skill(self, tmp_path: Path) -> None:
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        sk = _make_skill()
        storage.add_skill(sk)
        fetched = storage.get_skill(sk.id)
        assert fetched is not None
        assert fetched.id == sk.id
        assert fetched.name == sk.name
        assert fetched.body == sk.body
        assert fetched.trigger == sk.trigger
        assert fetched.tags == sk.tags

    def test_get_skill_missing_returns_none(self, tmp_path: Path) -> None:
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        assert storage.get_skill("does-not-exist") is None

    def test_add_duplicate_raises_value_error(self, tmp_path: Path) -> None:
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        sk = _make_skill()
        storage.add_skill(sk)
        with pytest.raises(ValueError, match="already exists"):
            storage.add_skill(sk)

    def test_list_skills_empty(self, tmp_path: Path) -> None:
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        assert storage.list_skills() == []

    def test_list_skills_ordered_by_confidence(self, tmp_path: Path) -> None:
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        storage.add_skill(_make_skill(skill_id="sk_a", name="A", confidence=0.4))
        storage.add_skill(_make_skill(skill_id="sk_b", name="B", confidence=0.9))
        storage.add_skill(_make_skill(skill_id="sk_c", name="C", confidence=0.6))
        listed = storage.list_skills()
        confs = [sk.confidence for sk in listed]
        assert confs == sorted(confs, reverse=True)

    def test_update_skill(self, tmp_path: Path) -> None:
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        sk = _make_skill()
        storage.add_skill(sk)
        updated = sk.model_copy(update={"name": "Updated Name", "confidence": 0.99})
        storage.update_skill(updated)
        fetched = storage.get_skill(sk.id)
        assert fetched is not None
        assert fetched.name == "Updated Name"
        assert abs(fetched.confidence - 0.99) < 1e-6

    def test_update_skill_missing_raises_lookup_error(self, tmp_path: Path) -> None:
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        sk = _make_skill()
        with pytest.raises(LookupError, match="not found"):
            storage.update_skill(sk)

    def test_record_skill_use_success(self, tmp_path: Path) -> None:
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        sk = _make_skill()
        storage.add_skill(sk)
        updated = storage.record_skill_use(sk.id, success=True)
        assert updated.use_count == 1
        assert updated.success_count == 1
        assert updated.last_used_at is not None

    def test_record_skill_use_failure(self, tmp_path: Path) -> None:
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        sk = _make_skill()
        storage.add_skill(sk)
        updated = storage.record_skill_use(sk.id, success=False)
        assert updated.use_count == 1
        assert updated.success_count == 0

    def test_record_skill_use_missing_raises_lookup_error(self, tmp_path: Path) -> None:
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        with pytest.raises(LookupError, match="not found"):
            storage.record_skill_use("does-not-exist", success=True)

    def test_skill_round_trip_tags_and_files(self, tmp_path: Path) -> None:
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        sk = _make_skill(tags=["a", "b", "c"], files=["src/", "tests/"])
        storage.add_skill(sk)
        fetched = storage.get_skill(sk.id)
        assert fetched is not None
        assert fetched.tags == ["a", "b", "c"]
        assert fetched.files == ["src/", "tests/"]

    def test_auto_inject_persisted(self, tmp_path: Path) -> None:
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        sk = _make_skill(auto_inject=False)
        storage.add_skill(sk)
        fetched = storage.get_skill(sk.id)
        assert fetched is not None
        assert fetched.auto_inject is False


# ── Promoter tests ─────────────────────────────────────────────────────────────


class TestPromotePlaybookToSkill:
    def test_promote_carries_provenance(
        self, seeded_memories: list[MemoryEntry]
    ) -> None:
        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        assert playbooks, "Need at least one playbook."
        pb = playbooks[0]
        skill = promote_playbook_to_skill(pb)
        assert skill.source_memory_ids == [item.memory_id for item in pb.grounded_in]

    def test_promote_copies_trigger(self, seeded_memories: list[MemoryEntry]) -> None:
        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        pb = playbooks[0]
        skill = promote_playbook_to_skill(pb)
        assert skill.trigger == pb.trigger

    def test_promote_copies_tags(self, seeded_memories: list[MemoryEntry]) -> None:
        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        pb = playbooks[0]
        skill = promote_playbook_to_skill(pb)
        assert skill.tags == pb.tags

    def test_promote_custom_name(self, seeded_memories: list[MemoryEntry]) -> None:
        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        pb = playbooks[0]
        skill = promote_playbook_to_skill(pb, name="My Custom Skill")
        assert skill.name == "My Custom Skill"

    def test_promote_default_name_from_title(
        self, seeded_memories: list[MemoryEntry]
    ) -> None:
        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        pb = playbooks[0]
        skill = promote_playbook_to_skill(pb)
        assert skill.name == pb.title

    def test_promote_body_from_steps(self, seeded_memories: list[MemoryEntry]) -> None:
        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        pb = playbooks[0]
        skill = promote_playbook_to_skill(pb)
        # Body should contain numbered step markers.
        assert "1." in skill.body

    def test_promote_confidence_from_playbook(
        self, seeded_memories: list[MemoryEntry]
    ) -> None:
        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        pb = playbooks[0]
        skill = promote_playbook_to_skill(pb)
        assert abs(skill.confidence - pb.confidence) < 1e-6

    def test_promote_id_is_stable(self, seeded_memories: list[MemoryEntry]) -> None:
        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        pb = playbooks[0]
        id1 = promote_playbook_to_skill(pb).id
        id2 = promote_playbook_to_skill(pb).id
        assert id1 == id2

    def test_promote_auto_inject_defaults_true(
        self, seeded_memories: list[MemoryEntry]
    ) -> None:
        playbooks = compile_playbooks(seeded_memories, no_llm=True)
        pb = playbooks[0]
        skill = promote_playbook_to_skill(pb)
        assert skill.auto_inject is True


# ── Auto-promote tests ─────────────────────────────────────────────────────────


class TestAutoPromoteRecurring:
    def test_auto_promote_finds_fail_fix_pattern(
        self, tmp_path: Path, seeded_memories: list[MemoryEntry]
    ) -> None:
        """Seeded memories have FAILED_APPROACH + INVARIANT under shared tags."""
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        storage.upsert_memories(seeded_memories)
        skills = auto_promote_recurring(storage)
        assert len(skills) >= 1, "Expected at least one auto-promoted skill."

    def test_auto_promote_skips_already_sourced(
        self, tmp_path: Path, seeded_memories: list[MemoryEntry]
    ) -> None:
        """Memories already captured by an existing skill should not be re-promoted."""
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        storage.upsert_memories(seeded_memories)
        # First pass.
        first = auto_promote_recurring(storage)
        for sk in first:
            storage.add_skill(sk)
        # Second pass: all source memories are now captured.
        second = auto_promote_recurring(storage)
        # IDs from first should not appear again.
        first_ids = {sk.id for sk in first}
        second_ids = {sk.id for sk in second}
        assert first_ids.isdisjoint(second_ids), (
            "auto_promote should not re-emit skills already in storage."
        )

    def test_auto_promote_requires_fix_kind(self, tmp_path: Path) -> None:
        """A cluster with only FAILED_APPROACH memories (no FIX kind) is skipped."""
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        only_fails = [
            _make_memory(
                memory_id=f"fail-{i}",
                kind=MemoryKind.FAILED_APPROACH,
                title=f"Fail {i}",
                summary=f"Something failed {i}.",
                tags=["arch"],
            )
            for i in range(3)
        ]
        storage.upsert_memories(only_fails)
        skills = auto_promote_recurring(storage)
        assert len(skills) == 0, "Should not promote a pure FAILED_APPROACH cluster."

    def test_auto_promote_results_have_body(
        self, tmp_path: Path, seeded_memories: list[MemoryEntry]
    ) -> None:
        storage = SQLiteStorage(tmp_path / "memory.db")
        storage.initialize()
        storage.upsert_memories(seeded_memories)
        skills = auto_promote_recurring(storage)
        for sk in skills:
            assert sk.body, f"Skill {sk.id} must have a non-empty body."


# ── rank_skills tests ──────────────────────────────────────────────────────────


class TestRankSkills:
    def test_rank_by_tag_overlap(self) -> None:
        sk_matching = _make_skill(
            skill_id="sk_match", name="Matching", tags=["testing", "ruff"], confidence=0.5
        )
        sk_unrelated = _make_skill(
            skill_id="sk_unrel", name="Unrelated", tags=["infra"], confidence=0.9
        )
        ranked = rank_skills(
            [sk_unrelated, sk_matching], tags=["testing"], files=[]
        )
        # Tag-matching skill should rank above the unrelated one despite lower confidence.
        assert ranked[0].id == sk_matching.id

    def test_rank_by_success_rate(self) -> None:
        high_success = _make_skill(
            skill_id="sk_hi",
            name="High Success",
            tags=["arch"],
            use_count=10,
            success_count=9,
            confidence=0.5,
        )
        low_success = _make_skill(
            skill_id="sk_lo",
            name="Low Success",
            tags=["arch"],
            use_count=10,
            success_count=1,
            confidence=0.5,
        )
        ranked = rank_skills([low_success, high_success], tags=["arch"], files=[])
        assert ranked[0].id == high_success.id

    def test_staleness_penalty_demotes_old_skills(self) -> None:
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        old_last_used = now - timedelta(days=90)
        stale_skill = _make_skill(
            skill_id="sk_stale", name="Stale", tags=["testing"], confidence=0.9
        )
        stale_skill = stale_skill.model_copy(update={"last_used_at": old_last_used})
        fresh_skill = _make_skill(
            skill_id="sk_fresh", name="Fresh", tags=["testing"], confidence=0.5
        )
        ranked = rank_skills([stale_skill, fresh_skill], tags=["testing"], files=[], now=now)
        # The stale skill had higher confidence but should be demoted.
        assert ranked[0].id == fresh_skill.id

    def test_rank_empty_list(self) -> None:
        assert rank_skills([], tags=["testing"], files=[]) == []

    def test_rank_no_context_uses_confidence(self) -> None:
        sk_a = _make_skill(skill_id="sk_a", name="A", tags=[], confidence=0.9)
        sk_b = _make_skill(skill_id="sk_b", name="B", tags=[], confidence=0.4)
        ranked = rank_skills([sk_b, sk_a], tags=[], files=[])
        assert ranked[0].id == sk_a.id


# ── Service tests ──────────────────────────────────────────────────────────────


class TestSkillService:
    def test_skill_promote_from_playbook(
        self,
        initialized_repo: Path,
        seeded_memories: list[MemoryEntry],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        storage.upsert_memories(seeded_memories)
        _, playbooks, _ = svc.generate_playbooks(no_llm=True, write_artifacts=False)
        assert playbooks, "Need a playbook to promote."
        skills = svc.skill_promote(playbooks[0].id)
        assert len(skills) == 1
        from oh_no_my_claudecode.models.skill import Skill as _Skill
        assert isinstance(skills[0], _Skill)

    def test_skill_promote_auto(
        self,
        initialized_repo: Path,
        seeded_memories: list[MemoryEntry],
    ) -> None:
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        storage.upsert_memories(seeded_memories)
        skills = svc.skill_promote(auto=True)
        assert len(skills) >= 1

    def test_skill_promote_missing_playbook_raises(self, initialized_repo: Path) -> None:
        svc = OnmcService(initialized_repo)
        with pytest.raises(LookupError):
            svc.skill_promote("does-not-exist")

    def test_skill_list(
        self,
        initialized_repo: Path,
        seeded_memories: list[MemoryEntry],
    ) -> None:
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        storage.upsert_memories(seeded_memories)
        svc.skill_promote(auto=True)
        skills = svc.skill_list()
        assert len(skills) >= 1

    def test_skill_show_by_prefix(
        self,
        initialized_repo: Path,
        seeded_memories: list[MemoryEntry],
    ) -> None:
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        storage.upsert_memories(seeded_memories)
        promoted = svc.skill_promote(auto=True)
        from oh_no_my_claudecode.models.skill import Skill as _Skill
        first = promoted[0]
        assert isinstance(first, _Skill)
        found = svc.skill_show(first.id[:8])
        assert isinstance(found, _Skill)
        assert found.id == first.id

    def test_skill_feedback_up(
        self,
        initialized_repo: Path,
        seeded_memories: list[MemoryEntry],
    ) -> None:
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        storage.upsert_memories(seeded_memories)
        promoted = svc.skill_promote(auto=True)
        from oh_no_my_claudecode.models.skill import Skill as _Skill
        first = promoted[0]
        assert isinstance(first, _Skill)
        updated = svc.skill_feedback(first.id, "up")
        assert isinstance(updated, _Skill)
        assert updated.use_count == 1
        assert updated.success_count == 1
        assert updated.confidence >= first.confidence

    def test_skill_feedback_down(
        self,
        initialized_repo: Path,
        seeded_memories: list[MemoryEntry],
    ) -> None:
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        storage.upsert_memories(seeded_memories)
        promoted = svc.skill_promote(auto=True)
        from oh_no_my_claudecode.models.skill import Skill as _Skill
        first = promoted[0]
        assert isinstance(first, _Skill)
        updated = svc.skill_feedback(first.id, "down")
        assert isinstance(updated, _Skill)
        assert updated.use_count == 1
        assert updated.success_count == 0
        assert updated.confidence <= first.confidence
        # Confidence must stay above the floor.
        assert updated.confidence >= OnmcService._SKILL_CONFIDENCE_FLOOR

    def test_skill_prune_demotes_failing_skill(self, initialized_repo: Path) -> None:
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        sk = _make_skill(use_count=5, success_count=0, confidence=0.8, auto_inject=True)
        storage.add_skill(sk)
        pruned = svc.skill_prune()
        from oh_no_my_claudecode.models.skill import Skill as _Skill
        skill_pruned = [s for s in pruned if isinstance(s, _Skill)]
        assert any(s.id == sk.id for s in skill_pruned)
        # Verify auto_inject is now False in storage.
        fetched = storage.get_skill(sk.id)
        assert fetched is not None
        assert fetched.auto_inject is False

    def test_skill_prune_leaves_healthy_skills(self, initialized_repo: Path) -> None:
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        healthy = _make_skill(
            skill_id="sk_healthy",
            name="Healthy",
            use_count=10,
            success_count=9,
            confidence=0.9,
            auto_inject=True,
        )
        storage.add_skill(healthy)
        pruned = svc.skill_prune()
        from oh_no_my_claudecode.models.skill import Skill as _Skill
        pruned_ids = {s.id for s in pruned if isinstance(s, _Skill)}
        assert healthy.id not in pruned_ids


# ── CLI tests ──────────────────────────────────────────────────────────────────


class TestSkillCLI:
    def test_skill_list_empty(
        self,
        initialized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        result = _runner.invoke(app, ["skill", "list"], color=False)
        assert result.exit_code == 0
        assert "No skills" in result.output

    def test_skill_list_json_empty(
        self,
        initialized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        result = _runner.invoke(app, ["skill", "list", "--json"], color=False)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []

    def test_skill_promote_auto_and_list(
        self,
        initialized_repo: Path,
        seeded_memories: list[MemoryEntry],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        storage.upsert_memories(seeded_memories)
        result = _runner.invoke(app, ["skill", "promote", "--auto"], color=False)
        assert result.exit_code == 0
        # Now list should show skills.
        result2 = _runner.invoke(app, ["skill", "list"], color=False)
        assert result2.exit_code == 0
        assert "Skill" in result2.output

    def test_skill_promote_auto_json(
        self,
        initialized_repo: Path,
        seeded_memories: list[MemoryEntry],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        storage.upsert_memories(seeded_memories)
        result = _runner.invoke(app, ["skill", "promote", "--auto", "--json"], color=False)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_skill_show_json(
        self,
        initialized_repo: Path,
        seeded_memories: list[MemoryEntry],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        storage.upsert_memories(seeded_memories)
        promoted = svc.skill_promote(auto=True)
        from oh_no_my_claudecode.models.skill import Skill as _Skill
        first = promoted[0]
        assert isinstance(first, _Skill)
        result = _runner.invoke(
            app, ["skill", "show", first.id, "--json"], color=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == first.id
        assert "name" in data
        assert "body" in data
        assert "trigger" in data

    def test_skill_show_not_found(
        self,
        initialized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        result = _runner.invoke(app, ["skill", "show", "does-not-exist"], color=False)
        assert result.exit_code != 0

    def test_skill_feedback_up_json(
        self,
        initialized_repo: Path,
        seeded_memories: list[MemoryEntry],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        storage.upsert_memories(seeded_memories)
        promoted = svc.skill_promote(auto=True)
        from oh_no_my_claudecode.models.skill import Skill as _Skill
        first = promoted[0]
        assert isinstance(first, _Skill)
        result = _runner.invoke(
            app, ["skill", "feedback", first.id, "up", "--json"], color=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["direction"] == "up"
        assert data["use_count"] == 1
        assert data["success_count"] == 1

    def test_skill_feedback_down_json(
        self,
        initialized_repo: Path,
        seeded_memories: list[MemoryEntry],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        storage.upsert_memories(seeded_memories)
        promoted = svc.skill_promote(auto=True)
        from oh_no_my_claudecode.models.skill import Skill as _Skill
        first = promoted[0]
        assert isinstance(first, _Skill)
        result = _runner.invoke(
            app, ["skill", "feedback", first.id, "down", "--json"], color=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["direction"] == "down"
        assert data["use_count"] == 1
        assert data["success_count"] == 0

    def test_skill_feedback_invalid_direction(
        self,
        initialized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        result = _runner.invoke(
            app, ["skill", "feedback", "sk_any", "sideways"], color=False
        )
        assert result.exit_code != 0

    def test_skill_prune_json(
        self,
        initialized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        # Add a skill that is clearly failing (5 uses, 0 successes).
        sk = _make_skill(use_count=5, success_count=0, confidence=0.8, auto_inject=True)
        storage.add_skill(sk)
        result = _runner.invoke(app, ["skill", "prune", "--json"], color=False)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert any(item["id"] == sk.id for item in data)

    def test_skill_promote_without_args_fails(
        self,
        initialized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        result = _runner.invoke(app, ["skill", "promote"], color=False)
        assert result.exit_code != 0
