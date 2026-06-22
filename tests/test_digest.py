"""Tests for `onmc digest --since <ref>`.

Covers:
- Committed-export path: memories in .agent-memory/ at ref A, new memories added
  after → digest reports new ones grouped by kind.
- created_at fallback path: no committed export at ref → filters by created_at.
- Bad ref → clean nonzero exit.
- ONMC_TERSE shrinks output.
- JSON flag emits parseable JSON.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.digest.compiler import compile_digest, digest_to_markdown
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType

runner = CliRunner()

# ---------------------------------------------------------------------------
# Shared git helpers (mirrors conftest.py style)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=merged_env,
    )
    return result.stdout.strip()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(
    repo: Path,
    message: str,
    timestamp: str,
    env: dict[str, str] | None = None,
) -> str:
    """Stage all, commit with message + timestamp, return short hash."""
    ts_env: dict[str, str] = {
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_DATE": timestamp,
    }
    if env:
        ts_env.update(env)
    _git(repo, "add", ".", env=ts_env)
    _git(repo, "commit", "-m", message, env=ts_env)
    return _git(repo, "rev-parse", "--short", "HEAD")


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    return repo


# ---------------------------------------------------------------------------
# Fixture: a repo whose .agent-memory/ is committed at ref A but has new
# memories added between A and HEAD.
# ---------------------------------------------------------------------------


def _make_memory_json(mem_id: str, kind: str, title: str, summary: str) -> str:
    """Produce the JSON shape that memory_diff._load_memories_at expects."""
    return json.dumps(
        {
            "memory": {
                "id": mem_id,
                "kind": kind,
                "title": title,
                "summary": summary,
            }
        },
        indent=2,
    )


@pytest.fixture()
def committed_export_repo(tmp_path: Path) -> tuple[Path, str]:
    """Repo with committed .agent-memory/ at ref A + new memory added after A.

    Returns (repo_path, hash_a).
    """
    repo = _init_repo(tmp_path)

    # Commit A: .agent-memory/ has one decision memory.
    _write(
        repo / ".agent-memory" / "memories" / "decision" / "mem-001.json",
        _make_memory_json("mem-001", "decision", "Use async I/O", "Always prefer async."),
    )
    _write(repo / "README.md", "# Repo\n")
    hash_a = _commit(repo, "initial snapshot", "2026-01-01T10:00:00+00:00")

    # After A: add a new invariant memory to the committed export.
    _write(
        repo / ".agent-memory" / "memories" / "invariant" / "mem-002.json",
        _make_memory_json(
            "mem-002",
            "invariant",
            "Never skip validation",
            "Input must always be validated before processing.",
        ),
    )
    # Also add a new gotcha.
    _write(
        repo / ".agent-memory" / "memories" / "gotcha" / "mem-003.json",
        _make_memory_json(
            "mem-003",
            "gotcha",
            "Clock skew on containers",
            "Container clocks may be skewed; always use server-side timestamps.",
        ),
    )
    _commit(repo, "add invariant + gotcha memories", "2026-02-01T10:00:00+00:00")

    return repo, hash_a


@pytest.fixture()
def no_export_repo(tmp_path: Path) -> tuple[Path, str, OnmcService]:
    """Repo WITHOUT committed .agent-memory/; ONMC initialized with live memories.

    Returns (repo_path, hash_a, service).
    """
    repo = _init_repo(tmp_path)
    _write(repo / "README.md", "# Repo\n")
    hash_a = _commit(repo, "initial commit", "2026-01-01T10:00:00+00:00")

    svc = OnmcService(repo)
    svc.init_project()

    return repo, hash_a, svc


# ---------------------------------------------------------------------------
# Tests: committed-export path
# ---------------------------------------------------------------------------


class TestCommittedExportPath:
    def test_reports_added_memories_grouped_by_kind(
        self, committed_export_repo: tuple[Path, str]
    ) -> None:
        repo, hash_a = committed_export_repo
        # Use a dummy storage — committed-export path doesn't read live storage.
        from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

        storage_path = repo / ".onmc" / "memory.db"
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage = SQLiteStorage(storage_path)

        result = compile_digest(repo, storage, hash_a)

        assert result.source == "committed_export"
        assert result.since_ref == hash_a
        assert result.since_short  # resolved
        # invariant and gotcha were added after hash_a
        kinds_with_entries = set(result.by_kind.keys())
        assert MemoryKind.INVARIANT in kinds_with_entries
        assert MemoryKind.GOTCHA in kinds_with_entries
        # The original decision memory (mem-001) existed at A → not "added"
        decision_entries = result.by_kind.get(MemoryKind.DECISION, [])
        assert len(decision_entries) == 0, "mem-001 existed at ref A, should not appear"

    def test_total_matches_sum_of_by_kind(
        self, committed_export_repo: tuple[Path, str]
    ) -> None:
        repo, hash_a = committed_export_repo
        from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

        storage_path = repo / ".onmc" / "memory.db"
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage = SQLiteStorage(storage_path)

        result = compile_digest(repo, storage, hash_a)

        assert result.total == sum(len(v) for v in result.by_kind.values())
        assert result.total == 2  # one invariant + one gotcha

    def test_all_entries_marked_added(
        self, committed_export_repo: tuple[Path, str]
    ) -> None:
        repo, hash_a = committed_export_repo
        from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

        storage_path = repo / ".onmc" / "memory.db"
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage = SQLiteStorage(storage_path)

        result = compile_digest(repo, storage, hash_a)

        for entries in result.by_kind.values():
            for entry in entries:
                assert entry.change_type == "added"

    def test_markdown_contains_kind_sections(
        self, committed_export_repo: tuple[Path, str]
    ) -> None:
        repo, hash_a = committed_export_repo
        from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

        storage_path = repo / ".onmc" / "memory.db"
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage = SQLiteStorage(storage_path)

        result = compile_digest(repo, storage, hash_a)
        md = digest_to_markdown(result)

        assert "## Invariants" in md
        assert "## Gotchas" in md
        assert "Never skip validation" in md
        assert "Clock skew on containers" in md
        # ref label in header
        assert hash_a[:4] in md

    def test_nothing_new_when_ref_is_head(
        self, committed_export_repo: tuple[Path, str]
    ) -> None:
        repo, _hash_a = committed_export_repo
        from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

        storage_path = repo / ".onmc" / "memory.db"
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage = SQLiteStorage(storage_path)

        result = compile_digest(repo, storage, "HEAD")

        assert result.total == 0
        md = digest_to_markdown(result)
        assert "Nothing new" in md


# ---------------------------------------------------------------------------
# Tests: created_at fallback path
# ---------------------------------------------------------------------------


class TestCreatedAtFallbackPath:
    def _seed_memory(
        self,
        svc: OnmcService,
        *,
        title: str,
        kind: MemoryKind,
        created_at: datetime,
    ) -> None:
        """Insert a memory directly into the storage with a controlled created_at."""
        _, _, storage = svc._load_context()
        import uuid

        from oh_no_my_claudecode.utils.time import utc_now

        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            kind=kind,
            title=title,
            summary=f"Summary of {title}",
            details="",
            source_type=SourceType.MANUAL,
            source_ref="test",
            tags=[],
            confidence=0.9,
            feedback_score=0.0,
            created_at=created_at,
            updated_at=utc_now(),
        )
        storage.upsert_memories([entry])

    def test_fallback_reports_memories_after_ref_timestamp(
        self, no_export_repo: tuple[Path, str, OnmcService]
    ) -> None:
        repo, hash_a, svc = no_export_repo

        ref_ts_str = _git(repo, "log", "-1", "--format=%cI", hash_a)
        ref_ts = datetime.fromisoformat(ref_ts_str).astimezone(UTC)

        # Memory created BEFORE ref (should not appear).
        old_ts = ref_ts.replace(year=ref_ts.year - 1)
        self._seed_memory(svc, title="Old memory", kind=MemoryKind.DECISION, created_at=old_ts)

        # Memory created AFTER ref (should appear).
        new_ts = ref_ts.replace(year=ref_ts.year + 1)
        self._seed_memory(
            svc, title="New decision", kind=MemoryKind.DECISION, created_at=new_ts
        )
        self._seed_memory(
            svc, title="New invariant", kind=MemoryKind.INVARIANT, created_at=new_ts
        )

        _, _, storage = svc._load_context()
        result = compile_digest(repo, storage, hash_a)

        assert result.source == "created_at_fallback"
        assert result.fallback_reason  # must be set
        decision_entries = result.by_kind.get(MemoryKind.DECISION, [])
        assert len(decision_entries) == 1
        assert decision_entries[0].title == "New decision"
        invariant_entries = result.by_kind.get(MemoryKind.INVARIANT, [])
        assert len(invariant_entries) == 1
        assert invariant_entries[0].title == "New invariant"

    def test_fallback_markdown_has_note(
        self, no_export_repo: tuple[Path, str, OnmcService]
    ) -> None:
        repo, hash_a, svc = no_export_repo
        _, _, storage = svc._load_context()
        result = compile_digest(repo, storage, hash_a)

        md = digest_to_markdown(result)
        assert "fallback" in md.lower() or "Note" in md


# ---------------------------------------------------------------------------
# Tests: bad ref → nonzero exit
# ---------------------------------------------------------------------------


class TestBadRef:
    def test_bad_ref_raises_value_error(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _write(repo / "f.txt", "x")
        _commit(repo, "init", "2026-01-01T10:00:00+00:00")

        from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

        storage_path = repo / ".onmc" / "memory.db"
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage = SQLiteStorage(storage_path)

        with pytest.raises(ValueError, match="Cannot resolve git ref"):
            compile_digest(repo, storage, "not-a-real-ref-xyzzy9999")

    def test_cli_bad_ref_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_repo(tmp_path)
        _write(repo / "f.txt", "x")
        _commit(repo, "init", "2026-01-01T10:00:00+00:00")

        svc = OnmcService(repo)
        svc.init_project()
        monkeypatch.chdir(repo)

        result = runner.invoke(
            app,
            ["digest", "--since", "totally-bogus-ref-xyz"],
            catch_exceptions=False,
            prog_name="onmc",
        )
        assert result.exit_code != 0

    def test_cli_missing_since_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_repo(tmp_path)
        _write(repo / "f.txt", "x")
        _commit(repo, "init", "2026-01-01T10:00:00+00:00")

        svc = OnmcService(repo)
        svc.init_project()
        monkeypatch.chdir(repo)

        result = runner.invoke(
            app,
            ["digest"],
            catch_exceptions=False,
            prog_name="onmc",
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Tests: ONMC_TERSE reduces output
# ---------------------------------------------------------------------------


class TestTerseMode:
    def test_terse_omits_summary_column(
        self,
        committed_export_repo: tuple[Path, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo, hash_a = committed_export_repo
        svc = OnmcService(repo)
        svc.init_project()
        monkeypatch.chdir(repo)

        # Full mode — invoke without ONMC_TERSE
        full_result = runner.invoke(
            app,
            ["digest", "--since", hash_a],
            catch_exceptions=False,
            prog_name="onmc",
            env={"ONMC_TERSE": "0"},
        )

        # Terse mode
        terse_result = runner.invoke(
            app,
            ["digest", "--since", hash_a],
            catch_exceptions=False,
            prog_name="onmc",
            env={"ONMC_TERSE": "1"},
        )

        # Both should succeed
        assert full_result.exit_code == 0
        assert terse_result.exit_code == 0
        # Terse output should be shorter (no summary column)
        assert len(terse_result.output) < len(full_result.output)


# ---------------------------------------------------------------------------
# Tests: JSON output
# ---------------------------------------------------------------------------


class TestJsonOutput:
    def test_json_flag_emits_valid_json(
        self,
        committed_export_repo: tuple[Path, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo, hash_a = committed_export_repo
        svc = OnmcService(repo)
        svc.init_project()
        monkeypatch.chdir(repo)

        result = runner.invoke(
            app,
            ["digest", "--since", hash_a, "--json"],
            catch_exceptions=False,
            prog_name="onmc",
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert "since_ref" in payload
        assert "by_kind" in payload
        assert "total" in payload
        assert payload["source"] == "committed_export"

    def test_json_by_kind_has_expected_keys(
        self,
        committed_export_repo: tuple[Path, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo, hash_a = committed_export_repo
        svc = OnmcService(repo)
        svc.init_project()
        monkeypatch.chdir(repo)

        result = runner.invoke(
            app,
            ["digest", "--since", hash_a, "--json"],
            catch_exceptions=False,
            prog_name="onmc",
        )
        payload = json.loads(result.output)
        by_kind = payload["by_kind"]
        assert "invariant" in by_kind
        assert "gotcha" in by_kind
        for entries in by_kind.values():
            for entry in entries:
                assert "id" in entry
                assert "title" in entry
                assert "summary" in entry
                assert "change_type" in entry


# ---------------------------------------------------------------------------
# Tests: artifact written to .onmc/compiled/
# ---------------------------------------------------------------------------


class TestArtifactWritten:
    def test_service_writes_artifact(
        self, committed_export_repo: tuple[Path, str]
    ) -> None:
        repo, hash_a = committed_export_repo
        svc = OnmcService(repo)
        svc.init_project()

        artifact_path, result = svc.digest(hash_a)

        assert artifact_path.exists()
        assert artifact_path.suffix == ".md"
        assert "digest-since" in artifact_path.name
        content = artifact_path.read_text(encoding="utf-8")
        assert "Knowledge changelog" in content
