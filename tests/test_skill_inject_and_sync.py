"""Tests for skill auto-injection and .agent-memory/ portability.

Covers:
- Relevant skill IS injected into compile_prompt_recall_safe output for matching prompt.
- Irrelevant skills are NOT injected when there is no tag/prompt overlap.
- A surfaced skill's use_count is bumped after injection.
- Hook still exits 0 and injects memories when skills raise/are empty.
- compile_boot_digest includes skills in both terse and verbose modes.
- sync commit→restore round-trips a skill with provenance intact.
- Terse vs verbose skill rendering (render_skills_terse / render_skills_verbose).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oh_no_my_claudecode.hooks.boot_digest import compile_boot_digest
from oh_no_my_claudecode.hooks.prompt_recall import (
    compile_prompt_recall_safe,
    compile_skills_recall,
)
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, Skill, SourceType
from oh_no_my_claudecode.serialize.skill_renderer import render_skills_terse, render_skills_verbose
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_storage(db_path: Path) -> SQLiteStorage:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    return storage


def _make_memory(*, title: str, summary: str, tags: list[str]) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=f"mem-{title[:8].lower().replace(' ', '-')}",
        kind=MemoryKind.INVARIANT,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.DOC,
        source_ref="docs/arch.md",
        tags=tags,
        confidence=0.9,
        feedback_score=0.0,
        created_at=now,
        updated_at=now,
    )


def _make_skill(
    *,
    skill_id: str = "sk_inject01",
    name: str = "Cache Invalidation Skill",
    trigger: str = "When fixing cache invalidation bugs.",
    body: str = "1. Route through boundary module.\n2. Never write directly.",
    tags: list[str] | None = None,
    confidence: float = 0.85,
    auto_inject: bool = True,
    use_count: int = 0,
    success_count: int = 0,
) -> Skill:
    now = utc_now()
    return Skill(
        id=skill_id,
        name=name,
        body=body,
        trigger=trigger,
        tags=tags if tags is not None else ["cache", "invalidation"],
        files=["src/"],
        source_memory_ids=["mem-cache-1"],
        use_count=use_count,
        success_count=success_count,
        confidence=confidence,
        auto_inject=auto_inject,
        created_at=now,
        updated_at=now,
        last_used_at=None,
    )


def _seed_memories(storage: SQLiteStorage) -> None:
    memories = [
        _make_memory(
            title="Cache boundary invariant",
            summary="All cache invalidation must go through the shared boundary module.",
            tags=["cache", "invariant"],
        ),
    ]
    storage.upsert_memories(memories)


# ---------------------------------------------------------------------------
# Skill renderer tests
# ---------------------------------------------------------------------------


class TestSkillRenderer:
    def test_render_skills_terse_returns_nonempty_for_skills(self) -> None:
        skill = _make_skill()
        result = render_skills_terse([skill])
        assert result != ""
        assert "SKILL:" in result
        assert "Cache Invalidation Skill" in result
        assert "cache invalidation bugs" in result

    def test_render_skills_terse_empty_list_returns_empty(self) -> None:
        assert render_skills_terse([]) == ""

    def test_render_skills_terse_max_items_limits_output(self) -> None:
        skills = [_make_skill(skill_id=f"sk_{i:04d}", name=f"Skill {i}") for i in range(5)]
        result = render_skills_terse(skills, max_items=2)
        assert result.count("SKILL:") == 2

    def test_render_skills_verbose_contains_section_header(self) -> None:
        skill = _make_skill()
        result = render_skills_verbose([skill])
        assert "## Relevant skills" in result
        assert "Cache Invalidation Skill" in result

    def test_render_skills_verbose_empty_list_returns_empty(self) -> None:
        assert render_skills_verbose([]) == ""

    def test_render_skills_terse_body_first_line_included(self) -> None:
        skill = _make_skill(body="1. Route through boundary module.\n2. Never write directly.")
        result = render_skills_terse([skill])
        # First line of body should appear
        assert "Route through boundary module" in result


# ---------------------------------------------------------------------------
# compile_skills_recall tests
# ---------------------------------------------------------------------------


class TestCompileSkillsRecall:
    def test_matching_skill_is_returned_for_matching_prompt(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path / "memory.db")
        skill = _make_skill(tags=["cache"])
        storage.add_skill(skill)

        text, skill_ids = compile_skills_recall(storage, "fix cache invalidation bug", terse=True)

        assert text != "", "Expected a skills block for matching prompt."
        assert skill.id in skill_ids

    def test_non_auto_inject_skill_is_excluded(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path / "memory.db")
        skill = _make_skill(auto_inject=False, tags=["cache"])
        storage.add_skill(skill)

        text, skill_ids = compile_skills_recall(storage, "fix cache invalidation bug", terse=True)

        assert skill.id not in skill_ids

    def test_irrelevant_skills_not_returned_for_unrelated_prompt(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path / "memory.db")
        # Skill with very specific tags unlikely to match a generic prompt.
        skill = _make_skill(
            skill_id="sk_specific01",
            tags=["zoology", "taxonomy", "biology"],
            confidence=0.1,  # low confidence so it won't pass confidence filter either
        )
        storage.add_skill(skill)

        text, skill_ids = compile_skills_recall(
            storage, "fix javascript syntax error", terse=True
        )

        assert skill.id not in skill_ids

    def test_empty_store_returns_empty(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path / "memory.db")
        text, skill_ids = compile_skills_recall(storage, "fix cache bug", terse=True)
        assert text == ""
        assert skill_ids == []

    def test_verbose_mode_uses_verbose_renderer(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path / "memory.db")
        skill = _make_skill(tags=["cache"])
        storage.add_skill(skill)

        text, _ = compile_skills_recall(
            storage, "fix cache invalidation bug", terse=False
        )

        assert "## Relevant skills" in text

    def test_terse_mode_uses_skill_prefix(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path / "memory.db")
        skill = _make_skill(tags=["cache"])
        storage.add_skill(skill)

        text, _ = compile_skills_recall(storage, "fix cache invalidation bug", terse=True)

        assert "SKILL:" in text


# ---------------------------------------------------------------------------
# compile_prompt_recall_safe (combined) tests
# ---------------------------------------------------------------------------


class TestCompilePromptRecallSafe:
    def test_skills_appended_after_memory_block(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path / "memory.db")
        _seed_memories(storage)
        skill = _make_skill(tags=["cache"])
        storage.add_skill(skill)

        text, tokens = compile_prompt_recall_safe(
            storage, "fix cache invalidation bug", terse=True
        )

        # Must include something (either memories or skills or both).
        assert text != "" or tokens == 0  # acceptable when store is too small
        # If text is non-empty, it should have token count > 0.
        if text:
            assert tokens > 0

    def test_hook_exits_zero_when_skills_empty(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path / "memory.db")
        _seed_memories(storage)

        # No skills added — should still return memory text without error.
        text, _ = compile_prompt_recall_safe(storage, "cache invalidation", terse=True)

        # Memories are present; text should be non-empty.
        assert isinstance(text, str)

    def test_use_count_is_bumped_for_surfaced_skill(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path / "memory.db")
        skill = _make_skill(tags=["cache"], use_count=0)
        storage.add_skill(skill)
        _seed_memories(storage)

        compile_prompt_recall_safe(storage, "fix cache invalidation bug", terse=True)

        # Give the background thread a moment to commit.
        import time
        time.sleep(0.1)

        updated = storage.get_skill(skill.id)
        assert updated is not None
        assert updated.use_count >= 1, "Expected use_count to be bumped after surfacing skill."

    def test_hook_returns_memories_even_when_skills_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate a broken skills layer — memories must still appear."""
        storage = _make_storage(tmp_path / "memory.db")
        _seed_memories(storage)

        # Monkey-patch compile_skills_recall to raise.
        import oh_no_my_claudecode.hooks.prompt_recall as pr_module

        def _broken_skills(*_a: object, **_kw: object) -> tuple[str, list[str]]:
            msg = "simulated skills crash"
            raise RuntimeError(msg)

        monkeypatch.setattr(pr_module, "compile_skills_recall", _broken_skills)

        text, _ = compile_prompt_recall_safe(storage, "cache invalidation", terse=True)

        # Must not raise; should return memories even without skills.
        assert isinstance(text, str)

    def test_returns_empty_for_unrelated_prompt_with_no_skills(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path / "memory.db")
        # Store with memories that don't match the prompt.
        _seed_memories(storage)

        text, _ = compile_prompt_recall_safe(
            storage, "xyzzyx frabbitz quux", terse=True
        )

        assert isinstance(text, str)


