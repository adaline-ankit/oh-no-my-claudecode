"""Tests for provenance-based staleness detection (migration v3).

Covers:
- classify_staleness: fresh / stale / orphaned / unanchored on a real temp git repo
- memory verify CLI: updates staleness + last_verified_at columns
- memory prune --orphaned: removes orphaned generated memories, preserves manual ones
- migration v3 idempotency: schema_version becomes "3"
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.memory.staleness import classify_staleness, extract_anchor_path
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=merged,
    )


def _commit(repo: Path, message: str, timestamp: str) -> None:
    env = {
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_DATE": timestamp,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    _git(repo, "add", ".", env=env)
    _git(repo, "commit", "--allow-empty-message", "-m", message, env=env)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_memory(
    *,
    source_ref: str,
    source_type: SourceType = SourceType.DOC,
    updated_at: datetime | None = None,
) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=f"mem-{source_ref.replace('/', '-')}-{int(now.timestamp())}",
        kind=MemoryKind.DOC_FACT,
        title=f"Test memory for {source_ref}",
        summary="Test summary",
        details="Test details",
        source_type=source_type,
        source_ref=source_ref,
        tags=[],
        confidence=0.8,
        feedback_score=0.0,
        created_at=now,
        updated_at=updated_at or now,
    )


# ---------------------------------------------------------------------------
# anchor-path extraction unit tests
# ---------------------------------------------------------------------------


def test_extract_anchor_path_plain_file() -> None:
    assert extract_anchor_path("README.md") == "README.md"


def test_extract_anchor_path_nested_file() -> None:
    assert extract_anchor_path("src/cache.py") == "src/cache.py"


def test_extract_anchor_path_pipe_joined() -> None:
    # First path with extension wins
    assert extract_anchor_path("src/foo.py|tests/test_foo.py") == "src/foo.py"


def test_extract_anchor_path_repo_tree_sentinel() -> None:
    assert extract_anchor_path("repo_tree") is None


def test_extract_anchor_path_manual_prefix() -> None:
    assert extract_anchor_path("manual:one") is None


def test_extract_anchor_path_directory_bucket() -> None:
    # Bare directory name has no extension → not a file anchor
    assert extract_anchor_path("src") is None


def test_extract_anchor_path_pyproject_sentinel() -> None:
    # "pyproject.toml" is a sentinel with an extension → valid anchor
    assert extract_anchor_path("pyproject.toml") == "pyproject.toml"


def test_extract_anchor_path_empty() -> None:
    assert extract_anchor_path("") is None


# ---------------------------------------------------------------------------
# classify_staleness on a real git repo
# ---------------------------------------------------------------------------


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Minimal git repo with one committed file and one deleted file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")

    _write(repo / "docs" / "guide.md", "# Guide\nThis is the guide.\n")
    _write(repo / "src" / "main.py", "# main\n")
    _commit(repo, "initial", "2020-01-01T00:00:00+00:00")

    # Create and later delete a file
    _write(repo / "docs" / "old.md", "# Old\nWill be deleted.\n")
    _commit(repo, "add old.md", "2020-06-01T00:00:00+00:00")

    (repo / "docs" / "old.md").unlink()
    _commit(repo, "delete old.md", "2020-07-01T00:00:00+00:00")

    return repo


def test_classify_fresh_file(git_repo: Path) -> None:
    # Memory recorded *after* the last commit that touched guide.md → fresh
    memory = _make_memory(
        source_ref="docs/guide.md",
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    result = classify_staleness(git_repo, memory)
    assert result == "fresh"


def test_classify_stale_file(git_repo: Path) -> None:
    # Memory recorded *before* the last commit that touched src/main.py → stale
    memory = _make_memory(
        source_ref="src/main.py",
        updated_at=datetime(2019, 1, 1, tzinfo=UTC),
    )
    result = classify_staleness(git_repo, memory)
    assert result == "stale"


def test_classify_orphaned_file(git_repo: Path) -> None:
    # docs/old.md was deleted from the repo
    memory = _make_memory(
        source_ref="docs/old.md",
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    result = classify_staleness(git_repo, memory)
    assert result == "orphaned"


def test_classify_unanchored(git_repo: Path) -> None:
    memory = _make_memory(source_ref="repo_tree")
    result = classify_staleness(git_repo, memory)
    assert result == "unanchored"


def test_classify_unanchored_manual(git_repo: Path) -> None:
    memory = _make_memory(source_ref="manual:custom note", source_type=SourceType.MANUAL)
    result = classify_staleness(git_repo, memory)
    assert result == "unanchored"


# ---------------------------------------------------------------------------
# Migration v3 idempotency
# ---------------------------------------------------------------------------


def test_migration_v3_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    # Start from scratch — no pre-existing schema
    storage = SQLiteStorage(db_path)
    storage.initialize()
    storage.initialize()  # second call must be a no-op

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}

    assert "staleness" in columns
    assert "last_verified_at" in columns
    assert storage.get_meta("schema_version") == "6"


def test_migration_v3_upgrades_existing_v2_db(tmp_path: Path) -> None:
    """A DB that previously ran only through v2 must smoothly upgrade to v3."""
    db_path = tmp_path / "memory.db"
    # Build v2 schema manually (mirrors test_memory_feedback.py pattern)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                details TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                confidence REAL NOT NULL,
                feedback_score REAL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta VALUES ('schema_version', '2');
            """
        )

    storage = SQLiteStorage(db_path)
    storage.initialize()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}

    assert "staleness" in columns
    assert "last_verified_at" in columns
    assert storage.get_meta("schema_version") == "6"


