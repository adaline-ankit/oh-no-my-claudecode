from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.config import user_database_path, user_state_dir
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.hooks.boot_digest import compile_boot_digest
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def test_user_state_dir_under_fake_home(tmp_path: Path) -> None:
    assert user_state_dir(home=tmp_path) == tmp_path / ".onmc"


def test_user_database_path_under_fake_home(tmp_path: Path) -> None:
    assert user_database_path(home=tmp_path) == tmp_path / ".onmc" / "user.db"


# ---------------------------------------------------------------------------
# Service — add / list / show / remove round-trip
# ---------------------------------------------------------------------------


def test_add_user_memory_round_trip(tmp_path: Path) -> None:
    svc = OnmcService()
    entry = svc.add_user_memory(
        title="Prefers pytest",
        summary="Always use pytest, never unittest.",
        home=tmp_path,
    )
    assert entry.id.startswith("user-")
    assert entry.title == "Prefers pytest"
    assert entry.source_type == SourceType.MANUAL
    assert "user-pref" in entry.tags

    # list returns the entry
    all_prefs = svc.list_user_memories(home=tmp_path)
    assert any(m.id == entry.id for m in all_prefs)


def test_show_user_memory(tmp_path: Path) -> None:
    svc = OnmcService()
    entry = svc.add_user_memory(
        title="Always ruff",
        summary="Run ruff before committing.",
        home=tmp_path,
    )
    fetched = svc.get_user_memory(entry.id, home=tmp_path)
    assert fetched is not None
    assert fetched.summary == "Run ruff before committing."


def test_remove_user_memory(tmp_path: Path) -> None:
    svc = OnmcService()
    entry = svc.add_user_memory(
        title="Temp pref",
        summary="This will be removed.",
        home=tmp_path,
    )
    removed = svc.remove_user_memory(entry.id, home=tmp_path)
    assert removed is True

    # no longer returned
    assert svc.get_user_memory(entry.id, home=tmp_path) is None


def test_remove_nonexistent_user_memory(tmp_path: Path) -> None:
    svc = OnmcService()
    removed = svc.remove_user_memory("user-doesnotexist", home=tmp_path)
    assert removed is False


# ---------------------------------------------------------------------------
# Isolation: user memories are isolated from repo memories
# ---------------------------------------------------------------------------


def test_user_memories_isolated_from_repo(tmp_path: Path, sample_repo: Path) -> None:
    """User DB and repo DB are separate; a user pref must not appear in repo list."""
    svc = OnmcService(sample_repo)
    svc.init_project()

    svc.add_user_memory(
        title="User-only pref",
        summary="This is a cross-repo preference.",
        home=tmp_path,
    )

    # Repo-scoped memories do not include user prefs
    repo_memories = svc.list_memories()
    assert all(m.title != "User-only pref" for m in repo_memories)

    # User memories don't appear in repo storage
    user_mems = svc.list_user_memories(home=tmp_path)
    assert any(m.title == "User-only pref" for m in user_mems)


# ---------------------------------------------------------------------------
# Boot digest includes a "Your preferences" section when user memories exist
# ---------------------------------------------------------------------------


def _make_user_pref(title: str, summary: str) -> MemoryEntry:
    now = datetime.now(tz=UTC)
    return MemoryEntry(
        id=f"user-{title[:8].lower().replace(' ', '-')}",
        kind=MemoryKind.DECISION,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.MANUAL,
        source_ref="user:manual",
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )


def test_boot_digest_includes_user_prefs_section() -> None:
    prefs = [
        _make_user_pref("Prefers pytest", "Always use pytest."),
        _make_user_pref("Run ruff first", "Run ruff before committing."),
    ]
    digest, tokens = compile_boot_digest(
        memories=[],
        tasks=[],
        repo_name="my-repo",
        user_memories=prefs,
    )
    assert "### Your preferences" in digest
    assert "Prefers pytest" in digest
    assert "Run ruff first" in digest
    assert tokens > 0


