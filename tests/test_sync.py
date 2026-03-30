from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import AttemptKind, AttemptStatus, MemoryArtifactType, TaskStatus


def test_sync_exporter_produces_valid_json(sample_repo: Path, monkeypatch: object) -> None:
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
        summary="Try a narrower fix.",
        kind=AttemptKind.FIX_ATTEMPT,
        status=AttemptStatus.TRIED,
        reasoning_summary="The cache path has churn.",
        evidence_for="README and git history point at cache.",
        evidence_against=None,
        files_touched=["src/cache.py"],
    )
    service.add_memory_artifact(
        task.task_id,
        artifact_type=MemoryArtifactType.FIX,
        title="Cache boundary fix",
        summary="The fix belongs at the shared boundary.",
        why_it_matters="Future fixes should preserve the boundary.",
        apply_when="The task touches invalidation behavior.",
        avoid_when=None,
        evidence="The worker refresh path uses the shared cache function.",
        related_files=["src/cache.py"],
        related_modules=["cache"],
        confidence=0.8,
    )
    service.end_task(task.task_id, status=TaskStatus.SOLVED, summary="Fixed cache issue.")
    service.compile_brief("fix cache invalidation bug")

    _, result = service.sync_commit()

    manifest = json.loads(
        (sample_repo / ".agent-memory" / "manifest.json").read_text(encoding="utf-8")
    )
    memory_payload = json.loads(
        next((sample_repo / ".agent-memory" / "memories").glob("*/*.json")).read_text(
            encoding="utf-8"
        )
    )
    task_payload = json.loads(
        (sample_repo / ".agent-memory" / "tasks" / f"{task.task_id}.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["counts"]["memories"] == result.memory_count
    assert "memory" in memory_payload
    assert memory_payload["memory"]["id"]
    assert task_payload["task"]["task_id"] == task.task_id
    assert task_payload["attempts"][0]["attempt_id"].startswith("attempt-")
    assert task_payload["artifacts"][0]["memory_id"].startswith("artifact-")
    assert (sample_repo / ".agent-memory" / "compiled" / "latest-brief.md").exists()


def test_sync_round_trip_restore_produces_identical_records(
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
        labels=["bug"],
    )
    attempt = service.add_attempt(
        task.task_id,
        summary="Try a narrower fix.",
        kind=AttemptKind.FIX_ATTEMPT,
        status=AttemptStatus.REJECTED,
        reasoning_summary="The cache path has churn.",
        evidence_for="README points at cache.",
        evidence_against="Worker refresh still fails.",
        files_touched=["src/cache.py"],
    )
    artifact = service.add_memory_artifact(
        task.task_id,
        artifact_type=MemoryArtifactType.DID_NOT_WORK,
        title="Cache-only fix missed worker path",
        summary="A narrow change missed the caller flow.",
        why_it_matters="Future work should inspect caller boundaries first.",
        apply_when=None,
        avoid_when="The task crosses worker refresh logic.",
        evidence="The test still failed after the narrow patch.",
        related_files=["src/cache.py"],
        related_modules=["cache"],
        confidence=0.75,
    )
    service.sync_commit()

    db_path = sample_repo / ".onmc" / "memory.db"
    db_path.unlink()
    service.init_project()
    _, restore_result = service.sync_restore()

    restored_memories = {memory.id for memory in service.list_memories()}
    restored_task = service.get_task(task.task_id)
    restored_attempts = {item.attempt_id for item in service.list_attempts_for_task(task.task_id)}
    restored_artifacts = {
        item.memory_id for item in service.list_memory_artifacts_for_task(task.task_id)
    }

    assert restore_result.memory_count == len(restored_memories)
    assert restored_task is not None
    assert attempt.attempt_id in restored_attempts
    assert artifact.memory_id in restored_artifacts


def test_sync_restore_missing_manifest_exits_with_code_one(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    result = runner.invoke(app, ["sync", "--restore"])

    assert result.exit_code == 1
    assert "Missing sync manifest" in result.stdout


def test_manifest_counts_match_exported_files(sample_repo: Path, monkeypatch: object) -> None:
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
        summary="Try a narrower fix.",
        kind=AttemptKind.FIX_ATTEMPT,
        status=AttemptStatus.TRIED,
        reasoning_summary=None,
        evidence_for=None,
        evidence_against=None,
        files_touched=["src/cache.py"],
    )
    service.add_memory_artifact(
        task.task_id,
        artifact_type=MemoryArtifactType.FIX,
        title="Boundary fix",
        summary="Fix at shared boundary.",
        why_it_matters="Preserves the invariant.",
        apply_when=None,
        avoid_when=None,
        evidence="Used by refresh path.",
        related_files=["src/cache.py"],
        related_modules=["cache"],
        confidence=0.8,
    )

    service.sync_commit()

    manifest = json.loads(
        (sample_repo / ".agent-memory" / "manifest.json").read_text(encoding="utf-8")
    )
    memory_files = list((sample_repo / ".agent-memory" / "memories").glob("*/*.json"))
    task_files = list((sample_repo / ".agent-memory" / "tasks").glob("*.json"))
    task_payload = json.loads(task_files[0].read_text(encoding="utf-8"))

    assert manifest["counts"]["memories"] == len(memory_files)
    assert manifest["counts"]["tasks"] == len(task_files)
    assert manifest["counts"]["attempts"] == len(task_payload["attempts"])
    assert manifest["counts"]["artifacts"] == len(task_payload["artifacts"])