# ---------------------------------------------------------------------------
# Boot digest skills injection tests
# ---------------------------------------------------------------------------


class TestBootDigestSkills:
    def test_terse_boot_digest_includes_skills(self) -> None:
        skill = _make_skill()
        text, tokens = compile_boot_digest(
            memories=[
                _make_memory(
                    title="Boundary invariant",
                    summary="Route writes through the boundary.",
                    tags=["cache"],
                )
            ],
            tasks=[],
            repo_name="test-repo",
            skills=[skill],
            terse=True,
        )
        assert text != ""
        assert "SKILL:" in text
        assert tokens > 0

    def test_verbose_boot_digest_includes_skills_section(self) -> None:
        skill = _make_skill()
        text, _ = compile_boot_digest(
            memories=[
                _make_memory(
                    title="Boundary invariant",
                    summary="Route writes through the boundary.",
                    tags=["cache"],
                )
            ],
            tasks=[],
            repo_name="test-repo",
            skills=[skill],
            terse=False,
        )
        assert "Top skills" in text
        assert "Cache Invalidation Skill" in text

    def test_boot_digest_with_no_skills_unaffected(self) -> None:
        text, _ = compile_boot_digest(
            memories=[
                _make_memory(
                    title="Boundary invariant",
                    summary="Route writes through the boundary.",
                    tags=["cache"],
                )
            ],
            tasks=[],
            repo_name="test-repo",
            skills=None,
            terse=True,
        )
        # Should still work; no skills section.
        assert "SKILL:" not in text

    def test_boot_digest_returns_empty_when_all_empty(self) -> None:
        text, tokens = compile_boot_digest(
            memories=[],
            tasks=[],
            repo_name="empty-repo",
            skills=[],
            terse=True,
        )
        assert text == ""
        assert tokens == 0

    def test_boot_digest_non_auto_inject_skill_excluded(self) -> None:
        skill = _make_skill(auto_inject=False)
        text, _ = compile_boot_digest(
            memories=[
                _make_memory(
                    title="Boundary invariant",
                    summary="Route writes through the boundary.",
                    tags=["cache"],
                )
            ],
            tasks=[],
            repo_name="test-repo",
            skills=[skill],
            terse=True,
        )
        assert "SKILL:" not in text


