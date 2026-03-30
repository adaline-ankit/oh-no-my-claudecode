from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.models import MemoryArtifactRecord
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.sync.schema import (
    ExportedMemoryRecord,
    ExportedTaskRecord,
    SyncManifest,
    SyncResult,
)


def restore_agent_memory(*, input_dir: Path, storage: SQLiteStorage) -> SyncResult:
    """Restore ONMC memory and task state from a git-portable JSON directory."""
    manifest_path = input_dir / "manifest.json"
    SyncManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))

    memories_restored = 0
    for payload_path in sorted((input_dir / "memories").glob("*/*.json")):
        exported = ExportedMemoryRecord.model_validate(
            json.loads(payload_path.read_text(encoding="utf-8"))
        )
        storage.upsert_memories([exported.memory])
        memories_restored += 1

    tasks_restored = 0
    attempts_restored = 0
    artifacts_restored = 0
    for payload_path in sorted((input_dir / "tasks").glob("*.json")):
        exported_task = ExportedTaskRecord.model_validate(
            json.loads(payload_path.read_text(encoding="utf-8"))
        )
        _restore_task_bundle(storage, exported_task)
        tasks_restored += 1
        attempts_restored += len(exported_task.attempts)
        artifacts_restored += len(exported_task.artifacts)

    latest_brief_path: str | None = (input_dir / "compiled" / "latest-brief.md").as_posix()
    if not (input_dir / "compiled" / "latest-brief.md").exists():
        latest_brief_path = None

    return SyncResult(
        output_dir=input_dir.as_posix(),
        memory_count=memories_restored,
        task_count=tasks_restored,
        attempt_count=attempts_restored,
        artifact_count=artifacts_restored,
        latest_brief_path=latest_brief_path,
    )


def _restore_task_bundle(storage: SQLiteStorage, exported_task: ExportedTaskRecord) -> None:
    task = exported_task.task
    if storage.get_task(task.task_id) is None:
        storage.create_task(task)
    else:
        storage.update_task(task)

    for attempt in exported_task.attempts:
        if storage.get_attempt(attempt.attempt_id) is None:
            storage.create_attempt(attempt)
        else:
            storage.update_attempt(attempt)

    for artifact in exported_task.artifacts:
        _upsert_memory_artifact(storage, artifact)


def _upsert_memory_artifact(storage: SQLiteStorage, artifact: MemoryArtifactRecord) -> None:
    if storage.get_memory_artifact(artifact.memory_id) is None:
        storage.create_memory_artifact(artifact)
    else:
        storage.update_memory_artifact(artifact)