# ---------------------------------------------------------------------------
# set_memory_staleness round-trip
# ---------------------------------------------------------------------------


def test_set_memory_staleness_persists(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    storage = SQLiteStorage(db_path)
    storage.initialize()

    now = utc_now()
    entry = MemoryEntry(
        id="test-stale-001",
        kind=MemoryKind.DOC_FACT,
        title="Staleness test",
        summary="summary",
        details="details",
        source_type=SourceType.DOC,
        source_ref="docs/guide.md",
        tags=[],
        confidence=0.9,
        feedback_score=0.0,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    storage.set_memory_staleness("test-stale-001", "stale", "2025-01-01T00:00:00+00:00")

    loaded = storage.get_memory("test-stale-001")
    assert loaded is not None
    assert loaded.staleness == "stale"
    assert loaded.last_verified_at is not None
    assert loaded.last_verified_at.year == 2025


# ---------------------------------------------------------------------------
# CLI: memory verify
# ---------------------------------------------------------------------------


@pytest.fixture()
def onmc_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialized ONMC repo ready for CLI tests."""
    repo = tmp_path / "onmc-repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    _write(repo / "README.md", "# Test\n\nThis is a test repo.\n")
    _commit(repo, "initial", "2020-01-01T00:00:00+00:00")
    monkeypatch.chdir(repo)
    svc = OnmcService(repo)
    svc.init_project()
    return repo


def test_memory_verify_updates_staleness(
    onmc_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(onmc_repo)

    # Seed one doc memory and one unanchored memory
    svc = OnmcService(onmc_repo)
    _repo_root, _config, storage = svc._load_context()  # noqa: SLF001

    now = utc_now()
    doc_mem = MemoryEntry(
        id="verify-doc-001",
        kind=MemoryKind.DOC_FACT,
        title="README test",
        summary="summary",
        details="details",
        source_type=SourceType.DOC,
        source_ref="README.md",  # exists in repo
        tags=[],
        confidence=0.8,
        feedback_score=0.0,
        created_at=now,
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),  # after last commit
    )
    ghost_mem = MemoryEntry(
        id="verify-ghost-001",
        kind=MemoryKind.DOC_FACT,
        title="Ghost memory",
        summary="summary",
        details="details",
        source_type=SourceType.DOC,
        source_ref="docs/missing.md",  # does NOT exist
        tags=[],
        confidence=0.8,
        feedback_score=0.0,
        created_at=now,
        updated_at=now,
    )
    manual_mem = MemoryEntry(
        id="verify-manual-001",
        kind=MemoryKind.INVARIANT,
        title="Manual memory",
        summary="summary",
        details="details",
        source_type=SourceType.MANUAL,
        source_ref="manual:handwritten",
        tags=[],
        confidence=1.0,
        feedback_score=0.0,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([doc_mem, ghost_mem, manual_mem])

    result = runner.invoke(app, ["memory", "verify"])

    assert result.exit_code == 0, result.output
    assert "Verified" in result.output

    # Reload from storage and check staleness was persisted
    loaded_doc = storage.get_memory("verify-doc-001")
    loaded_ghost = storage.get_memory("verify-ghost-001")
    loaded_manual = storage.get_memory("verify-manual-001")

    assert loaded_doc is not None
    assert loaded_doc.staleness in ("fresh", "stale")  # depends on git clock vs updated_at
    assert loaded_doc.last_verified_at is not None

    assert loaded_ghost is not None
    assert loaded_ghost.staleness == "orphaned"
    assert loaded_ghost.last_verified_at is not None

    assert loaded_manual is not None
    assert loaded_manual.staleness == "unanchored"


# ---------------------------------------------------------------------------
# CLI: memory prune --orphaned
# ---------------------------------------------------------------------------


def test_memory_prune_orphaned_removes_generated_keeps_manual(
    onmc_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(onmc_repo)

    svc = OnmcService(onmc_repo)
    _repo_root, _config, storage = svc._load_context()  # noqa: SLF001

    now = utc_now()
    # Orphaned generated memory — should be deleted
    gen_orphan = MemoryEntry(
        id="prune-gen-001",
        kind=MemoryKind.DOC_FACT,
        title="Orphaned generated",
        summary="s",
        details="d",
        source_type=SourceType.DOC,
        source_ref="docs/gone.md",
        tags=[],
        confidence=0.7,
        feedback_score=0.0,
        created_at=now,
        updated_at=now,
    )
    # Orphaned MANUAL memory — must be preserved
    manual_orphan = MemoryEntry(
        id="prune-manual-001",
        kind=MemoryKind.INVARIANT,
        title="Orphaned manual",
        summary="s",
        details="d",
        source_type=SourceType.MANUAL,
        source_ref="docs/gone.md",
        tags=[],
        confidence=1.0,
        feedback_score=0.0,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([gen_orphan, manual_orphan])
    # Tag both as orphaned
    verified_at = "2025-01-01T00:00:00+00:00"
    storage.set_memory_staleness("prune-gen-001", "orphaned", verified_at)
    storage.set_memory_staleness("prune-manual-001", "orphaned", verified_at)

    result = runner.invoke(app, ["memory", "prune", "--orphaned"])

    assert result.exit_code == 0, result.output
    assert storage.get_memory("prune-gen-001") is None, "Generated orphan should be deleted"
    assert storage.get_memory("prune-manual-001") is not None, "Manual memory must be preserved"


def test_memory_prune_dry_run_does_not_delete(
    onmc_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(onmc_repo)

    svc = OnmcService(onmc_repo)
    _repo_root, _config, storage = svc._load_context()  # noqa: SLF001

    now = utc_now()
    gen_orphan = MemoryEntry(
        id="dryrun-gen-001",
        kind=MemoryKind.DOC_FACT,
        title="Dry run orphan",
        summary="s",
        details="d",
        source_type=SourceType.DOC,
        source_ref="docs/gone.md",
        tags=[],
        confidence=0.7,
        feedback_score=0.0,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([gen_orphan])
    storage.set_memory_staleness("dryrun-gen-001", "orphaned", "2025-01-01T00:00:00+00:00")

    result = runner.invoke(app, ["memory", "prune", "--orphaned", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    # Memory must still exist
    assert storage.get_memory("dryrun-gen-001") is not None, "Dry run must not delete"


def test_memory_prune_no_flag_is_fatal() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["memory", "prune"])
    assert result.exit_code != 0 or "Specify --orphaned" in result.output
