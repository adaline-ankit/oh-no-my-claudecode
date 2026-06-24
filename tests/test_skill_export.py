"""Tests for onmc skill export — SKILL.md generation (agentskills.io standard)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import Skill
from oh_no_my_claudecode.skill.export import export_skills, render_skill_md, skill_slug
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_runner = CliRunner()


def _make_skill(
    *,
    skill_id: str = "sk_export_test01",
    name: str = "Cache Invalidation",
    body: str = "1. Always invalidate through the cache boundary.\n2. Never bypass the layer.",
    trigger: str = "When cache invalidation patterns appear in the codebase.",
    tags: list[str] | None = None,
    files: list[str] | None = None,
    confidence: float = 0.82,
) -> Skill:
    now = utc_now()
    resolved_files = ["src/cache.py"] if files is None else files
    return Skill(
        id=skill_id,
        name=name,
        body=body,
        trigger=trigger,
        tags=tags or ["caching", "architecture"],
        files=resolved_files,
        source_memory_ids=["mem-1"],
        use_count=3,
        success_count=3,
        confidence=confidence,
        auto_inject=True,
        created_at=now,
        updated_at=now,
        last_used_at=None,
    )


# ---------------------------------------------------------------------------
# skill_slug
# ---------------------------------------------------------------------------


class TestSkillSlug:
    def test_basic_slug_is_lowercase_hyphen(self) -> None:
        sk = _make_skill(name="Cache Invalidation")
        slug = skill_slug(sk)
        assert slug == "cache-invalidation"

    def test_slug_strips_special_chars(self) -> None:
        sk = _make_skill(name="Fix: Race Condition (DB)")
        slug = skill_slug(sk)
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in slug)
        assert slug  # non-empty

    def test_slug_max_length(self) -> None:
        sk = _make_skill(name="a" * 200)
        slug = skill_slug(sk)
        assert len(slug) <= 48

    def test_dedup_with_existing_set(self) -> None:
        sk1 = _make_skill(skill_id="sk_aaa", name="Same Name")
        sk2 = _make_skill(skill_id="sk_bbb", name="Same Name")
        existing: set[str] = set()
        slug1 = skill_slug(sk1, existing=existing)
        existing.add(slug1)
        slug2 = skill_slug(sk2, existing=existing)
        assert slug1 != slug2

    def test_two_skills_same_name_unique_slugs(self) -> None:
        sk1 = _make_skill(skill_id="sk_111111", name="Auth Guard")
        sk2 = _make_skill(skill_id="sk_222222", name="Auth Guard")
        allocated: set[str] = set()
        s1 = skill_slug(sk1, existing=allocated)
        allocated.add(s1)
        s2 = skill_slug(sk2, existing=allocated)
        assert s1 != s2

    def test_empty_name_falls_back(self) -> None:
        sk = _make_skill(name="!@#$%")
        slug = skill_slug(sk)
        assert slug  # non-empty fallback


# ---------------------------------------------------------------------------
# render_skill_md
# ---------------------------------------------------------------------------


class TestRenderSkillMd:
    def test_produces_yaml_frontmatter(self) -> None:
        sk = _make_skill()
        md = render_skill_md(sk)
        assert md.startswith("---\n")
        # Find closing ---
        second_fence = md.index("---\n", 4)
        frontmatter_text = md[4:second_fence]
        parsed = yaml.safe_load(frontmatter_text)
        assert isinstance(parsed, dict)

    def test_frontmatter_has_name(self) -> None:
        sk = _make_skill(name="Cache Invalidation")
        md = render_skill_md(sk)
        second_fence = md.index("---\n", 4)
        parsed = yaml.safe_load(md[4:second_fence])
        assert parsed["name"] == "Cache Invalidation"

    def test_frontmatter_has_description(self) -> None:
        sk = _make_skill()
        md = render_skill_md(sk)
        second_fence = md.index("---\n", 4)
        parsed = yaml.safe_load(md[4:second_fence])
        assert "description" in parsed
        assert parsed["description"]

    def test_frontmatter_has_when_to_use(self) -> None:
        sk = _make_skill(trigger="When cache patterns appear.")
        md = render_skill_md(sk)
        second_fence = md.index("---\n", 4)
        parsed = yaml.safe_load(md[4:second_fence])
        assert "when_to_use" in parsed
        assert "cache" in parsed["when_to_use"].lower()

    def test_frontmatter_paths_from_files(self) -> None:
        sk = _make_skill(files=["src/cache.py", "tests/"])
        md = render_skill_md(sk)
        second_fence = md.index("---\n", 4)
        parsed = yaml.safe_load(md[4:second_fence])
        assert "paths" in parsed
        paths_str = parsed["paths"]
        assert "src/cache.py" in paths_str

    def test_no_paths_when_files_empty(self) -> None:
        sk = _make_skill(files=[])
        md = render_skill_md(sk)
        second_fence = md.index("---\n", 4)
        parsed = yaml.safe_load(md[4:second_fence])
        assert "paths" not in parsed

    def test_body_present_after_frontmatter(self) -> None:
        sk = _make_skill(body="1. Do the thing.\n2. Do it again.")
        md = render_skill_md(sk)
        assert "1. Do the thing." in md

    def test_provenance_footer_present(self) -> None:
        sk = _make_skill(confidence=0.85)
        md = render_skill_md(sk)
        assert "_Learned by onmc" in md
        assert "0.85" in md

    def test_description_truncated_under_1536_chars(self) -> None:
        long_name = "A" * 1000
        long_trigger = "B" * 1000
        sk = _make_skill(name=long_name, trigger=long_trigger)
        md = render_skill_md(sk)
        second_fence = md.index("---\n", 4)
        parsed = yaml.safe_load(md[4:second_fence])
        description = parsed.get("description", "")
        when_to_use = parsed.get("when_to_use", "")
        combined = f"{description} {when_to_use}"
        assert len(combined) <= 1536

    def test_yaml_frontmatter_is_valid_for_colon_in_trigger(self) -> None:
        sk = _make_skill(trigger="When you see: a colon in the trigger.")
        md = render_skill_md(sk)
        second_fence = md.index("---\n", 4)
        parsed = yaml.safe_load(md[4:second_fence])
        assert isinstance(parsed, dict)
        assert "when_to_use" in parsed

    def test_yaml_frontmatter_is_valid_for_special_name(self) -> None:
        sk = _make_skill(name="Fix: Race Condition [critical]")
        md = render_skill_md(sk)
        second_fence = md.index("---\n", 4)
        parsed = yaml.safe_load(md[4:second_fence])
        assert isinstance(parsed, dict)

    def test_idempotent_output(self) -> None:
        sk = _make_skill()
        assert render_skill_md(sk) == render_skill_md(sk)


# ---------------------------------------------------------------------------
# export_skills
# ---------------------------------------------------------------------------


class TestExportSkills:
    def test_writes_skill_md_files(self, tmp_path: Path) -> None:
        sk = _make_skill()
        written = export_skills([sk], tmp_path)
        assert len(written) == 1
        assert written[0].name == "SKILL.md"
        assert written[0].exists()

    def test_directory_structure_is_slug_subdir(self, tmp_path: Path) -> None:
        sk = _make_skill(name="Auth Guard")
        export_skills([sk], tmp_path)
        assert (tmp_path / "auth-guard" / "SKILL.md").exists()

    def test_idempotent_reexport_does_not_rewrite(self, tmp_path: Path) -> None:
        sk = _make_skill()
        written1 = export_skills([sk], tmp_path)
        written2 = export_skills([sk], tmp_path)
        assert len(written1) == 1
        assert len(written2) == 0  # already up to date — no re-write

    def test_empty_skills_returns_empty(self, tmp_path: Path) -> None:
        written = export_skills([], tmp_path)
        assert written == []

    def test_multiple_skills_multiple_dirs(self, tmp_path: Path) -> None:
        sk1 = _make_skill(skill_id="sk_aa", name="Alpha Skill")
        sk2 = _make_skill(skill_id="sk_bb", name="Beta Skill")
        written = export_skills([sk1, sk2], tmp_path)
        assert len(written) == 2
        assert (tmp_path / "alpha-skill" / "SKILL.md").exists()
        assert (tmp_path / "beta-skill" / "SKILL.md").exists()

    def test_same_name_skills_get_unique_dirs(self, tmp_path: Path) -> None:
        sk1 = _make_skill(skill_id="sk_111111", name="Same Skill")
        sk2 = _make_skill(skill_id="sk_222222", name="Same Skill")
        written = export_skills([sk1, sk2], tmp_path)
        assert len(written) == 2
        paths = [str(p) for p in written]
        assert len(set(paths)) == 2  # distinct paths

    def test_out_dir_created_if_missing(self, tmp_path: Path) -> None:
        out = tmp_path / "deep" / "nested" / "skills"
        sk = _make_skill()
        export_skills([sk], out)
        assert out.exists()

    def test_content_is_valid_skill_md(self, tmp_path: Path) -> None:
        sk = _make_skill()
        written = export_skills([sk], tmp_path)
        content = written[0].read_text(encoding="utf-8")
        assert content.startswith("---\n")
        second_fence = content.index("---\n", 4)
        parsed = yaml.safe_load(content[4:second_fence])
        assert isinstance(parsed, dict)
        assert "name" in parsed
        assert "description" in parsed


# ---------------------------------------------------------------------------
# service.skill_export
# ---------------------------------------------------------------------------


class TestServiceSkillExport:
    def test_default_path_is_dot_claude_skills(
        self, initialized_repo: Path, seeded_skills: list[Skill]
    ) -> None:
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        for sk in seeded_skills:
            storage.add_skill(sk)
        written = svc.skill_export()
        expected_base = str(initialized_repo / ".claude" / "skills")
        assert all(expected_base in str(p) for p in written)

    def test_explicit_out_dir(
        self, initialized_repo: Path, seeded_skills: list[Skill], tmp_path: Path
    ) -> None:
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        for sk in seeded_skills:
            storage.add_skill(sk)
        custom_out = tmp_path / "my-skills"
        written = svc.skill_export(out_dir=custom_out)
        assert all(str(custom_out) in str(p) for p in written)

    def test_empty_store_returns_empty(self, initialized_repo: Path) -> None:
        svc = OnmcService(initialized_repo)
        written = svc.skill_export()
        assert written == []

    def test_personal_scope_writes_home_skills(
        self,
        initialized_repo: Path,
        seeded_skills: list[Skill],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Redirect home() to a temp dir so we don't pollute the real ~.
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        for sk in seeded_skills:
            storage.add_skill(sk)
        written = svc.skill_export(scope="personal")
        assert all(str(fake_home / ".claude" / "skills") in str(p) for p in written)


# ---------------------------------------------------------------------------
# CLI: onmc skill export
# ---------------------------------------------------------------------------


class TestSkillExportCLI:
    def test_export_no_skills_exits_ok(
        self, initialized_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        result = _runner.invoke(app, ["skill", "export"], color=False)
        assert result.exit_code == 0
        assert "No skills yet" in result.output

    def test_export_writes_and_prints_summary(
        self,
        initialized_repo: Path,
        seeded_skills: list[Skill],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        for sk in seeded_skills:
            storage.add_skill(sk)
        result = _runner.invoke(app, ["skill", "export"], color=False)
        assert result.exit_code == 0
        assert "Exported" in result.output
        assert "SKILL.md" in result.output or ".claude/skills" in result.output

    def test_export_json_returns_paths(
        self,
        initialized_repo: Path,
        seeded_skills: list[Skill],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        for sk in seeded_skills:
            storage.add_skill(sk)
        result = _runner.invoke(app, ["skill", "export", "--json"], color=False)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert all(isinstance(p, str) for p in data)

    def test_export_json_empty_skills(
        self, initialized_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        result = _runner.invoke(app, ["skill", "export", "--json"], color=False)
        assert result.exit_code == 0
        # Empty store → friendly message, not JSON (json output only for non-empty)
        # Actually with empty store the early-return prints the friendly message.
        assert "No skills yet" in result.output or result.output == "[]\n"

    def test_export_custom_out_dir(
        self,
        initialized_repo: Path,
        seeded_skills: list[Skill],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        svc = OnmcService(initialized_repo)
        _, _, storage = svc._load_context()
        for sk in seeded_skills:
            storage.add_skill(sk)
        custom = tmp_path / "exported"
        result = _runner.invoke(
            app, ["skill", "export", "--out", str(custom)], color=False
        )
        assert result.exit_code == 0
        assert custom.exists()

    def test_export_invalid_scope_fails(
        self, initialized_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(initialized_repo)
        result = _runner.invoke(
            app, ["skill", "export", "--scope", "enterprise"], color=False
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def initialized_repo(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(sample_repo)
    svc = OnmcService(sample_repo)
    svc.init_project()
    return sample_repo


@pytest.fixture
def seeded_skills() -> list[Skill]:
    now = utc_now()
    return [
        Skill(
            id="sk_export_seed1",
            name="Cache Invalidation Guard",
            body="1. Route all cache writes through the boundary layer.\n2. Never bypass.",
            trigger="When cache invalidation code is touched.",
            tags=["caching"],
            files=["src/cache.py"],
            source_memory_ids=["mem-seed-1"],
            use_count=2,
            success_count=2,
            confidence=0.85,
            auto_inject=True,
            created_at=now,
            updated_at=now,
            last_used_at=None,
        ),
        Skill(
            id="sk_export_seed2",
            name="Input Validation at Boundary",
            body="1. Validate inputs at the service layer.\n2. Never trust caller assumptions.",
            trigger="When adding or modifying service entry points.",
            tags=["validation"],
            files=["src/service.py"],
            source_memory_ids=["mem-seed-2"],
            use_count=1,
            success_count=1,
            confidence=0.78,
            auto_inject=True,
            created_at=now,
            updated_at=now,
            last_used_at=None,
        ),
    ]