def test_boot_digest_omits_user_prefs_section_when_empty() -> None:
    digest, tokens = compile_boot_digest(
        memories=[],
        tasks=[],
        repo_name="my-repo",
        user_memories=[],
    )
    assert digest == ""
    assert tokens == 0


def test_boot_digest_omits_prefs_section_when_none_passed() -> None:
    digest, tokens = compile_boot_digest(
        memories=[],
        tasks=[],
        repo_name="my-repo",
    )
    assert digest == ""
    assert tokens == 0


def test_boot_digest_user_prefs_appear_before_invariants() -> None:
    now = datetime.now(tz=UTC)
    inv = MemoryEntry(
        id="mem-inv",
        kind=MemoryKind.INVARIANT,
        title="Key invariant",
        summary="Never skip validation.",
        details="detail",
        source_type=SourceType.MANUAL,
        source_ref="manual",
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    pref = _make_user_pref("Prefers pytest", "Always use pytest.")
    digest, _ = compile_boot_digest(
        memories=[inv],
        tasks=[],
        repo_name="my-repo",
        user_memories=[pref],
    )
    prefs_idx = digest.find("Your preferences")
    inv_idx = digest.find("Key invariants")
    assert prefs_idx < inv_idx


# ---------------------------------------------------------------------------
# CLI commands via CliRunner
# ---------------------------------------------------------------------------


def test_cli_user_add(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = _cli_runner()
    result = runner.invoke(
        app,
        ["user", "add", "--title", "Prefers pytest", "--summary", "Always use pytest."],
    )
    assert result.exit_code == 0
    assert "Prefers pytest" in result.stdout or "User Preference" in result.stdout


def test_cli_user_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = _cli_runner()
    # Add one first
    runner.invoke(
        app,
        ["user", "add", "--title", "Prefers pytest", "--summary", "Always use pytest."],
    )
    result = runner.invoke(app, ["user", "list"])
    assert result.exit_code == 0
    assert "Prefers pytest" in result.stdout


def test_cli_user_show(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = _cli_runner()
    add_result = runner.invoke(
        app,
        ["user", "add", "--title", "Show me", "--summary", "A preference to show."],
    )
    assert add_result.exit_code == 0

    # Parse the ID from the added memory
    svc = OnmcService()
    mems = svc.list_user_memories(home=tmp_path)
    assert mems
    memory_id = mems[0].id

    result = runner.invoke(app, ["user", "show", memory_id])
    assert result.exit_code == 0
    assert "Show me" in result.stdout


def test_cli_user_remove(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = _cli_runner()
    runner.invoke(
        app,
        ["user", "add", "--title", "To remove", "--summary", "Will be removed."],
    )
    svc = OnmcService()
    mems = svc.list_user_memories(home=tmp_path)
    assert mems
    memory_id = mems[0].id

    result = runner.invoke(app, ["user", "remove", memory_id])
    assert result.exit_code == 0
    assert "Removed" in result.stdout or memory_id in result.stdout

    # Confirm deletion
    assert svc.get_user_memory(memory_id, home=tmp_path) is None


def test_cli_user_list_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = _cli_runner()
    result = runner.invoke(app, ["user", "list"])
    assert result.exit_code == 0
    assert "No user preferences" in result.stdout


def test_cli_user_show_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = _cli_runner()
    result = runner.invoke(app, ["user", "show", "user-doesnotexist"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# boot_digest service method passes user memories through
# ---------------------------------------------------------------------------


def test_boot_digest_service_includes_user_prefs(
    sample_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(sample_repo)
    svc = OnmcService(sample_repo)
    svc.init_project()
    svc.ingest()
    svc.add_user_memory(title="Always ruff", summary="Run ruff first.", home=tmp_path)

    digest_md, token_count = svc.boot_digest(home=tmp_path)
    assert token_count > 0
    assert "Your preferences" in digest_md
    assert "Always ruff" in digest_md
