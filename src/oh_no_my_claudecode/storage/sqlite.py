from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.models import (
    AttemptKind,
    AttemptRecord,
    AttemptStatus,
    FileStat,
    MemoryArtifactRecord,
    MemoryArtifactType,
    MemoryEntry,
    MemoryKind,
    RepoFileRecord,
    SourceType,
    TaskRecord,
    TaskStatus,
)
from oh_no_my_claudecode.utils.time import isoformat_utc, parse_datetime


class SQLiteStorage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
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
                CREATE TABLE IF NOT EXISTS repo_files (
                    path TEXT PRIMARY KEY,
                    extension TEXT,
                    is_test INTEGER NOT NULL,
                    size_bytes INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS file_stats (
                    path TEXT PRIMARY KEY,
                    change_count INTEGER NOT NULL,
                    recent_change_count INTEGER NOT NULL,
                    last_modified_at TEXT,
                    is_test INTEGER NOT NULL,
                    top_level_dir TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    repo_root TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    labels_json TEXT NOT NULL,
                    final_summary TEXT,
                    final_outcome TEXT,
                    confidence REAL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reasoning_summary TEXT,
                    evidence_for TEXT,
                    evidence_against TEXT,
                    files_touched_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    closed_at TEXT,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS memory_artifacts (
                    memory_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    why_it_matters TEXT NOT NULL,
                    apply_when TEXT,
                    avoid_when TEXT,
                    evidence TEXT NOT NULL,
                    related_files_json TEXT NOT NULL,
                    related_modules_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_memory_artifacts_task_id
                    ON memory_artifacts(task_id);
                CREATE INDEX IF NOT EXISTS idx_memory_artifacts_type
                    ON memory_artifacts(type);
                """
            )

    def upsert_memories(self, entries: list[MemoryEntry]) -> tuple[int, int]:
        new_count = 0
        updated_count = 0
        with self._connect() as conn:
            for entry in entries:
                exists = conn.execute(
                    "SELECT 1 FROM memories WHERE id = ?",
                    (entry.id,),
                ).fetchone()
                if exists:
                    updated_count += 1
                else:
                    new_count += 1
                conn.execute(
                    """
                    INSERT INTO memories (
                        id, kind, title, summary, details, source_type, source_ref,
                        tags_json, confidence, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        kind=excluded.kind,
                        title=excluded.title,
                        summary=excluded.summary,
                        details=excluded.details,
                        source_type=excluded.source_type,
                        source_ref=excluded.source_ref,
                        tags_json=excluded.tags_json,
                        confidence=excluded.confidence,
                        updated_at=excluded.updated_at
                    """,
                    (
                        entry.id,
                        entry.kind.value,
                        entry.title,
                        entry.summary,
                        entry.details,
                        entry.source_type.value,
                        entry.source_ref,
                        json.dumps(entry.tags),
                        entry.confidence,
                        isoformat_utc(entry.created_at),
                        isoformat_utc(entry.updated_at),
                    ),
                )
        return new_count, updated_count

    def replace_generated_memories(self, entries: list[MemoryEntry]) -> tuple[int, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM memories WHERE source_type != ?",
                (SourceType.MANUAL.value,),
            ).fetchall()
            existing_ids = {str(row["id"]) for row in rows}
            next_ids = {entry.id for entry in entries}
            new_count = len(next_ids - existing_ids)
            updated_count = len(next_ids & existing_ids)

            conn.execute(
                "DELETE FROM memories WHERE source_type != ?",
                (SourceType.MANUAL.value,),
            )
            conn.executemany(
                """
                INSERT INTO memories (
                    id, kind, title, summary, details, source_type, source_ref,
                    tags_json, confidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        entry.id,
                        entry.kind.value,
                        entry.title,
                        entry.summary,
                        entry.details,
                        entry.source_type.value,
                        entry.source_ref,
                        json.dumps(entry.tags),
                        entry.confidence,
                        isoformat_utc(entry.created_at),
                        isoformat_utc(entry.updated_at),
                    )
                    for entry in entries
                ],
            )
        return new_count, updated_count

    def list_memories(self, *, kind: MemoryKind | None = None) -> list[MemoryEntry]:
        query = "SELECT * FROM memories"
        params: tuple[Any, ...] = ()
        if kind is not None:
            query += " WHERE kind = ?"
            params = (kind.value,)
        query += " ORDER BY updated_at DESC, title ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def get_memory(self, memory_id: str) -> MemoryEntry | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return None if row is None else self._row_to_memory(row)

    def replace_repo_files(self, records: list[RepoFileRecord]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM repo_files")
            conn.executemany(
                """
                INSERT INTO repo_files (path, extension, is_test, size_bytes)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        record.path,
                        record.extension,
                        int(record.is_test),
                        record.size_bytes,
                    )
                    for record in records
                ],
            )

    def list_repo_files(self) -> list[RepoFileRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM repo_files ORDER BY path ASC").fetchall()
        return [
            RepoFileRecord(
                path=row["path"],
                extension=row["extension"],
                is_test=bool(row["is_test"]),
                size_bytes=int(row["size_bytes"]),
            )
            for row in rows
        ]

    def replace_file_stats(self, stats: list[FileStat]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM file_stats")
            conn.executemany(
                """
                INSERT INTO file_stats (
                    path,
                    change_count,
                    recent_change_count,
                    last_modified_at,
                    is_test,
                    top_level_dir
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        stat.path,
                        stat.change_count,
                        stat.recent_change_count,
                        isoformat_utc(stat.last_modified_at) if stat.last_modified_at else None,
                        int(stat.is_test),
                        stat.top_level_dir,
                    )
                    for stat in stats
                ],
            )

    def list_file_stats(self) -> list[FileStat]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM file_stats "
                "ORDER BY change_count DESC, recent_change_count DESC, path ASC"
            ).fetchall()
        return [
            FileStat(
                path=row["path"],
                change_count=int(row["change_count"]),
                recent_change_count=int(row["recent_change_count"]),
                last_modified_at=parse_datetime(row["last_modified_at"]),
                is_test=bool(row["is_test"]),
                top_level_dir=row["top_level_dir"],
            )
            for row in rows
        ]

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO meta (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def get_meta(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def all_meta(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM meta ORDER BY key ASC").fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def memory_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM memories").fetchone()
        return int(row["count"])

    def create_task(self, task: TaskRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id,
                    title,
                    description,
                    status,
                    created_at,
                    started_at,
                    ended_at,
                    repo_root,
                    branch,
                    labels_json,
                    final_summary,
                    final_outcome,
                    confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._task_values(task),
            )

    def update_task(self, task: TaskRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks SET
                    title = ?,
                    description = ?,
                    status = ?,
                    created_at = ?,
                    started_at = ?,
                    ended_at = ?,
                    repo_root = ?,
                    branch = ?,
                    labels_json = ?,
                    final_summary = ?,
                    final_outcome = ?,
                    confidence = ?
                WHERE task_id = ?
                """,
                (
                    task.title,
                    task.description,
                    task.status.value,
                    isoformat_utc(task.created_at),
                    isoformat_utc(task.started_at) if task.started_at else None,
                    isoformat_utc(task.ended_at) if task.ended_at else None,
                    task.repo_root,
                    task.branch,
                    json.dumps(task.labels),
                    task.final_summary,
                    task.final_outcome,
                    task.confidence,
                    task.task_id,
                ),
            )

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return None if row is None else self._row_to_task(row)

    def list_tasks(self) -> list[TaskRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                ORDER BY
                    CASE status
                        WHEN 'active' THEN 0
                        WHEN 'blocked' THEN 1
                        WHEN 'open' THEN 2
                        WHEN 'solved' THEN 3
                        ELSE 4
                    END,
                    rowid DESC
                """
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def task_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM tasks").fetchone()
        return int(row["count"])

    def create_attempt(self, attempt: AttemptRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO attempts (
                    attempt_id,
                    task_id,
                    summary,
                    kind,
                    status,
                    reasoning_summary,
                    evidence_for,
                    evidence_against,
                    files_touched_json,
                    created_at,
                    closed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._attempt_values(attempt),
            )

    def update_attempt(self, attempt: AttemptRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE attempts SET
                    task_id = ?,
                    summary = ?,
                    kind = ?,
                    status = ?,
                    reasoning_summary = ?,
                    evidence_for = ?,
                    evidence_against = ?,
                    files_touched_json = ?,
                    created_at = ?,
                    closed_at = ?
                WHERE attempt_id = ?
                """,
                (
                    attempt.task_id,
                    attempt.summary,
                    attempt.kind.value,
                    attempt.status.value,
                    attempt.reasoning_summary,
                    attempt.evidence_for,
                    attempt.evidence_against,
                    json.dumps(attempt.files_touched),
                    isoformat_utc(attempt.created_at),
                    isoformat_utc(attempt.closed_at) if attempt.closed_at else None,
                    attempt.attempt_id,
                ),
            )

    def get_attempt(self, attempt_id: str) -> AttemptRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        return None if row is None else self._row_to_attempt(row)

    def list_attempts_for_task(self, task_id: str) -> list[AttemptRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM attempts
                WHERE task_id = ?
                ORDER BY created_at DESC, rowid DESC
                """,
                (task_id,),
            ).fetchall()
        return [self._row_to_attempt(row) for row in rows]

    def list_attempt_counts_by_task(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, COUNT(*) AS count
                FROM attempts
                GROUP BY task_id
                """
            ).fetchall()
        return {str(row["task_id"]): int(row["count"]) for row in rows}

    def attempt_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM attempts").fetchone()
        return int(row["count"])

    def create_memory_artifact(self, artifact: MemoryArtifactRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_artifacts (
                    memory_id,
                    task_id,
                    type,
                    title,
                    summary,
                    why_it_matters,
                    apply_when,
                    avoid_when,
                    evidence,
                    related_files_json,
                    related_modules_json,
                    confidence,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._memory_artifact_values(artifact),
            )

    def get_memory_artifact(self, memory_id: str) -> MemoryArtifactRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_artifacts WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        return None if row is None else self._row_to_memory_artifact(row)

    def list_memory_artifacts(
        self,
        *,
        artifact_type: MemoryArtifactType | None = None,
    ) -> list[MemoryArtifactRecord]:
        query = "SELECT * FROM memory_artifacts"
        params: tuple[Any, ...] = ()
        if artifact_type is not None:
            query += " WHERE type = ?"
            params = (artifact_type.value,)
        query += " ORDER BY created_at DESC, rowid DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_memory_artifact(row) for row in rows]

    def list_memory_artifacts_for_task(self, task_id: str) -> list[MemoryArtifactRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_artifacts
                WHERE task_id = ?
                ORDER BY created_at DESC, rowid DESC
                """,
                (task_id,),
            ).fetchall()
        return [self._row_to_memory_artifact(row) for row in rows]

    def list_memory_artifact_counts_by_task(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, COUNT(*) AS count
                FROM memory_artifacts
                GROUP BY task_id
                """
            ).fetchall()
        return {str(row["task_id"]): int(row["count"]) for row in rows}

    def memory_artifact_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM memory_artifacts").fetchone()
        return int(row["count"])

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> MemoryEntry:
        created_at = parse_datetime(row["created_at"])
        updated_at = parse_datetime(row["updated_at"])
        if created_at is None or updated_at is None:
            msg = "Memory row is missing timestamps."
            raise ValueError(msg)
        return MemoryEntry(
            id=row["id"],
            kind=MemoryKind(row["kind"]),
            title=row["title"],
            summary=row["summary"],
            details=row["details"],
            source_type=SourceType(row["source_type"]),
            source_ref=row["source_ref"],
            tags=json.loads(row["tags_json"]),
            confidence=float(row["confidence"]),
            created_at=created_at,
            updated_at=updated_at,
        )

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> TaskRecord:
        created_at = parse_datetime(row["created_at"])
        if created_at is None:
            msg = "Task row is missing created_at."
            raise ValueError(msg)
        return TaskRecord(
            task_id=row["task_id"],
            title=row["title"],
            description=row["description"],
            status=TaskStatus(row["status"]),
            created_at=created_at,
            started_at=parse_datetime(row["started_at"]),
            ended_at=parse_datetime(row["ended_at"]),
            repo_root=row["repo_root"],
            branch=row["branch"],
            labels=json.loads(row["labels_json"]),
            final_summary=row["final_summary"],
            final_outcome=row["final_outcome"],
            confidence=float(row["confidence"]) if row["confidence"] is not None else None,
        )

    @staticmethod
    def _task_values(task: TaskRecord) -> tuple[Any, ...]:
        return (
            task.task_id,
            task.title,
            task.description,
            task.status.value,
            isoformat_utc(task.created_at),
            isoformat_utc(task.started_at) if task.started_at else None,
            isoformat_utc(task.ended_at) if task.ended_at else None,
            task.repo_root,
            task.branch,
            json.dumps(task.labels),
            task.final_summary,
            task.final_outcome,
            task.confidence,
        )

    @staticmethod
    def _row_to_attempt(row: sqlite3.Row) -> AttemptRecord:
        created_at = parse_datetime(row["created_at"])
        if created_at is None:
            msg = "Attempt row is missing created_at."
            raise ValueError(msg)
        return AttemptRecord(
            attempt_id=row["attempt_id"],
            task_id=row["task_id"],
            summary=row["summary"],
            kind=AttemptKind(row["kind"]),
            status=AttemptStatus(row["status"]),
            reasoning_summary=row["reasoning_summary"],
            evidence_for=row["evidence_for"],
            evidence_against=row["evidence_against"],
            files_touched=json.loads(row["files_touched_json"]),
            created_at=created_at,
            closed_at=parse_datetime(row["closed_at"]),
        )

    @staticmethod
    def _attempt_values(attempt: AttemptRecord) -> tuple[Any, ...]:
        return (
            attempt.attempt_id,
            attempt.task_id,
            attempt.summary,
            attempt.kind.value,
            attempt.status.value,
            attempt.reasoning_summary,
            attempt.evidence_for,
            attempt.evidence_against,
            json.dumps(attempt.files_touched),
            isoformat_utc(attempt.created_at),
            isoformat_utc(attempt.closed_at) if attempt.closed_at else None,
        )

    @staticmethod
    def _row_to_memory_artifact(row: sqlite3.Row) -> MemoryArtifactRecord:
        created_at = parse_datetime(row["created_at"])
        if created_at is None:
            msg = "Memory artifact row is missing created_at."
            raise ValueError(msg)
        return MemoryArtifactRecord(
            memory_id=row["memory_id"],
            task_id=row["task_id"],
            type=MemoryArtifactType(row["type"]),
            title=row["title"],
            summary=row["summary"],
            why_it_matters=row["why_it_matters"],
            apply_when=row["apply_when"],
            avoid_when=row["avoid_when"],
            evidence=row["evidence"],
            related_files=json.loads(row["related_files_json"]),
            related_modules=json.loads(row["related_modules_json"]),
            confidence=float(row["confidence"]),
            created_at=created_at,
        )

    @staticmethod
    def _memory_artifact_values(artifact: MemoryArtifactRecord) -> tuple[Any, ...]:
        return (
            artifact.memory_id,
            artifact.task_id,
            artifact.type.value,
            artifact.title,
            artifact.summary,
            artifact.why_it_matters,
            artifact.apply_when,
            artifact.avoid_when,
            artifact.evidence,
            json.dumps(artifact.related_files),
            json.dumps(artifact.related_modules),
            artifact.confidence,
            isoformat_utc(artifact.created_at),
        )
