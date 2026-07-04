"""Tests for the ``fixci`` module — CI-fix autopilot.

All tests are **offline and deterministic**: the CI log is injected as a string
into :func:`plan_ci_fix`; ``gh`` / network are never touched, and we never
assert on Rich ``--help`` output.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.fixci.autopilot import CiFailure, plan_ci_fix
from oh_no_my_claudecode.models import MemoryKind, SourceType
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

# A realistic failing-pytest CI log (GitHub Actions format with timestamps).
_FAILING_PYTEST_LOG = """\
2024-01-02T03:04:05Z ##[group]Run pytest
2024-01-02T03:04:05Z + uv run python -m pytest
2024-01-02T03:04:06Z ============================= test session starts ============================
2024-01-02T03:04:07Z collected 12 items
2024-01-02T03:04:08Z tests/test_widget.py::test_render FAILED
2024-01-02T03:04:09Z =================================== FAILURES ==================================
2024-01-02T03:04:10Z _______________________________ test_render ___________________________________
2024-01-02T03:04:11Z     def test_render():
2024-01-02T03:04:12Z >       assert widget.render() == "ok"
2024-01-02T03:04:13Z E       AssertionError: assert 'boom' == 'ok'
2024-01-02T03:04:14Z src/myproj/widget.py:42: AssertionError
2024-01-02T03:04:15Z FAILED tests/test_widget.py::test_render - AssertionError: 'boom' != 'ok'
2024-01-02T03:04:16Z ##[error]Process completed with exit code 1.
"""


def _init_storage(db_path: Path) -> SQLiteStorage:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    return storage


def _seed_dead_end(storage: SQLiteStorage, title: str, summary: str, details: str) -> str:
    """Insert a FAILED_APPROACH memory and return its id."""
    from oh_no_my_claudecode.models.memory import MemoryEntry

    now = utc_now()
    entry = MemoryEntry(
        id=stable_id(MemoryKind.FAILED_APPROACH.value, title, summary, "test:seed", prefix="test"),
        kind=MemoryKind.FAILED_APPROACH,
        title=title,
        summary=summary,
        details=details,
        source_type=SourceType.MANUAL,
        source_ref="test:seed",
        tags=[MemoryKind.FAILED_APPROACH.value],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return entry.id


def _repo_with_widget(tmp_path: Path) -> Path:
    """Create a tiny repo whose widget.py the CI log points at."""
    repo = tmp_path / "repo"
    (repo / "src" / "myproj").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "src" / "myproj" / "widget.py").write_text(
        "def render() -> str:\n    return 'boom'\n", encoding="utf-8"
    )
    (repo / "src" / "myproj" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "tests" / "test_widget.py").write_text(
        "from myproj import widget\n\n\ndef test_render():\n    assert widget.render() == 'ok'\n",
        encoding="utf-8",
    )
    return repo


# ---------------------------------------------------------------------------
# Core: plan_ci_fix on a failing-pytest log
# ---------------------------------------------------------------------------


def test_plan_extracts_step_error_and_likely_files(tmp_path: Path) -> None:
    """A failing-pytest log yields the step, the error, and a likely file."""
    repo = _repo_with_widget(tmp_path)
    storage = _init_storage(tmp_path / "mem.db")

    failure = plan_ci_fix(storage, repo, log_text=_FAILING_PYTEST_LOG, pr="42")

    assert failure.has_failure
    assert failure.failing_step == "Run pytest"
    assert "AssertionError" in failure.error_excerpt
    # The log named src/myproj/widget.py and it exists on disk → surfaced.
    assert "src/myproj/widget.py" in failure.likely_files
    assert failure.suggested_fix
    assert "42" in failure.swarm_unit


def test_plan_recalls_seeded_dead_end(tmp_path: Path) -> None:
    """A seeded FAILED_APPROACH relevant to the error is recalled as a dead-end."""
    repo = _repo_with_widget(tmp_path)
    storage = _init_storage(tmp_path / "mem.db")
    _seed_dead_end(
        storage,
        title="Patching widget render assertion",
        summary="Tried changing the AssertionError expectation in test_render to silence it",
        details="Editing the assert in tests/test_widget.py to expect 'boom' hid the real bug.",
    )

    failure = plan_ci_fix(storage, repo, log_text=_FAILING_PYTEST_LOG, pr="42")

    assert failure.dead_ends, "expected the seeded dead-end to be recalled"
    joined = " ".join(failure.dead_ends).lower()
    assert "widget" in joined or "assertion" in joined


# ---------------------------------------------------------------------------
# Graceful handling
# ---------------------------------------------------------------------------


def test_plan_empty_log_is_graceful(tmp_path: Path) -> None:
    """An empty log produces a no-failure plan, not an exception."""
    storage = _init_storage(tmp_path / "mem.db")
    failure = plan_ci_fix(storage, tmp_path, log_text="", pr="1")

    assert isinstance(failure, CiFailure)
    assert not failure.has_failure
    assert failure.failing_step == ""
    assert failure.error_excerpt == ""
    assert failure.likely_files == []
    assert failure.dead_ends == []
    assert failure.swarm_unit == ""
    assert "nothing to fix" in failure.suggested_fix.lower()


def test_plan_whitespace_log_is_graceful(tmp_path: Path) -> None:
    """A whitespace-only log is treated like an empty log."""
    storage = _init_storage(tmp_path / "mem.db")
    failure = plan_ci_fix(storage, tmp_path, log_text="   \n\t\n  ", pr="1")
    assert not failure.has_failure


def test_plan_clean_log_no_errors(tmp_path: Path) -> None:
    """A passing-looking log with no error markers degrades gracefully."""
    storage = _init_storage(tmp_path / "mem.db")
    clean = (
        "##[group]Run pytest\n"
        "collected 3 items\n"
        "tests/test_ok.py ...\n"
        "3 passed in 0.10s\n"
    )
    failure = plan_ci_fix(storage, tmp_path, log_text=clean, pr="7")
    # No code-graph match in an empty repo, no recalled dead-ends.
    assert failure.dead_ends == []
    assert isinstance(failure.error_excerpt, str)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_plan_is_deterministic(tmp_path: Path) -> None:
    """The same inputs always yield the same plan."""
    repo = _repo_with_widget(tmp_path)
    storage = _init_storage(tmp_path / "mem.db")
    _seed_dead_end(
        storage,
        title="Patching widget render assertion",
        summary="Tried changing the AssertionError expectation in test_render",
        details="Editing the assert hid the real bug.",
    )

    first = plan_ci_fix(storage, repo, log_text=_FAILING_PYTEST_LOG, pr="42")
    second = plan_ci_fix(storage, repo, log_text=_FAILING_PYTEST_LOG, pr="42")
    assert first.to_dict() == second.to_dict()


# ---------------------------------------------------------------------------
# CLI: --log (offline) + --json
# ---------------------------------------------------------------------------


def test_cli_fix_ci_with_log_file_json(tmp_path: Path, monkeypatch) -> None:
    """`onmc fix-ci <pr> --log <file> --json` plans offline and emits JSON."""
    repo = _repo_with_widget(tmp_path)
    log_file = tmp_path / "ci.log"
    log_file.write_text(_FAILING_PYTEST_LOG, encoding="utf-8")
    monkeypatch.chdir(repo)

    runner = CliRunner()
    result = runner.invoke(app, ["fix-ci", "42", "--log", str(log_file), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["failing_step"] == "Run pytest"
    assert "AssertionError" in payload["error_excerpt"]
    assert "src/myproj/widget.py" in payload["likely_files"]


def test_cli_fix_ci_with_log_file_plain(tmp_path: Path, monkeypatch) -> None:
    """The default (non-JSON) render prints a plan-only panel."""
    log_file = tmp_path / "ci.log"
    log_file.write_text(_FAILING_PYTEST_LOG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(app, ["fix-ci", "42", "--log", str(log_file)])

    assert result.exit_code == 0, result.output
    assert "fix-ci" in result.output
    assert "Run pytest" in result.output


def test_cli_missing_log_file_errors(tmp_path: Path, monkeypatch) -> None:
    """A nonexistent --log path exits non-zero with a clear message."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["fix-ci", "42", "--log", str(tmp_path / "nope.log")])
    assert result.exit_code != 0
