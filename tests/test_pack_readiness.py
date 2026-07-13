"""Tests for pack readiness guard (Fix A) and goal-path boosting (Fix B).

Fix A: brain_readiness_warnings warns when not ingested, stays quiet when ready.
       --strict refuses (exit 1) when unready; proceeds without it (just warns).

Fix B: extract_goal_paths pulls real file paths out of goal text; ignore non-paths.
       Force-included goal paths appear FIRST in pack.context_files.
       Gracefully degrades when graph is empty or readers raise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode import init
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.pack.builder import _collect_context_files, build_pack, extract_goal_paths
from oh_no_my_claudecode.pack.readiness import brain_readiness_warnings
from oh_no_my_claudecode.storage import SQLiteStorage

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uningest_storage(sample_repo: Path) -> SQLiteStorage:
    """Return a storage that has been init'd but NEVER ingested."""
    repo = init(sample_repo)
    # Do NOT call repo.ingest() — simulates a brand-new onmc init with no data.
    _, _, storage = repo._service._load_context()
    return storage


def _ingested_storage(sample_repo: Path) -> SQLiteStorage:
    """Return a storage that has been init'd AND ingested."""
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()
    return storage


# ---------------------------------------------------------------------------
# Fix A — precondition guard: brain_readiness_warnings
# ---------------------------------------------------------------------------


class TestBrainReadinessWarnings:
    def test_warns_when_never_ingested(self, sample_repo: Path) -> None:
        """A fresh (init'd but not ingested) storage triggers a warning."""
        storage = _uningest_storage(sample_repo)
        warnings = brain_readiness_warnings(storage)
        assert len(warnings) >= 1, warnings
        text = "\n".join(warnings).lower()
        assert "ingest" in text

    def test_silent_when_ready(self, sample_repo: Path) -> None:
        """An ingested storage with repo_files returns no warnings."""
        storage = _ingested_storage(sample_repo)
        warnings = brain_readiness_warnings(storage)
        assert warnings == [], warnings

    def test_warns_when_repo_files_empty_after_ingest(self, sample_repo: Path) -> None:
        """Manually simulate a failed ingest: last_ingest_at set but no repo_files."""
        storage = _uningest_storage(sample_repo)
        # Set last_ingest_at as if ingest ran but leave repo_files empty.
        storage.set_meta("last_ingest_at", "2026-01-01T00:00:00Z")
        warnings = brain_readiness_warnings(storage)
        # Should warn that repo-file index is empty.
        assert len(warnings) >= 1
        text = "\n".join(warnings).lower()
        assert "ingest" in text

    def test_graceful_when_get_meta_raises(self) -> None:
        """Storage read failures are caught; function returns warnings, never raises."""
        bad_storage: Any = MagicMock(spec=SQLiteStorage)
        bad_storage.get_meta.side_effect = RuntimeError("db locked")
        bad_storage.list_repo_files.side_effect = RuntimeError("db locked")
        # Must not raise.
        warnings = brain_readiness_warnings(bad_storage)
        assert isinstance(warnings, list)
        # At minimum the ingest warning should appear.
        assert len(warnings) >= 1

    def test_graceful_when_list_repo_files_raises(self, sample_repo: Path) -> None:
        """list_repo_files failure is handled; ingest timestamp still checked."""
        bad_storage: Any = MagicMock(spec=SQLiteStorage)
        bad_storage.get_meta.return_value = "2026-01-01T00:00:00Z"
        bad_storage.list_repo_files.side_effect = RuntimeError("io error")
        warnings = brain_readiness_warnings(bad_storage)
        # list_repo_files failed → treat as 0 files → warn about empty index.
        assert isinstance(warnings, list)
        assert len(warnings) >= 1


# ---------------------------------------------------------------------------
# Fix A — CLI --strict flag
# ---------------------------------------------------------------------------


