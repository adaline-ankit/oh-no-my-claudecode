from __future__ import annotations

import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.brief.compiler import score_memories
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.rendering.console import console, render_memory_list
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now


def test_confirm_and_reject_adjust_feedback_score(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    memory = service.add_memory(
        kind=MemoryKind.INVARIANT,
        title="Repository layer only",
        summary="All writes must go through the repository layer.",
    )

    confirmed = service.confirm_memory(memory.id)
    rejected = service.reject_memory(memory.id)

    assert confirmed.feedback_score == 0.3
    assert rejected.feedback_score == -0.2


def test_rejected_records_are_excluded_from_brief_candidates() -> None:
    now = utc_now()
    rejected = MemoryEntry(
        id="memory-rejected",
        kind=MemoryKind.INVARIANT,
        title="Rejected invariant",
        summary="This should be excluded.",
        details="This should be excluded.",
        source_type=SourceType.MANUAL,
        source_ref="manual:one",
        tags=["cache"],
        confidence=1.0,
        feedback_score=-0.5,
        created_at=now,
        updated_at=now,
    )
    accepted = MemoryEntry(
        id="memory-accepted",
        kind=MemoryKind.DECISION,
        title="Accepted decision",
        summary="This remains relevant to the cache task.",
        details="This remains relevant to the cache task.",
        source_type=SourceType.MANUAL,
        source_ref="manual:two",
        tags=["cache"],
        confidence=1.0,
        feedback_score=0.3,
        created_at=now,
        updated_at=now,
    )

    ranked = score_memories("fix cache task", [rejected, accepted], limit=5)

    assert [memory.id for memory in ranked] == ["memory-accepted"]


def test_edit_updates_summary_and_resets_feedback(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    memory = service.add_memory(
        kind=MemoryKind.GOTCHA,
        title="Original summary",
        summary="Old summary.",
    )
    service.confirm_memory(memory.id)

    updated = service.edit_memory(memory.id, "New edited summary.")

    assert updated.summary == "New edited summary."
    assert updated.details == "New edited summary."
    assert updated.feedback_score == 0.0


def test_memory_list_display_shows_feedback_indicator() -> None:
    now = utc_now()
    confirmed = MemoryEntry(
        id="memory-confirmed",
        kind=MemoryKind.INVARIANT,
        title="Confirmed",
        summary="Confirmed memory.",
        details="Confirmed memory.",
        source_type=SourceType.MANUAL,
        source_ref="manual:confirmed",
        tags=[],
        confidence=0.9,
        feedback_score=0.3,
        created_at=now,
        updated_at=now,
    )
    rejected = MemoryEntry(
        id="memory-rejected",
        kind=MemoryKind.GOTCHA,
        title="Rejected",
        summary="Rejected memory.",
        details="Rejected memory.",
        source_type=SourceType.MANUAL,
        source_ref="manual:rejected",
        tags=[],
        confidence=0.7,
        feedback_score=-0.5,
        created_at=now,
        updated_at=now,
    )

    with console.capture() as capture:
        render_memory_list([confirmed, rejected])
    output = capture.get()

    assert "✓" in output
    assert "✗" in output


def test_feedback_score_migration_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
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
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

    storage = SQLiteStorage(db_path)
    storage.initialize()
    storage.initialize()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}

    assert "feedback_score" in columns


def test_memory_cli_feedback_and_mine_hint(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    monkeypatch.setattr("oh_no_my_claudecode.mine.transcript.Path.home", lambda: tmp_path)

    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["ingest"]).exit_code == 0
    service = OnmcService(sample_repo)
    memory = service.add_memory(
        kind=MemoryKind.INVARIANT,
        title="CLI feedback memory",
        summary="Initial CLI feedback summary.",
    )

    confirm_result = runner.invoke(app, ["memory", "confirm", memory.id])
    reject_result = runner.invoke(app, ["memory", "reject", memory.id])
    edit_result = runner.invoke(
        app,
        ["memory", "edit", memory.id],
        input="Edited summary from CLI\nY\n",
    )

    assert confirm_result.exit_code == 0
    assert "Feedback: 0.30" in confirm_result.stdout
    assert reject_result.exit_code == 0
    assert "Feedback: -0.20" in reject_result.stdout
    assert edit_result.exit_code == 0
    assert "Edited summary from CLI" in edit_result.stdout
    assert "Feedback: 0.00" in edit_result.stdout

    monkeypatch.setattr(
        OnmcService,
        "mine",
        lambda self, **kwargs: {
            "message": None,
            "attempts": [{"id": "attempt-1"}],
            "memories": [{"id": "memory-1"}],
            "artifacts": [{"id": "artifact-1"}],
        },
    )

    mine_result = runner.invoke(app, ["mine"])

    assert mine_result.exit_code == 0
    assert "Review them? [onmc memory list --source transcript]" in mine_result.stdout


def test_memory_list_supports_wide_and_filter_flags(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    confirmed = service.add_memory(
        kind=MemoryKind.INVARIANT,
        title="Confirmed repository boundary",
        summary="All writes must go through the repository boundary.",
        source_type=SourceType.MANUAL_SEED,
        confidence=0.95,
    )
    service.confirm_memory(confirmed.id)
    service.add_memory(
        kind=MemoryKind.GOTCHA,
        title="Low confidence note",
        summary="This should be filtered out.",
        source_type=SourceType.LLM_EXTRACTED,
        confidence=0.2,
    )

    result = runner.invoke(
        app,
        [
            "memory",
            "list",
            "--source",
            "manual_seed",
            "--min-confidence",
            "0.8",
            "--confirmed",
            "--wide",
        ],
    )

    assert result.exit_code == 0
    assert confirmed.id in result.stdout
    assert "Low confidence note" not in result.stdout
