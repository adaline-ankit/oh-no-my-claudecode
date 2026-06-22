"""Tests for ``onmc import``: OMC skills, hermes memories, generic markdown, CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.importers import ImportResult, run_import
from oh_no_my_claudecode.importers.hermes import parse as hermes_parse
from oh_no_my_claudecode.importers.hermes import resolve_hermes_files
from oh_no_my_claudecode.importers.markdown import (
    parse_as_memories,
    parse_as_skills,
    resolve_md_paths,
)
from oh_no_my_claudecode.importers.omc import parse as omc_parse
from oh_no_my_claudecode.importers.omc import resolve_omc_dirs
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

# ── CLI runner ─────────────────────────────────────────────────────────────────

_runner = CliRunner()


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def brain(tmp_path: Path) -> SQLiteStorage:
    """Initialised SQLiteStorage at a temporary path."""
    db = tmp_path / "brain.db"
    storage = SQLiteStorage(db)
    storage.initialize()
    return storage


@pytest.fixture()
def omc_skills_dir(tmp_path: Path) -> Path:
    """A .omc/skills/ directory with two skill files."""
    skills_dir = tmp_path / ".omc" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "my-first-skill.md").write_text(
        "# First Skill\n\nAlways run tests before merging.\n\nDetails go here.",
        encoding="utf-8",
    )
    (skills_dir / "second-skill.md").write_text(
        "# Second Skill\n\nCheck the cache boundary before modifying workers.",
        encoding="utf-8",
    )
    return skills_dir


@pytest.fixture()
def hermes_memory_file(tmp_path: Path) -> Path:
    """A MEMORY.md file with several ## sections."""
    md = tmp_path / "MEMORY.md"
    md.write_text(
        """\
# Project Memory

Preamble content about the project.

## Decision

We chose SQLite for portability.

## Invariant

Never bypass the cache boundary.

## Hotspot

apps/mira is high churn — 32 commits in 30 days.
""",
        encoding="utf-8",
    )
    return md


@pytest.fixture()
def md_skills_dir(tmp_path: Path) -> Path:
    """A directory of generic .md skill files."""
    d = tmp_path / "how-tos"
    d.mkdir()
    (d / "deploy.md").write_text(
        "# Deploy Runbook\n\nRun `make deploy` to push to production.",
        encoding="utf-8",
    )
    (d / "debug.md").write_text(
        "# Debug Tips\n\nSet LOG_LEVEL=debug and check .onmc/logs/.",
        encoding="utf-8",
    )
    return d


# ── OMC importer tests ─────────────────────────────────────────────────────────


class TestOmcParse:
    def test_parse_returns_skills(self, omc_skills_dir: Path) -> None:
        skills = omc_parse([omc_skills_dir])
        assert len(skills) == 2  # noqa: PLR2004

    def test_skills_tagged_imported_omc(self, omc_skills_dir: Path) -> None:
        skills = omc_parse([omc_skills_dir])
        for skill in skills:
            assert "imported:omc" in skill.tags

    def test_skill_name_from_heading(self, omc_skills_dir: Path) -> None:
        skills = omc_parse([omc_skills_dir])
        names = {s.name for s in skills}
        assert "First Skill" in names
        assert "Second Skill" in names

    def test_skill_trigger_from_first_prose(self, omc_skills_dir: Path) -> None:
        skills = {s.name: s for s in omc_parse([omc_skills_dir])}
        assert "Always run tests before merging" in skills["First Skill"].trigger

    def test_skill_body_contains_full_text(self, omc_skills_dir: Path) -> None:
        skills = {s.name: s for s in omc_parse([omc_skills_dir])}
        assert "Details go here" in skills["First Skill"].body

    def test_stable_id_deterministic(self, omc_skills_dir: Path) -> None:
        skills_a = omc_parse([omc_skills_dir])
        skills_b = omc_parse([omc_skills_dir])
        ids_a = {s.id for s in skills_a}
        ids_b = {s.id for s in skills_b}
        assert ids_a == ids_b

    def test_resolve_omc_dirs_explicit_path(self, omc_skills_dir: Path) -> None:
        dirs = resolve_omc_dirs(omc_skills_dir)
        assert omc_skills_dir in dirs

    def test_resolve_omc_dirs_missing_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            resolve_omc_dirs(None, cwd=tmp_path)

    def test_resolve_omc_dirs_autodetect_project(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / ".omc" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "test.md").write_text("# Test", encoding="utf-8")
        dirs = resolve_omc_dirs(None, cwd=tmp_path)
        assert skills_dir in dirs


# ── Hermes importer tests ──────────────────────────────────────────────────────