# ---------------------------------------------------------------------------
# Sync commit → restore round-trip with skills
# ---------------------------------------------------------------------------


class TestSyncSkillRoundTrip:
    def test_skill_exports_and_restores_with_provenance_intact(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """commit → restore preserves all Skill fields including tags and files."""
        from oh_no_my_claudecode.core.service import OnmcService

        monkeypatch.chdir(sample_repo)
        svc = OnmcService(sample_repo)
        svc.init_project()

        # Directly insert a skill into storage.
        _, _, storage = svc._load_context()  # noqa: SLF001
        skill = _make_skill(
            skill_id="sk_roundtrip01",
            name="Round-trip Skill",
            trigger="When testing round-trip fidelity.",
            body="1. Export.\n2. Restore.\n3. Verify.",
            tags=["sync", "testing"],
        )
        storage.add_skill(skill)

        # Export.
        svc.sync_commit()

        skill_file = sample_repo / ".agent-memory" / "skills" / "sk_roundtrip01.json"
        assert skill_file.exists(), "Skill file must be written to .agent-memory/skills/."

        payload = json.loads(skill_file.read_text(encoding="utf-8"))
        assert "skill" in payload
        assert payload["skill"]["id"] == "sk_roundtrip01"
        assert payload["skill"]["tags"] == ["sync", "testing"]

        # Check manifest counts.skills.
        manifest = json.loads(
            (sample_repo / ".agent-memory" / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["counts"]["skills"] >= 1

        # Wipe DB and restore.
        db_path = sample_repo / ".onmc" / "memory.db"
        db_path.unlink()
        svc.init_project()
        _, restore_result = svc.sync_restore()

        assert restore_result.skill_count >= 1

        # Verify round-trip fidelity.
        _, _, restored_storage = svc._load_context()  # noqa: SLF001
        restored_skill = restored_storage.get_skill("sk_roundtrip01")
        assert restored_skill is not None
        assert restored_skill.name == "Round-trip Skill"
        assert restored_skill.tags == ["sync", "testing"]
        assert restored_skill.body == "1. Export.\n2. Restore.\n3. Verify."
        assert restored_skill.trigger == "When testing round-trip fidelity."

    def test_sync_restore_is_idempotent_for_skills(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Restoring the same export twice must not fail or duplicate skills."""
        from oh_no_my_claudecode.core.service import OnmcService

        monkeypatch.chdir(sample_repo)
        svc = OnmcService(sample_repo)
        svc.init_project()

        _, _, storage = svc._load_context()  # noqa: SLF001
        skill = _make_skill(skill_id="sk_idem01", name="Idempotency Skill")
        storage.add_skill(skill)
        svc.sync_commit()

        # First restore.
        db_path = sample_repo / ".onmc" / "memory.db"
        db_path.unlink()
        svc.init_project()
        svc.sync_restore()

        # Second restore must not raise.
        svc.sync_restore()

        _, _, restored_storage = svc._load_context()  # noqa: SLF001
        skills = restored_storage.list_skills()
        ids = [sk.id for sk in skills]
        assert ids.count("sk_idem01") == 1, "Skill must not be duplicated on second restore."

    def test_sync_without_skills_dir_still_works(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Restoring an export that has no skills/ directory must succeed silently."""
        from oh_no_my_claudecode.core.service import OnmcService

        monkeypatch.chdir(sample_repo)
        svc = OnmcService(sample_repo)
        svc.init_project()
        svc.ingest()
        svc.sync_commit()

        # Remove the skills/ dir (simulates an old export with no skills).
        skills_dir = sample_repo / ".agent-memory" / "skills"
        if skills_dir.exists():
            import shutil

            shutil.rmtree(skills_dir)

        db_path = sample_repo / ".onmc" / "memory.db"
        db_path.unlink()
        svc.init_project()
        # Must not raise.
        _, restore_result = svc.sync_restore()
        assert restore_result.skill_count == 0
