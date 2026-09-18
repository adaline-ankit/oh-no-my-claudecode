"""Atomic working-state updates in ONMC's existing SQLite metadata table.

This is a namespace over the existing storage backend, not another database.
BEGIN IMMEDIATE prevents concurrent hook processes from losing each other's
updates. Session identifiers become hashed keys, never paths or SQL syntax.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from oh_no_my_claudecode.working_context.models import WorkingSession

PREFIX = "working_context/v1/"
CONFIG_KEY = PREFIX + "config"


def session_key(session_id: str) -> str:
    if not session_id.strip() or len(session_id) > 256:
        raise ValueError("session_id must contain 1–256 characters")
    return PREFIX + "session/" + hashlib.sha256(session_id.encode()).hexdigest()


def anchor_key(memory_id: str) -> str:
    return PREFIX + "anchor/" + hashlib.sha256(memory_id.encode()).hexdigest()


def read(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row[0])


def write(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def load_session(conn: sqlite3.Connection, session_id: str) -> WorkingSession | None:
    raw = read(conn, session_key(session_id))
    return None if raw is None else WorkingSession.model_validate_json(raw)


def save_session(conn: sqlite3.Connection, session: WorkingSession) -> None:
    write(conn, session_key(session.session_id), session.model_dump_json())


@contextmanager
def transaction(db_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(db_path, timeout=2, isolation_level=None)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