class TestHermesParse:
    def test_parse_sections_into_memories(self, hermes_memory_file: Path) -> None:
        memories = hermes_parse([hermes_memory_file])
        # Preamble + 3 ## sections = 4 entries
        assert len(memories) >= 3  # noqa: PLR2004

    def test_memories_tagged_imported_hermes(self, hermes_memory_file: Path) -> None:
        memories = hermes_parse([hermes_memory_file])
        for mem in memories:
            assert "imported:hermes" in mem.tags

    def test_decision_section_infers_kind(self, hermes_memory_file: Path) -> None:
        from oh_no_my_claudecode.models import MemoryKind

        memories = {m.title: m for m in hermes_parse([hermes_memory_file])}
        assert "Decision" in memories
        assert memories["Decision"].kind == MemoryKind.DECISION

    def test_invariant_section_infers_kind(self, hermes_memory_file: Path) -> None:
        from oh_no_my_claudecode.models import MemoryKind

        memories = {m.title: m for m in hermes_parse([hermes_memory_file])}
        assert "Invariant" in memories
        assert memories["Invariant"].kind == MemoryKind.INVARIANT

    def test_hotspot_section_infers_kind(self, hermes_memory_file: Path) -> None:
        from oh_no_my_claudecode.models import MemoryKind

        memories = {m.title: m for m in hermes_parse([hermes_memory_file])}
        assert "Hotspot" in memories
        assert memories["Hotspot"].kind == MemoryKind.HOTSPOT

    def test_resolve_hermes_files_explicit_file(self, hermes_memory_file: Path) -> None:
        files = resolve_hermes_files(hermes_memory_file)
        assert hermes_memory_file in files

    def test_resolve_hermes_files_autodetect(self, hermes_memory_file: Path) -> None:
        parent = hermes_memory_file.parent
        files = resolve_hermes_files(None, cwd=parent)
        assert hermes_memory_file in files

    def test_resolve_hermes_files_missing_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            resolve_hermes_files(None, cwd=tmp_path)


# ── Generic markdown importer tests ───────────────────────────────────────────


