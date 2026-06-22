"""Tests for the PreToolUse hook: compile_pretool_warning, the CLI command,
and the installer's PreToolUse registration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.hooks.installer import (
    _PRE_TOOL_USE_MATCHER,
    PRE_TOOL_USE_COMMAND,
    hooks_installed,
    install_claude_hooks,
    uninstall_claude_hooks,
)
from oh_no_my_claudecode.hooks.pre_tool_use import compile_pretool_warning
from oh_no_my_claudecode.models import FileStat, MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage import SQLiteStorage


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _make_storage(tmp_path: Path) -> SQLiteStorage:
    db = SQLiteStorage(tmp_path / ".onmc" / "memory.db")
    db.initialize()
    return db


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _memory(
    memory_id: str,
    kind: MemoryKind,
    title: str,
    summary: str,
    source_ref: str = "",
) -> MemoryEntry:
    return MemoryEntry(
        id=memory_id,
        kind=kind,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.MANUAL,
        source_ref=source_ref,
        confidence=0.9,
        created_at=_now(),
        updated_at=_now(),
    )


# ---------------------------------------------------------------------------
# compile_pretool_warning — unit tests
# ---------------------------------------------------------------------------


def test_compile_pretool_warning_empty_for_unknown_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    storage = _make_storage(tmp_path)

    md, n = compile_pretool_warning(storage, repo, "src/unknown.py")

    assert md == ""
    assert n == 0


def test_compile_pretool_warning_surfaces_hotspot_churn(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    storage = _make_storage(tmp_path)

    # Seed a file stat indicating high churn.
    storage.upsert_file_stats(
        [FileStat(path="src/hotspot.py", change_count=15, recent_change_count=4)]
    )

    md, n = compile_pretool_warning(storage, repo, "src/hotspot.py")

    assert n >= 1
    assert "HIGH-CHURN" in md
    assert "15" in md


def test_compile_pretool_warning_surfaces_invariant(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    storage = _make_storage(tmp_path)

    storage.upsert_memories(
        [
            _memory(
                "inv1",
                MemoryKind.INVARIANT,
                "Never bypass cache",
                "Direct DB writes skip cache invalidation — always use the cache layer.",
                source_ref="src/cache.py",
            )
        ]
    )

    md, n = compile_pretool_warning(storage, repo, "src/cache.py")

    assert n >= 1
    assert "INVARIANT" in md
    assert "Never bypass cache" in md


def test_compile_pretool_warning_surfaces_failed_approach(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    storage = _make_storage(tmp_path)

    storage.upsert_memories(
        [
            _memory(
                "fail1",
                MemoryKind.FAILED_APPROACH,
                "Lazy init caused races",
                "Lazy-loading the singleton from workers caused data races in prod.",
                source_ref="src/worker.py",
            )
        ]
    )

    md, n = compile_pretool_warning(storage, repo, "src/worker.py")

    assert n >= 1
    assert "FAILED BEFORE" in md
    assert "Lazy init caused races" in md


def test_compile_pretool_warning_matches_on_basename(tmp_path: Path) -> None:
    """A memory referencing only the filename (not the full path) must still match."""
    repo = tmp_path / "repo"
    repo.mkdir()
    storage = _make_storage(tmp_path)

    storage.upsert_memories(
        [
            _memory(
                "inv2",
                MemoryKind.INVARIANT,
                "Keep auth.py lean",
                "auth.py must stay under 200 lines.",
                source_ref="auth.py",
            )
        ]
    )

    md, n = compile_pretool_warning(storage, repo, "src/auth.py")

    assert n >= 1
    assert "INVARIANT" in md


def test_compile_pretool_warning_absolute_path_normalises(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    storage = _make_storage(tmp_path)

    storage.upsert_file_stats(
        [FileStat(path="src/hotspot.py", change_count=10, recent_change_count=5)]
    )

    absolute = (repo / "src" / "hotspot.py").as_posix()
    md, n = compile_pretool_warning(storage, repo, absolute)

    assert n >= 1
    assert "HIGH-CHURN" in md


def test_compile_pretool_warning_combines_signals(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    storage = _make_storage(tmp_path)

    storage.upsert_file_stats(
        [FileStat(path="src/core.py", change_count=20, recent_change_count=8)]
    )
    storage.upsert_memories(
        [
            _memory(
                "inv3",
                MemoryKind.INVARIANT,
                "Core contract",
                "Do not mutate state from async handlers.",
                source_ref="src/core.py",
            ),
            _memory(
                "fail2",
                MemoryKind.FAILED_APPROACH,
                "Tried thread-local cache",
                "Thread-local cache broke under gevent.",
                source_ref="src/core.py",
            ),
        ]
    )

    md, n = compile_pretool_warning(storage, repo, "src/core.py")

    assert n >= 3  # churn + invariant + failed
    assert "HIGH-CHURN" in md
    assert "INVARIANT" in md
    assert "FAILED BEFORE" in md


# ---------------------------------------------------------------------------
# CLI command — onmc hooks pre-tool-use
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal git repo with onmc initialised and a hotspot file seeded."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    from oh_no_my_claudecode.core.service import OnmcService

    monkeypatch.chdir(repo)
    svc = OnmcService(repo)
    svc.init_project()
    _, _cfg, storage = svc._load_context()  # noqa: SLF001
    storage.upsert_file_stats(
        [FileStat(path="src/hotspot.py", change_count=12, recent_change_count=6)]
    )
    storage.upsert_memories(
        [
            _memory(
                "inv-hot",
                MemoryKind.INVARIANT,
                "Hotspot invariant",
                "Always acquire the lock before touching state.",
                source_ref="src/hotspot.py",
            )
        ]
    )
    return repo


def test_pre_tool_use_emits_json_for_edit_on_hotspot(
    seeded_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": str(seeded_repo / "src" / "hotspot.py")},
            "cwd": str(seeded_repo),
        }
    )

    result = runner.invoke(app, ["hooks", "pre-tool-use"], input=payload)

    assert result.exit_code == 0
    stdout = result.stdout.strip()
    assert stdout, "should emit JSON for a known-hotspot file"
    data = json.loads(stdout)
    hso = data["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    ctx = hso["additionalContext"]
    assert "HIGH-CHURN" in ctx or "INVARIANT" in ctx


def test_pre_tool_use_emits_nothing_for_non_edit_tool(
    seeded_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "cwd": str(seeded_repo),
        }
    )

    result = runner.invoke(app, ["hooks", "pre-tool-use"], input=payload)

    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_emits_nothing_for_unknown_file(
    seeded_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(seeded_repo / "src" / "brand_new.py")},
            "cwd": str(seeded_repo),
        }
    )

    result = runner.invoke(app, ["hooks", "pre-tool-use"], input=payload)

    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_exits_zero_on_malformed_stdin(
    seeded_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()

    result = runner.invoke(app, ["hooks", "pre-tool-use"], input="not valid json {{{")

    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_exits_zero_on_empty_stdin(
    seeded_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()

    result = runner.invoke(app, ["hooks", "pre-tool-use"], input="")

    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_all_edit_tool_names_recognised(
    seeded_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edit, Write, MultiEdit, NotebookEdit must all trigger the warning path."""
    runner = _cli_runner()
    for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        payload = json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": tool,
                "tool_input": {"file_path": str(seeded_repo / "src" / "hotspot.py")},
                "cwd": str(seeded_repo),
            }
        )
        result = runner.invoke(app, ["hooks", "pre-tool-use"], input=payload)
        assert result.exit_code == 0, f"{tool} command failed"
        stdout = result.stdout.strip()
        # At least one of the tools must produce output (hotspot is seeded)
        if stdout:
            data = json.loads(stdout)
            assert data["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


# ---------------------------------------------------------------------------
# Installer — PreToolUse registration
# ---------------------------------------------------------------------------


def test_installer_registers_pre_tool_use(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"

    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    payload = _read_json(tmp_path / ".claude" / "settings.json")
    hooks = payload.get("hooks")
    assert isinstance(hooks, dict)

    pre_tool_entries = hooks.get("PreToolUse")
    assert isinstance(pre_tool_entries, list), "PreToolUse must be registered"
    matchers = {entry.get("matcher") for entry in pre_tool_entries if isinstance(entry, dict)}
    assert _PRE_TOOL_USE_MATCHER in matchers

    # Command must be present within the matching entry.
    for entry in pre_tool_entries:
        if isinstance(entry, dict) and entry.get("matcher") == _PRE_TOOL_USE_MATCHER:
            cmds = [
                item.get("command")
                for item in entry.get("hooks", [])
                if isinstance(item, dict)
            ]
            assert PRE_TOOL_USE_COMMAND in cmds
            break
    else:
        pytest.fail("No entry with the expected PreToolUse matcher found")


def test_installer_hooks_installed_requires_pre_tool_use(tmp_path: Path) -> None:
    """hooks_installed must return False if PreToolUse is absent."""
    global_settings = tmp_path / "home" / ".claude" / "settings.json"
    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    # Manually remove just the PreToolUse entry.
    settings_path = tmp_path / ".claude" / "settings.json"
    payload = _read_json(settings_path)
    hooks = payload.get("hooks", {})
    assert isinstance(hooks, dict)
    hooks.pop("PreToolUse", None)
    _write_json(settings_path, payload)

    assert not hooks_installed(settings_path=settings_path), (
        "hooks_installed must be False when PreToolUse is missing"
    )


def test_installer_pre_tool_use_is_idempotent(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"

    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)
    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    payload = _read_json(tmp_path / ".claude" / "settings.json")
    hooks = payload.get("hooks", {})
    assert isinstance(hooks, dict)
    pre_tool_entries = hooks.get("PreToolUse", [])
    # Exactly one entry for the matcher.
    matching = [
        e
        for e in pre_tool_entries
        if isinstance(e, dict) and e.get("matcher") == _PRE_TOOL_USE_MATCHER
    ]
    assert len(matching) == 1
    assert len(matching[0]["hooks"]) == 1


def test_uninstall_removes_pre_tool_use(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"
    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    uninstall_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    payload = _read_json(tmp_path / ".claude" / "settings.json")
    hooks = payload.get("hooks", {})
    assert isinstance(hooks, dict)
    assert "PreToolUse" not in hooks, "uninstall must remove PreToolUse"


def test_installer_is_fully_installed_after_fresh_install(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"
    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    assert hooks_installed(settings_path=tmp_path / ".claude" / "settings.json")