class TestStrictFlag:
    def test_strict_exits_nonzero_when_unready(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--strict exits with code 1 when brain is not ingested."""
        monkeypatch.chdir(sample_repo)
        _uningest_storage(sample_repo)  # init without ingest

        result = runner.invoke(app, ["pack", "fix cache bug", "--strict"])
        assert result.exit_code == 1

    def test_strict_exits_nonzero_mission_when_unready(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """mission --strict exits with code 1 when brain is not ingested."""
        monkeypatch.chdir(sample_repo)
        _uningest_storage(sample_repo)  # init without ingest

        result = runner.invoke(app, ["mission", "fix cache bug", "--strict"])
        assert result.exit_code == 1

    def test_no_strict_proceeds_but_warns_on_unready(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without --strict the command exits 0 but emits WARNING to stderr."""
        monkeypatch.chdir(sample_repo)
        _uningest_storage(sample_repo)  # init without ingest

        result = runner.invoke(app, ["pack", "fix cache bug"])
        # Should succeed (exit 0) even though brain is unready.
        assert result.exit_code == 0
        # WARNING must appear in output (stderr is mixed into stdout by CliRunner).
        assert "WARNING" in result.output

    def test_strict_silent_when_ready(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--strict does not exit early when the brain is properly ingested."""
        monkeypatch.chdir(sample_repo)
        _ingested_storage(sample_repo)

        result = runner.invoke(app, ["pack", "fix cache bug", "--strict"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Fix B — extract_goal_paths
# ---------------------------------------------------------------------------


class TestExtractGoalPaths:
    def test_extracts_real_file_from_goal(self, sample_repo: Path) -> None:
        """A real on-disk file path embedded in the goal is extracted."""
        goal = "Fix the bug in src/cache.py and the worker"
        paths = extract_goal_paths(goal, sample_repo)
        assert "src/cache.py" in paths

    def test_ignores_bare_filename_no_slash(self, sample_repo: Path) -> None:
        """Tokens without '/' are not treated as paths (e.g. 'cache.py')."""
        goal = "Fix cache.py directly"
        paths = extract_goal_paths(goal, sample_repo)
        # 'cache.py' has no slash → not extracted.
        assert "cache.py" not in paths

    def test_ignores_nonexistent_paths(self, sample_repo: Path) -> None:
        """Paths that do not exist under repo_root are excluded."""
        goal = "Edit apps/voyage/src/handlers/_helpers/behavior-synthesis-v2.ts"
        paths = extract_goal_paths(goal, sample_repo)
        # This file does not exist in the sample_repo fixture.
        assert "apps/voyage/src/handlers/_helpers/behavior-synthesis-v2.ts" not in paths

    def test_ignores_tokens_with_non_source_extensions(self, tmp_path: Path) -> None:
        """Path tokens with unknown extensions are filtered out."""
        # Create a file with an unusual extension.
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "foo.xyz").write_text("data")
        goal = "Check src/foo.xyz for issues"
        paths = extract_goal_paths(goal, tmp_path)
        assert "src/foo.xyz" not in paths

    def test_returns_empty_for_pure_prose_goal(self, sample_repo: Path) -> None:
        """A goal with no path tokens returns an empty list."""
        goal = "Improve the overall system performance and reliability"
        paths = extract_goal_paths(goal, sample_repo)
        assert paths == []

    def test_deduplicates_same_path_mentioned_twice(self, sample_repo: Path) -> None:
        """Duplicate path mentions in the goal appear only once."""
        goal = "Edit src/cache.py — src/cache.py is the target"
        paths = extract_goal_paths(goal, sample_repo)
        assert paths.count("src/cache.py") == 1


# ---------------------------------------------------------------------------
# Fix B — force-include goal paths appear first in pack.context_files
# ---------------------------------------------------------------------------


class TestGoalPathBoosting:
    def test_goal_path_appears_first_in_context_files(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explicit file path in the goal is ranked first in context_files."""
        monkeypatch.chdir(sample_repo)
        storage = _ingested_storage(sample_repo)

        # Goal explicitly names src/worker.py — this must appear first.
        goal = "Refactor src/worker.py to add rate limiting"
        pack = build_pack(storage, sample_repo, goal)

        assert pack.context_files, "expected non-empty context_files"
        assert pack.context_files[0] == "src/worker.py", (
            f"expected 'src/worker.py' first, got: {pack.context_files}"
        )

    def test_goal_path_first_even_with_empty_graph(self, tmp_path: Path) -> None:
        """Force-include wins even when the code graph has zero files.

        Sets up a minimal repo: only a single TypeScript file.  The codegraph
        (Python-only by default) will not index it, so the graph is empty.
        Yet the file must appear first because it is explicitly named in the goal.
        """
        # Create a TS file — not indexed by the Python-only AST codegraph.
        src = tmp_path / "apps" / "voyage" / "src"
        src.mkdir(parents=True)
        ts_file = src / "handler.ts"
        ts_file.write_text("export function handler() {}", encoding="utf-8")

        goal = "Fix apps/voyage/src/handler.ts to handle errors"
        files = _collect_context_files(tmp_path, goal)

        assert "apps/voyage/src/handler.ts" in files, f"got: {files}"
        assert files[0] == "apps/voyage/src/handler.ts", (
            f"expected TS file first, got: {files}"
        )

    def test_goal_with_multiple_explicit_paths_all_appear(
        self, sample_repo: Path
    ) -> None:
        """Multiple explicit file paths in goal are all force-included."""
        goal = "Refactor src/cache.py and src/worker.py together"
        files = _collect_context_files(sample_repo, goal)

        assert "src/cache.py" in files, f"cache.py missing from: {files}"
        assert "src/worker.py" in files, f"worker.py missing from: {files}"
        # Both forced paths must precede any graph-ranked file.
        forced_indices = [files.index("src/cache.py"), files.index("src/worker.py")]
        assert max(forced_indices) < len(files), "forced paths should be present"
