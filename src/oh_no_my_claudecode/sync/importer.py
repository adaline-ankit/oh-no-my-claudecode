from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.hooks.prompt_recall import is_unpromoted_source, unpromoted_source_ref
from oh_no_my_claudecode.models import MemoryArtifactRecord, MemoryEntry
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.sync.schema import (
    ExportedMemoryRecord,
    ExportedSkillRecord,
    ExportedTaskRecord,
    SyncManifest,
    SyncResult,
)


def restore_agent_memory(*, input_dir: Path, storage: SQLiteStorage) -> SyncResult:
    """Restore ONMC memory, task state, and skills from a git-portable JSON directory.

    This is the *same-repo* restore path (``onmc sync --restore``): the export
    being read is this repo's own backup, so its provenance is taken at face
    value and no entry is promoted or demoted by the act of restoring.  What is
    guaranteed is that quarantine is never *lost*: an entry is restored
    quarantined when either the ``unpromoted`` record flag or the reserved
    ``unpromoted:`` ``source_ref`` prefix says so.  Cross-repo imports do not
    come through here — see
    :func:`~oh_no_my_claudecode.federation.pull.pull_memories`, which force-
    quarantines regardless of what the sending repo claimed.
    """
    manifest_path = input_dir / "manifest.json"
    SyncManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))

    memories_restored = 0
    for payload_path in sorted((input_dir / "memories").glob("*/*.json")):
        exported = ExportedMemoryRecord.model_validate(
            json.loads(payload_path.read_text(encoding="utf-8"))
        )
        storage.upsert_memories([_restored_memory(exported)])
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

    skills_restored = 0
    skills_dir = input_dir / "skills"
    if skills_dir.exists():
        for payload_path in sorted(skills_dir.glob("*.json")):
            exported_skill = ExportedSkillRecord.model_validate(
                json.loads(payload_path.read_text(encoding="utf-8"))
            )
            _upsert_skill(storage, exported_skill)
            skills_restored += 1

    latest_brief_path: str | None = (input_dir / "compiled" / "latest-brief.md").as_posix()
    if not (input_dir / "compiled" / "latest-brief.md").exists():
        latest_brief_path = None

    return SyncResult(
        output_dir=input_dir.as_posix(),
        memory_count=memories_restored,
        task_count=tasks_restored,
        attempt_count=attempts_restored,
        artifact_count=artifacts_restored,
        skill_count=skills_restored,
        latest_brief_path=latest_brief_path,
    )


def _restored_memory(exported: ExportedMemoryRecord) -> MemoryEntry:
    """Return the ``MemoryEntry`` to write, with quarantine state preserved.

    Quarantine is carried by two independent signals and the union wins:

    * the ``unpromoted`` record flag, which is explicit and human-editable in
      the open ``.agent-memory/`` format (a reviewer can quarantine an entry by
      flipping it, and that must be honoured), and
    * the reserved ``unpromoted:`` ``source_ref`` prefix, which is what the
      recall path actually gates on.

    An export written before the flag existed simply has no flag, so behaviour
    falls back to the prefix alone — exactly what previous versions did.  This
    function can only ever *add* quarantine; it never clears it, so a
    ``"unpromoted": false`` flag cannot launder a prefixed ``source_ref``.
    """
    memory = exported.memory
    if not exported.unpromoted or is_unpromoted_source(memory.source_ref):
        return memory
    return memory.model_copy(update={"source_ref": unpromoted_source_ref(memory.source_ref)})


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


def _upsert_skill(storage: SQLiteStorage, exported_skill: ExportedSkillRecord) -> None:
    """Idempotent skill restore: add if absent, update if present."""
    skill = exported_skill.skill
    existing = storage.get_skill(skill.id)
    if existing is None:
        storage.add_skill(skill)
    else:
        storage.update_skill(skill)
