from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.hooks.brief_compiler import compile_continuation_brief
from oh_no_my_claudecode.hooks.installer import install_claude_hooks
from oh_no_my_claudecode.models import AttemptKind, AttemptStatus, CompactionSnapshotRecord
from oh_no_my_claudecode.utils.time import utc_now


def test_compaction_snapshot_creation_and_retrieval(
    sample_repo: Path,
    monkeypatch: object,
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


def test_continuation_brief_compiler_handles_full_snapshot(
    sample_repo: Path,
    monkeypatch: object,
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


def test_installer_merges_existing_settings_without_destroying_other_keys(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    backup_path = tmp_path / ".claude" / "settings.json.onmc-backup"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "theme": "dark",
                "hooks": {
                    "PreCompact": [
                        {
                            "matcher": "python",
                            "hooks": [{"type": "command", "command": "echo existing"}],
                        }
                    ]
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    install_claude_hooks(settings_path=settings_path, backup_path=backup_path, add_mcp_server=False)

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["theme"] == "dark"
    assert backup_path.exists()
    assert "PreCompact" in payload["hooks"]
    assert "PostCompact" in payload["hooks"]


def test_installer_creates_backup_before_writing(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    backup_path = tmp_path / ".claude" / "settings.json.onmc-backup"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text('{"theme":"light"}\n', encoding="utf-8")

    install_claude_hooks(settings_path=settings_path, backup_path=backup_path, add_mcp_server=True)

    assert json.loads(backup_path.read_text(encoding="utf-8")) == {"theme": "light"}


def test_pre_compact_cli_exits_zero_even_when_no_active_task(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    result = runner.invoke(app, ["hooks", "pre-compact"])

    assert result.exit_code == 0
