from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.hooks.brief_compiler import compile_continuation_brief
from oh_no_my_claudecode.hooks.installer import (
    hooks_installed,
    install_claude_hooks,
    legacy_global_hooks_present,
    mcp_registered,
    uninstall_claude_hooks,
)
from oh_no_my_claudecode.hooks.pre_compact import build_compaction_snapshot
from oh_no_my_claudecode.models import AttemptKind, AttemptStatus, CompactionSnapshotRecord
from oh_no_my_claudecode.utils.time import utc_now


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


def _write_transcript(path: Path, repo_root: Path) -> None:
    lines = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Found the bug in the cache layer."},
                    {
                        "type": "tool_use",
                        "name": "Edit",
                        "input": {"file_path": (repo_root / "src" / "cache.py").as_posix()},
                    },
                ]
            },
        },
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "The cache-only fix did not cover the worker path.\n"
                            "Next: add a regression test for the worker refresh."
                        ),
                    }
                ]
            },
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect Path.home() so install/uninstall never touch the real user settings."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("oh_no_my_claudecode.hooks.installer.Path.home", lambda: home)
    return home


# ---------------------------------------------------------------------------
# Snapshot + brief compiler
# ---------------------------------------------------------------------------


def test_compaction_snapshot_creation_and_retrieval(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    task = service.start_task(
        title="Fix cache bug",
        description="Track the cache issue.",
        labels=[],
    )
    service.add_attempt(
        task.task_id,
        summary="Try a cache-only fix first.",
        kind=AttemptKind.FIX_ATTEMPT,
        status=AttemptStatus.REJECTED,
        reasoning_summary="Start at the cache boundary.",
        evidence_for="The cache file has churn.",
        evidence_against="The worker path still failed.",
        files_touched=["src/cache.py"],
    )

    snapshot = service.pre_compact()
    latest = service.latest_compaction_snapshot()

    assert latest is not None
    assert latest.id == snapshot.id
    assert latest.task_id == task.task_id
    assert "src/cache.py" in latest.active_files


def test_snapshot_enriched_from_transcript_when_no_task_records(tmp_path: Path) -> None:
    transcript_path = tmp_path / "session.jsonl"
    _write_transcript(transcript_path, tmp_path)

    snapshot = build_compaction_snapshot(
        task=None,
        attempts=[],
        artifacts=[],
        outputs=[],
        memories=[],
        transcript_path=transcript_path,
        repo_root=tmp_path,
    )

    assert "src/cache.py" in snapshot.active_files
    assert snapshot.working_hypothesis is not None
    assert "worker path" in snapshot.working_hypothesis
    assert snapshot.next_step is not None
    assert snapshot.next_step.startswith("Next: add a regression test")


def test_snapshot_merges_transcript_files_ahead_of_task_files(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    task = service.start_task(title="Fix cache bug", description="Cache issue.", labels=[])
    service.add_attempt(
        task.task_id,
        summary="Try a cache-only fix first.",
        kind=AttemptKind.FIX_ATTEMPT,
        status=AttemptStatus.REJECTED,
        reasoning_summary="Start at the cache boundary.",
        evidence_for="The cache file has churn.",
        evidence_against="The worker path still failed.",
        files_touched=["src/worker.py"],
    )
    transcript_path = sample_repo / ".onmc" / "session.jsonl"
    _write_transcript(transcript_path, sample_repo)

    snapshot = service.pre_compact(transcript_path=transcript_path)

    assert snapshot.active_files.index("src/cache.py") < snapshot.active_files.index(
        "src/worker.py"
    )


def test_snapshot_tolerates_missing_transcript(tmp_path: Path) -> None:
    snapshot = build_compaction_snapshot(
        task=None,
        attempts=[],
        artifacts=[],
        outputs=[],
        memories=[],
        transcript_path=tmp_path / "does-not-exist.jsonl",
        repo_root=tmp_path,
    )

    assert snapshot.active_files == []
    assert snapshot.working_hypothesis is None
    assert snapshot.next_step is None


def test_continuation_brief_compiler_handles_full_snapshot(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    task = service.start_task(
        title="Fix cache bug",
        description="Track the cache issue.",
        labels=[],
    )
    decision = next(
        memory
        for memory in service.list_memories()
        if memory.kind.value in {"decision", "invariant", "validation_rule"}
    )
    snapshot = CompactionSnapshotRecord(
        id="snapshot-deadbeef",
        task_id=task.task_id,
        timestamp=utc_now(),
        active_files=["src/cache.py"],
        recent_decisions=[decision.id],
        working_hypothesis="Start at the shared cache boundary before narrowing the patch.",
        last_error_trace="Worker refresh still fails after the cache-only change.",
        next_step="Inspect src/cache.py and the adjacent worker caller path.",
        brief_token_count=None,
        continuation_brief_md=None,
    )

    brief, token_count = compile_continuation_brief(
        snapshot=snapshot,
        task=task,
        decisions=[decision],
    )

    assert "## Where we are" in brief
    assert "## What was just decided" in brief
    assert "## What was being attempted" in brief
    assert "## Next step" in brief
    assert decision.title in brief
    assert token_count > 0


def test_continuation_brief_compiler_handles_minimal_snapshot() -> None:
    snapshot = CompactionSnapshotRecord(
        id="snapshot-feedbabe",
        task_id=None,
        timestamp=utc_now(),
        active_files=[],
        recent_decisions=[],
        working_hypothesis=None,
        last_error_trace=None,
        next_step=None,
        brief_token_count=None,
        continuation_brief_md=None,
    )

    brief, token_count = compile_continuation_brief(
        snapshot=snapshot,
        task=None,
        decisions=[],
    )

    assert "Active task context is unavailable." in brief
    assert "- unavailable." in brief
    assert "Next step unavailable." in brief
    assert token_count > 0


# ---------------------------------------------------------------------------
# Installer: project-scoped settings + .mcp.json
# ---------------------------------------------------------------------------


def test_installer_writes_project_scoped_hooks_and_mcp(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"

    result = install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    payload = _read_json(tmp_path / ".claude" / "settings.json")
    hooks = payload["hooks"]
    assert isinstance(hooks, dict)
    assert hooks["PreCompact"] == [
        {"matcher": "", "hooks": [{"type": "command", "command": "onmc hooks pre-compact"}]}
    ]
    assert hooks["SessionStart"] == [
        {
            "matcher": "compact",
            "hooks": [{"type": "command", "command": "onmc hooks session-start"}],
        }
    ]
    assert "PostCompact" not in hooks
    assert "mcpServers" not in payload
    mcp_payload = _read_json(tmp_path / ".mcp.json")
    assert mcp_payload == {
        "mcpServers": {"onmc": {"command": "onmc", "args": ["serve", "--mcp"]}}
    }
    assert result.backup_created is True
    assert result.legacy_global_cleaned is False
    assert hooks_installed(settings_path=tmp_path / ".claude" / "settings.json")
    assert mcp_registered(mcp_path=tmp_path / ".mcp.json")


def test_installer_merges_without_destroying_other_settings(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    _write_json(
        settings_path,
        {
            "theme": "dark",
            "hooks": {
                "PreCompact": [
                    {"matcher": "python", "hooks": [{"type": "command", "command": "echo hi"}]}
                ],
                "SessionStart": [
                    {"matcher": "startup", "hooks": [{"type": "command", "command": "echo up"}]}
                ],
            },
        },
    )
    _write_json(
        tmp_path / ".mcp.json",
        {"mcpServers": {"existing": {"command": "existing-mcp", "args": ["serve"]}}},
    )

    install_claude_hooks(
        repo_root=tmp_path,
        global_settings_path=tmp_path / "home" / ".claude" / "settings.json",
    )

    payload = _read_json(settings_path)
    assert payload["theme"] == "dark"
    hooks = payload["hooks"]
    assert isinstance(hooks, dict)
    assert {entry["matcher"] for entry in hooks["PreCompact"]} == {"python", ""}
    assert {entry["matcher"] for entry in hooks["SessionStart"]} == {"startup", "compact"}
    mcp_payload = _read_json(tmp_path / ".mcp.json")
    servers = mcp_payload["mcpServers"]
    assert isinstance(servers, dict)
    assert servers["existing"] == {"command": "existing-mcp", "args": ["serve"]}
    assert servers["onmc"] == {"command": "onmc", "args": ["serve", "--mcp"]}


def test_installer_is_idempotent(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"

    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)
    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    payload = _read_json(tmp_path / ".claude" / "settings.json")
    hooks = payload["hooks"]
    assert isinstance(hooks, dict)
    assert len(hooks["PreCompact"]) == 1
    assert len(hooks["PreCompact"][0]["hooks"]) == 1
    assert len(hooks["SessionStart"]) == 1
    assert len(hooks["SessionStart"][0]["hooks"]) == 1


def test_installer_backup_is_written_only_once(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    backup_path = tmp_path / ".claude" / "settings.json.onmc-backup"
    global_settings = tmp_path / "home" / ".claude" / "settings.json"
    _write_json(settings_path, {"theme": "light"})

    first = install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)
    second = install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    assert first.backup_created is True
    assert second.backup_created is False
    # The backup must hold the PRE-install settings, not the hooked ones.
    assert _read_json(backup_path) == {"theme": "light"}


def test_installer_migrates_legacy_project_entries(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    _write_json(
        settings_path,
        {
            "hooks": {
                "PostCompact": [
                    {
                        "matcher": "",
                        "hooks": [{"type": "command", "command": "onmc hooks post-compact"}],
                    }
                ]
            },
            "mcpServers": {"onmc": {"command": "onmc", "args": ["serve", "--mcp"]}},
        },
    )

    install_claude_hooks(
        repo_root=tmp_path,
        global_settings_path=tmp_path / "home" / ".claude" / "settings.json",
    )

    payload = _read_json(settings_path)
    hooks = payload["hooks"]
    assert isinstance(hooks, dict)
    assert "PostCompact" not in hooks
    # mcpServers in settings.json is ignored by Claude Code; the onmc key is migrated out.
    assert "mcpServers" not in payload


def test_installer_cleans_legacy_global_settings(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"
    _write_json(
        global_settings,
        {
            "theme": "dark",
            "hooks": {
                "PreCompact": [
                    {
                        "matcher": "",
                        "hooks": [
                            {"type": "command", "command": "onmc hooks pre-compact"},
                            {"type": "command", "command": "echo keep-me"},
                        ],
                    }
                ],
                "PostCompact": [
                    {
                        "matcher": "",
                        "hooks": [{"type": "command", "command": "onmc hooks post-compact"}],
                    }
                ],
            },
            "mcpServers": {
                "onmc": {"command": "onmc", "args": ["serve", "--mcp"]},
                "other": {"command": "other-mcp"},
            },
        },
    )
    assert legacy_global_hooks_present(settings_path=global_settings)

    result = install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    assert result.legacy_global_cleaned is True
    payload = _read_json(global_settings)
    assert payload["theme"] == "dark"
    hooks = payload["hooks"]
    assert isinstance(hooks, dict)
    assert "PostCompact" not in hooks
    assert hooks["PreCompact"] == [
        {"matcher": "", "hooks": [{"type": "command", "command": "echo keep-me"}]}
    ]
    assert payload["mcpServers"] == {"other": {"command": "other-mcp"}}
    assert not legacy_global_hooks_present(settings_path=global_settings)


def test_uninstall_is_surgical_and_keeps_backup(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    backup_path = tmp_path / ".claude" / "settings.json.onmc-backup"
    global_settings = tmp_path / "home" / ".claude" / "settings.json"
    _write_json(
        settings_path,
        {
            "theme": "dark",
            "hooks": {
                "PreCompact": [
                    {"matcher": "python", "hooks": [{"type": "command", "command": "echo hi"}]}
                ]
            },
        },
    )
    _write_json(tmp_path / ".mcp.json", {"mcpServers": {"other": {"command": "other-mcp"}}})
    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    legacy_cleaned = uninstall_claude_hooks(
        repo_root=tmp_path,
        global_settings_path=global_settings,
    )

    payload = _read_json(settings_path)
    assert payload["theme"] == "dark"
    hooks = payload["hooks"]
    assert isinstance(hooks, dict)
    assert hooks["PreCompact"] == [
        {"matcher": "python", "hooks": [{"type": "command", "command": "echo hi"}]}
    ]
    assert "SessionStart" not in hooks
    assert not hooks_installed(settings_path=settings_path)
    mcp_payload = _read_json(tmp_path / ".mcp.json")
    assert mcp_payload == {"mcpServers": {"other": {"command": "other-mcp"}}}
    # The backup is a safety artifact, never restored wholesale.
    assert backup_path.exists()
    assert legacy_cleaned is False


def test_uninstall_removes_mcp_file_when_onmc_was_the_only_server(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"
    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)
    assert (tmp_path / ".mcp.json").exists()

    uninstall_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    assert not (tmp_path / ".mcp.json").exists()


def test_uninstall_cleans_legacy_global_settings(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"
    _write_json(
        global_settings,
        {
            "hooks": {
                "PostCompact": [
                    {
                        "matcher": "",
                        "hooks": [{"type": "command", "command": "onmc hooks post-compact"}],
                    }
                ]
            }
        },
    )

    legacy_cleaned = uninstall_claude_hooks(
        repo_root=tmp_path,
        global_settings_path=global_settings,
    )

    assert legacy_cleaned is True
    payload = _read_json(global_settings)
    assert "hooks" not in payload


# ---------------------------------------------------------------------------
# CLI: install command
# ---------------------------------------------------------------------------


def test_hooks_install_yes_is_non_interactive_and_can_skip_mcp(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_home: Path,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    result = runner.invoke(app, ["hooks", "install", "--yes", "--no-mcp"])

    payload = _read_json(sample_repo / ".claude" / "settings.json")
    assert result.exit_code == 0
    assert "Hooks installed" in result.stdout
    assert not (sample_repo / ".mcp.json").exists()
    hooks = payload["hooks"]
    assert isinstance(hooks, dict)
    assert "PreCompact" in hooks
    assert "SessionStart" in hooks
    assert "PostCompact" not in hooks
    assert "mcpServers" not in payload


def test_hooks_install_yes_registers_project_mcp(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_home: Path,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    result = runner.invoke(app, ["hooks", "install", "--yes"])

    assert result.exit_code == 0
    mcp_payload = _read_json(sample_repo / ".mcp.json")
    assert mcp_payload == {
        "mcpServers": {"onmc": {"command": "onmc", "args": ["serve", "--mcp"]}}
    }


def test_hooks_uninstall_cli_removes_project_entries(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_home: Path,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    runner.invoke(app, ["hooks", "install", "--yes"])

    result = runner.invoke(app, ["hooks", "uninstall"])

    assert result.exit_code == 0
    payload = _read_json(sample_repo / ".claude" / "settings.json")
    assert "hooks" not in payload
    assert not (sample_repo / ".mcp.json").exists()
    assert (sample_repo / ".claude" / "settings.json.onmc-backup").exists()


# ---------------------------------------------------------------------------
# CLI: pre-compact hook command
# ---------------------------------------------------------------------------


def test_pre_compact_cli_exits_zero_even_when_no_active_task(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    result = runner.invoke(app, ["hooks", "pre-compact"], input="")

    assert result.exit_code == 0
    assert result.stdout == ""


def test_pre_compact_cli_exits_zero_when_onmc_state_is_missing(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)

    result = runner.invoke(app, ["hooks", "pre-compact"], input="")

    assert result.exit_code == 0
    assert result.stdout == ""
    assert "ONMC pre-compact warning" in result.stderr


def test_pre_compact_cli_exits_zero_with_corrupted_database(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    (sample_repo / ".onmc" / "memory.db").write_text("not-a-sqlite-database", encoding="utf-8")

    result = runner.invoke(app, ["hooks", "pre-compact"], input="")

    assert result.exit_code == 0
    assert result.stdout == ""
    assert "ONMC pre-compact warning" in result.stderr


def test_pre_compact_cli_reads_transcript_path_from_stdin_payload(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    transcript_path = sample_repo / ".onmc" / "session.jsonl"
    _write_transcript(transcript_path, sample_repo)
    payload = {
        "session_id": "sess-1",
        "transcript_path": transcript_path.as_posix(),
        "cwd": sample_repo.as_posix(),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
        "custom_instructions": "",
    }

    result = runner.invoke(app, ["hooks", "pre-compact"], input=json.dumps(payload))

    assert result.exit_code == 0
    assert result.stdout == ""
    snapshot = service.latest_compaction_snapshot()
    assert snapshot is not None
    assert "src/cache.py" in snapshot.active_files


def test_pre_compact_cli_tolerates_invalid_stdin(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    result = runner.invoke(app, ["hooks", "pre-compact"], input="this is { not json")

    assert result.exit_code == 0
    assert result.stdout == ""
    assert service.latest_compaction_snapshot() is not None


# ---------------------------------------------------------------------------
# CLI: session-start hook command (stdout JSON contract)
# ---------------------------------------------------------------------------


def _prepare_snapshot(sample_repo: Path) -> OnmcService:
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    task = service.start_task(
        title="Fix cache bug",
        description="Track the cache issue.",
        labels=[],
    )
    service.add_attempt(
        task.task_id,
        summary="Try a cache-only fix first.",
        kind=AttemptKind.FIX_ATTEMPT,
        status=AttemptStatus.REJECTED,
        reasoning_summary="Start at the cache boundary.",
        evidence_for="The cache file has churn.",
        evidence_against="The worker path still failed.",
        files_touched=["src/cache.py"],
    )
    service.pre_compact()
    return service


def test_session_start_emits_only_additional_context_json(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    _prepare_snapshot(sample_repo)
    payload = {
        "session_id": "sess-1",
        "transcript_path": (sample_repo / "session.jsonl").as_posix(),
        "cwd": sample_repo.as_posix(),
        "hook_event_name": "SessionStart",
        "source": "compact",
    }

    result = runner.invoke(app, ["hooks", "session-start"], input=json.dumps(payload))

    assert result.exit_code == 0
    # Stdout must parse as JSON in its entirety — anything else corrupts injection.
    parsed = json.loads(result.stdout)
    assert set(parsed) == {"hookSpecificOutput"}
    hook_output = parsed["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "SessionStart"
    assert "## Where we are" in hook_output["additionalContext"]
    assert "## Next step" in hook_output["additionalContext"]


def test_session_start_writes_debug_artifact_under_state_dir(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    _prepare_snapshot(sample_repo)

    result = runner.invoke(
        app,
        ["hooks", "session-start"],
        input=json.dumps({"source": "compact"}),
    )

    assert result.exit_code == 0
    artifact = sample_repo / ".onmc" / "continuation-brief.md"
    assert artifact.exists()
    assert "## Where we are" in artifact.read_text(encoding="utf-8")


def test_session_start_skips_injection_for_non_compact_sources(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    _prepare_snapshot(sample_repo)

    result = runner.invoke(
        app,
        ["hooks", "session-start"],
        input=json.dumps({"source": "startup"}),
    )

    assert result.exit_code == 0
    assert result.stdout == ""


def test_session_start_is_permissive_when_stdin_is_missing(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    _prepare_snapshot(sample_repo)

    result = runner.invoke(app, ["hooks", "session-start"], input="")

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_session_start_exits_zero_with_clean_stdout_when_no_snapshot_exists(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    result = runner.invoke(
        app,
        ["hooks", "session-start"],
        input=json.dumps({"source": "compact"}),
    )

    assert result.exit_code == 0
    assert result.stdout == ""
    assert "ONMC session-start warning" in result.stderr


def test_post_compact_alias_delegates_to_session_start(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    _prepare_snapshot(sample_repo)

    result = runner.invoke(
        app,
        ["hooks", "post-compact"],
        input=json.dumps({"source": "compact"}),
    )

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["hookSpecificOutput"]["hookEventName"] == "SessionStart"