class TestMarkdownParse:
    def test_parse_dir_as_skills(self, md_skills_dir: Path) -> None:
        files = resolve_md_paths(md_skills_dir)
        skills = parse_as_skills(files)
        assert len(skills) == 2  # noqa: PLR2004

    def test_skills_tagged_imported_md(self, md_skills_dir: Path) -> None:
        files = resolve_md_paths(md_skills_dir)
        skills = parse_as_skills(files)
        for skill in skills:
            assert "imported:md" in skill.tags

    def test_skill_name_from_heading(self, md_skills_dir: Path) -> None:
        files = resolve_md_paths(md_skills_dir)
        skills = parse_as_skills(files)
        names = {s.name for s in skills}
        assert "Deploy Runbook" in names
        assert "Debug Tips" in names

    def test_parse_file_as_memories(self, hermes_memory_file: Path) -> None:
        files = resolve_md_paths(hermes_memory_file)
        memories = parse_as_memories(files)
        assert len(memories) >= 1

    def test_memories_tagged_imported_md(self, hermes_memory_file: Path) -> None:
        files = resolve_md_paths(hermes_memory_file)
        memories = parse_as_memories(files)
        for mem in memories:
            assert "imported:md" in mem.tags

    def test_resolve_md_paths_missing_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            resolve_md_paths(tmp_path / "nonexistent.md")

    def test_resolve_md_paths_empty_dir_raises(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            resolve_md_paths(empty_dir)


# ── run_import / dedup / dry-run tests ────────────────────────────────────────


class TestRunImport:
    def test_omc_import_writes_skills(
        self, brain: SQLiteStorage, omc_skills_dir: Path
    ) -> None:
        result = run_import(brain, "omc", omc_skills_dir, dry_run=False, as_kind="skill")
        assert isinstance(result, ImportResult)
        assert result.imported == 2  # noqa: PLR2004
        assert result.skipped == 0
        assert result.as_kind == "skill"

    def test_omc_import_dedup_on_reimport(
        self, brain: SQLiteStorage, omc_skills_dir: Path
    ) -> None:
        run_import(brain, "omc", omc_skills_dir)
        result = run_import(brain, "omc", omc_skills_dir)
        assert result.imported == 0
        assert result.skipped == 2  # noqa: PLR2004

    def test_omc_import_items_list(
        self, brain: SQLiteStorage, omc_skills_dir: Path
    ) -> None:
        result = run_import(brain, "omc", omc_skills_dir)
        assert "First Skill" in result.items or "Second Skill" in result.items

    def test_hermes_import_writes_memories(
        self, brain: SQLiteStorage, hermes_memory_file: Path
    ) -> None:
        result = run_import(brain, "hermes", hermes_memory_file, as_kind="memory")
        assert result.imported >= 1
        assert result.as_kind == "memory"

    def test_hermes_import_dedup(
        self, brain: SQLiteStorage, hermes_memory_file: Path
    ) -> None:
        run_import(brain, "hermes", hermes_memory_file)
        result = run_import(brain, "hermes", hermes_memory_file)
        assert result.imported == 0
        assert result.skipped >= 1

    def test_md_dir_import_as_skills(
        self, brain: SQLiteStorage, md_skills_dir: Path
    ) -> None:
        result = run_import(brain, str(md_skills_dir), as_kind="skill")
        assert result.imported == 2  # noqa: PLR2004
        assert result.as_kind == "skill"

    def test_md_file_import_as_memory(
        self, brain: SQLiteStorage, hermes_memory_file: Path
    ) -> None:
        result = run_import(brain, str(hermes_memory_file), as_kind="memory")
        assert result.imported >= 1
        assert result.as_kind == "memory"

    def test_dry_run_writes_nothing(
        self, brain: SQLiteStorage, omc_skills_dir: Path
    ) -> None:
        result = run_import(brain, "omc", omc_skills_dir, dry_run=True)
        assert result.dry_run is True
        assert result.imported == 0
        assert result.skipped == 0
        # Items were parsed but not written — subsequent real run imports all.
        result2 = run_import(brain, "omc", omc_skills_dir, dry_run=False)
        assert result2.imported == 2  # noqa: PLR2004

    def test_missing_source_raises_file_not_found(self, brain: SQLiteStorage) -> None:
        with pytest.raises(FileNotFoundError):
            run_import(brain, "omc", Path("/nonexistent/skills/dir"))

    def test_invalid_as_kind_raises_value_error(
        self, brain: SQLiteStorage, omc_skills_dir: Path
    ) -> None:
        with pytest.raises(ValueError, match="as_kind"):
            run_import(brain, "omc", omc_skills_dir, as_kind="invalid")


# ── CLI tests ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def sample_repo_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal initialized onmc repo in tmp_path."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = _runner.invoke(app, ["init"], prog_name="onmc")
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    return repo


class TestImportCLI:
    def test_cli_omc_import_success(
        self, sample_repo_init: Path, omc_skills_dir: Path
    ) -> None:
        result = _runner.invoke(
            app,
            ["import", "omc", str(omc_skills_dir)],
            prog_name="onmc",
        )
        assert result.exit_code == 0, result.stdout
        assert "Imported" in result.stdout or "import" in result.stdout.lower()

    def test_cli_hermes_import_success(
        self, sample_repo_init: Path, hermes_memory_file: Path
    ) -> None:
        result = _runner.invoke(
            app,
            ["import", "hermes", str(hermes_memory_file)],
            prog_name="onmc",
        )
        assert result.exit_code == 0, result.stdout

    def test_cli_md_dir_import_success(
        self, sample_repo_init: Path, md_skills_dir: Path
    ) -> None:
        result = _runner.invoke(
            app,
            ["import", str(md_skills_dir)],
            prog_name="onmc",
        )
        assert result.exit_code == 0, result.stdout

    def test_cli_dry_run_writes_nothing(
        self, sample_repo_init: Path, omc_skills_dir: Path
    ) -> None:
        result = _runner.invoke(
            app,
            ["import", "omc", str(omc_skills_dir), "--dry-run"],
            prog_name="onmc",
        )
        assert result.exit_code == 0, result.stdout
        assert "dry" in result.stdout.lower() or "Dry" in result.stdout

    def test_cli_json_output_shape(
        self, sample_repo_init: Path, omc_skills_dir: Path
    ) -> None:
        result = _runner.invoke(
            app,
            ["import", "omc", str(omc_skills_dir), "--json"],
            prog_name="onmc",
        )
        assert result.exit_code == 0, result.stdout
        data = json.loads(result.stdout)
        assert "imported" in data
        assert "skipped" in data
        assert "items" in data
        assert "dry_run" in data
        assert "source" in data
        assert "as_kind" in data

    def test_cli_missing_source_nonzero_exit(self, sample_repo_init: Path) -> None:
        result = _runner.invoke(
            app,
            ["import", "omc", "/nonexistent/skills/path"],
            prog_name="onmc",
        )
        assert result.exit_code != 0

    def test_cli_invalid_as_kind_nonzero_exit(
        self, sample_repo_init: Path, md_skills_dir: Path
    ) -> None:
        result = _runner.invoke(
            app,
            ["import", str(md_skills_dir), "--as", "invalid"],
            prog_name="onmc",
        )
        assert result.exit_code != 0
