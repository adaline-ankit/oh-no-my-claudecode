from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.hooks.boot_digest import BOOT_DIGEST_MAX_TOKENS, compile_boot_digest
from oh_no_my_claudecode.hooks.installer import hooks_installed, install_claude_hooks
from oh_no_my_claudecode.models import (
    AttemptKind,
    AttemptStatus,
    MemoryEntry,
    MemoryKind,
    SourceType,
    TaskRecord,
    TaskStatus,
)


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _make_memory(
    *,
    kind: MemoryKind,
    title: str,
    summary: str,
    confidence: float = 0.8,
) -> MemoryEntry:
    now = datetime.now(tz=UTC)
    return MemoryEntry(
        id=f"mem-{title[:8].lower().replace(' ', '-')}",
        kind=kind,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.LLM_EXTRACTED,
        source_ref="doc:README.md",
        confidence=confidence,
        created_at=now,
        updated_at=now,
    )


def _make_task(*, title: str, status: TaskStatus = TaskStatus.ACTIVE) -> TaskRecord:
    now = datetime.now(tz=UTC)
    return TaskRecord(
        task_id="task-abc123",
        title=title,
        description="Task description.",
        status=status,
        created_at=now,
        started_at=now,
        ended_at=None,
        repo_root="/home/runner/repo",
        branch="main",
        labels=[],
        final_summary=None,
        final_outcome=None,
        confidence=None,
    )


# ---------------------------------------------------------------------------
# compile_boot_digest — unit tests (pure compiler, no stdin/stdout)
# ---------------------------------------------------------------------------


def test_boot_digest_contains_invariants_and_hotspots() -> None:
    memories = [
        _make_memory(
            kind=MemoryKind.INVARIANT,
            title="No direct DB writes",
            summary="All writes go through the repository layer.",
        ),
        _make_memory(
            kind=MemoryKind.HOTSPOT,
            title="cache.py high churn",
            summary="This file changes every sprint; check it first.",
        ),
    ]
    # terse=False: verify the full markdown output shape.
    digest, tokens = compile_boot_digest(
        memories=memories,
        tasks=[],
        repo_name="my-repo",
        terse=False,
    )

    assert "## Repo brain: my-repo" in digest
    assert "No direct DB writes" in digest
    assert "cache.py high churn" in digest
    assert tokens > 0
    assert tokens <= BOOT_DIGEST_MAX_TOKENS


def test_boot_digest_includes_active_tasks() -> None:
    task = _make_task(title="Fix cache invalidation bug")
    digest, tokens = compile_boot_digest(
        memories=[],
        tasks=[task],
        repo_name="my-repo",
    )

    assert "Fix cache invalidation bug" in digest
    assert "task-abc123" in digest
    assert tokens > 0


def test_boot_digest_empty_store_returns_empty_string() -> None:
    digest, tokens = compile_boot_digest(
        memories=[],
        tasks=[],
        repo_name="my-repo",
    )

    assert digest == ""
    assert tokens == 0


def test_boot_digest_excludes_rejected_memories() -> None:
    """Memories with feedback_score <= -0.5 are excluded."""
    bad_memory = _make_memory(
        kind=MemoryKind.INVARIANT,
        title="Wrong invariant",
        summary="This was marked wrong.",
    )
    bad_memory = bad_memory.model_copy(update={"feedback_score": -0.6})

    digest, tokens = compile_boot_digest(
        memories=[bad_memory],
        tasks=[],
        repo_name="my-repo",
    )

    assert digest == ""
    assert tokens == 0


def test_boot_digest_excludes_non_active_tasks() -> None:
    inactive_task = _make_task(title="Old task", status=TaskStatus.SOLVED)

    digest, tokens = compile_boot_digest(
        memories=[],
        tasks=[inactive_task],
        repo_name="my-repo",
    )

    assert digest == ""
    assert tokens == 0


def test_boot_digest_is_token_bounded_with_many_memories() -> None:
    """Large stores must still produce a digest within the token cap (full mode)."""
    memories = [
        _make_memory(
            kind=MemoryKind.INVARIANT,
            title=f"Invariant {i}: always validate input before processing in module X",
            summary=(
                f"This is a long summary for invariant {i}. "
                "Never skip the validation step even under high load. "
                "The downstream handler assumes clean input."
            ),
        )
        for i in range(20)
    ]

    # terse=False: full markdown must still respect the token budget.
    digest, tokens = compile_boot_digest(
        memories=memories,
        tasks=[],
        repo_name="my-repo",
        terse=False,
    )

    assert tokens <= BOOT_DIGEST_MAX_TOKENS
    assert "## Repo brain: my-repo" in digest


