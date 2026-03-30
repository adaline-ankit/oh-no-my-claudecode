from __future__ import annotations

import json
import shutil
from importlib.metadata import version
from pathlib import Path

from oh_no_my_claudecode.config import compiled_dir
from oh_no_my_claudecode.models import ProjectConfig
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.sync.schema import (
    ExportCounts,
    ExportedMemoryRecord,
    ExportedTaskRecord,
    SyncManifest,
    SyncResult,
)
from oh_no_my_claudecode.utils.time import utc_now


def export_agent_memory(
    *,
    repo_root: Path,
    config: ProjectConfig,
    storage: SQLiteStorage,
    output_dir: Path,
) -> SyncResult:
    """Export ONMC memory and task state to a git-portable JSON directory."""
    _prepare_output_dir(output_dir)

    memories = sorted(storage.list_memories(), key=lambda item: item.id)
    tasks = sorted(storage.list_tasks(), key=lambda item: item.task_id)
    attempts_total = 0
    artifacts_total = 0

    for memory in memories:
        target = output_dir / "memories" / memory.kind.value / f"{memory.id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        exported = ExportedMemoryRecord(memory=memory)
        target.write_text(
            json.dumps(exported.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    for task in tasks:
        attempts = storage.list_attempts_for_task(task.task_id)
        artifacts = storage.list_memory_artifacts_for_task(task.task_id)
        attempts_total += len(attempts)
        artifacts_total += len(artifacts)
        exported_task = ExportedTaskRecord(task=task, attempts=attempts, artifacts=artifacts)
        target = output_dir / "tasks" / f"{task.task_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(exported_task.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    latest_brief_path = _copy_latest_brief(
        repo_root=repo_root,
        config=config,
        output_dir=output_dir,
    )
    manifest = SyncManifest(
        repo_root=".",
        exported_at=utc_now(),
        onmc_version=version("oh-no-my-claudecode"),
        counts=ExportCounts(
            memories=len(memories),
            tasks=len(tasks),
            attempts=attempts_total,
            artifacts=artifacts_total,
        ),
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return SyncResult(
        output_dir=output_dir.as_posix(),
        memory_count=len(memories),
        task_count=len(tasks),
        attempt_count=attempts_total,
        artifact_count=artifacts_total,
        latest_brief_path=latest_brief_path,
    )


def _prepare_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        for child in ("memories", "tasks", "compiled"):
            shutil.rmtree(output_dir / child, ignore_errors=True)
        manifest = output_dir / "manifest.json"
        if manifest.exists():
            manifest.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)


def _copy_latest_brief(*, repo_root: Path, config: ProjectConfig, output_dir: Path) -> str | None:
    compiled_path = compiled_dir(config, repo_root)
    brief_files = sorted(compiled_path.glob("*-brief.md"), key=lambda path: path.stat().st_mtime)
    if not brief_files:
        return None
    latest = brief_files[-1]
    target = output_dir / "compiled" / "latest-brief.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(latest, target)
    return target.as_posix()
