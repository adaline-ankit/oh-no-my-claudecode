from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.models import FileStat, MemoryEntry, MemoryKind, RepoFileRecord, SourceType
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

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
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