def test_boot_digest_sections_ordering() -> None:
    """Invariants appear before hotspots, active tasks come last."""
    memories = [
        _make_memory(kind=MemoryKind.HOTSPOT, title="Hot file", summary="Changes a lot."),
        _make_memory(kind=MemoryKind.INVARIANT, title="Key rule", summary="Never skip X."),
    ]
    task = _make_task(title="Active work")
    digest, _ = compile_boot_digest(memories=memories, tasks=[task], repo_name="my-repo")

    inv_idx = digest.find("Key rule")
    hot_idx = digest.find("Hot file")
    task_idx = digest.find("Active work")
    assert inv_idx < hot_idx < task_idx


# ---------------------------------------------------------------------------
# CLI: session-start with source "startup" emits boot digest JSON
# ---------------------------------------------------------------------------


def test_session_start_startup_emits_boot_digest_json(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    result = runner.invoke(
        app,
        ["hooks", "session-start"],
        input=json.dumps(
            {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(sample_repo)}
        ),
    )

    assert result.exit_code == 0
    # stdout must be entirely valid JSON
    parsed = json.loads(result.stdout)
    assert set(parsed) == {"hookSpecificOutput"}
    hook_output = parsed["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "SessionStart"
    assert isinstance(hook_output["additionalContext"], str)
    assert len(hook_output["additionalContext"]) > 0
    # In terse mode (hook default) the header is [onmc:<repo>]; full mode has "Repo brain".
    # Either way the content must be non-empty and contain the repo name.
    ctx = hook_output["additionalContext"]
    assert "onmc" in ctx.lower() or "Repo brain" in ctx


def test_session_start_resume_emits_boot_digest_json(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    result = runner.invoke(
        app,
        ["hooks", "session-start"],
        input=json.dumps({"source": "resume"}),
    )

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "hookSpecificOutput" in parsed


def test_session_start_clear_emits_boot_digest_json(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    result = runner.invoke(
        app,
        ["hooks", "session-start"],
        input=json.dumps({"source": "clear"}),
    )

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_session_start_compact_still_emits_continuation_brief(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """source == 'compact' must still emit the continuation brief (unchanged behavior)."""
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    task = service.start_task(title="Fix cache bug", description="Cache issue.", labels=[])
    service.add_attempt(
        task.task_id,
        summary="Try a cache-only fix.",
        kind=AttemptKind.FIX_ATTEMPT,
        status=AttemptStatus.REJECTED,
        reasoning_summary="Start at the cache boundary.",
        evidence_for="Cache file has churn.",
        evidence_against="Worker path still failed.",
        files_touched=["src/cache.py"],
    )
    service.pre_compact()

    result = runner.invoke(
        app,
        ["hooks", "session-start"],
        input=json.dumps({"source": "compact"}),
    )

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    hook_output = parsed["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "SessionStart"
    # Continuation brief has these headings
    assert "## Where we are" in hook_output["additionalContext"]
    assert "## Next step" in hook_output["additionalContext"]


def test_session_start_startup_empty_store_clean_stdout_exit_zero(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No memories → no output on stdout, exit 0."""
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    # No ingest — empty store

    result = runner.invoke(
        app,
        ["hooks", "session-start"],
        input=json.dumps({"source": "startup"}),
    )

    assert result.exit_code == 0
    assert result.stdout == ""


def test_session_start_startup_writes_boot_digest_artifact(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    result = runner.invoke(
        app,
        ["hooks", "session-start"],
        input=json.dumps({"source": "startup"}),
    )

    assert result.exit_code == 0
    artifact = sample_repo / ".onmc" / "boot-digest.md"
    assert artifact.exists()
    content = artifact.read_text(encoding="utf-8")
    # In terse mode the artifact starts with [onmc:<repo>]; full mode uses "Repo brain".
    assert "onmc" in content.lower() or "Repo brain" in content


def test_session_start_startup_no_onmc_init_exits_zero_clean_stdout(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If onmc isn't initialized at all, the hook must exit 0 with empty stdout."""
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    # No init_project

    result = runner.invoke(
        app,
        ["hooks", "session-start"],
        input=json.dumps({"source": "startup"}),
    )

    assert result.exit_code == 0
    assert result.stdout == ""
    assert "ONMC session-start warning" in result.stderr


# ---------------------------------------------------------------------------
# Installer: SessionStart hook now uses matcher "" (all sources)
# ---------------------------------------------------------------------------


def test_installer_session_start_hook_uses_empty_matcher(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"
    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    settings_path = tmp_path / ".claude" / "settings.json"
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = payload["hooks"]
    session_start_entries = hooks["SessionStart"]

    # There should be exactly one entry with matcher="" covering all sources.
    assert len(session_start_entries) == 1
    entry = session_start_entries[0]
    assert entry["matcher"] == ""
    assert any(
        h.get("command") == "onmc hooks session-start"
        for h in entry["hooks"]
    )


def test_installer_hooks_installed_returns_true_with_empty_matcher(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"
    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    assert hooks_installed(settings_path=tmp_path / ".claude" / "settings.json")
