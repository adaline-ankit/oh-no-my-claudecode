"""SQLite-backed persistence for the code index.

Stores :class:`~oh_no_my_claudecode.codeindex.models.IndexChunk` rows in
``ci_chunks`` and :class:`~oh_no_my_claudecode.codeindex.models.IndexEdge`
rows in ``ci_edges``, both inside the repo's ``.onmc/`` directory (same
storage root as the main onmc SQLite database).

Schema version is tracked in ``ci_meta`` so future migrations can be applied
deterministically on open.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.codeindex.models import IndexChunk, IndexEdge, IndexStats

_SCHEMA_VERSION = 1
_DB_NAME = "codeindex.db"

_DDL = """\
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ci_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ci_chunks (
    chunk_id   TEXT PRIMARY KEY,
    blob_sha   TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    path       TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line   INTEGER NOT NULL,
    language   TEXT NOT NULL,
    is_test    INTEGER NOT NULL DEFAULT 0,
    is_stale   INTEGER NOT NULL DEFAULT 0,
    trust_level TEXT NOT NULL DEFAULT 'default',
    indexed_at TEXT NOT NULL,
    content    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ci_chunks_path      ON ci_chunks(path);
CREATE INDEX IF NOT EXISTS ci_chunks_symbol    ON ci_chunks(symbol);
CREATE INDEX IF NOT EXISTS ci_chunks_blob_sha  ON ci_chunks(blob_sha);
CREATE INDEX IF NOT EXISTS ci_chunks_path_sym  ON ci_chunks(path, symbol);

-- Edges stored by path+symbol (not chunk_id) for stability across
-- content changes.  Each file owns its own outgoing edges.
CREATE TABLE IF NOT EXISTS ci_edges (
    src_path   TEXT NOT NULL,
    src_symbol TEXT NOT NULL,
    dst_path   TEXT NOT NULL,
    dst_symbol TEXT NOT NULL,
    edge_type  TEXT NOT NULL,
    PRIMARY KEY (src_path, src_symbol, dst_path, dst_symbol, edge_type)
);

CREATE INDEX IF NOT EXISTS ci_edges_src ON ci_edges(src_path, src_symbol);
CREATE INDEX IF NOT EXISTS ci_edges_dst ON ci_edges(dst_path, dst_symbol);
"""


class CodeIndexStore:
    """Low-level read/write access to the SQLite code index.

    Parameters
    ----------
    db_path:
        Path to the SQLite file.  Created (with parent dirs) if absent.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        with conn:
            conn.executescript(_DDL)
            # Ensure schema version is recorded
            conn.execute(
                "INSERT OR IGNORE INTO ci_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(_SCHEMA_VERSION)),
            )
        conn.close()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Meta helpers
    # ------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT value FROM ci_meta WHERE key = ?", (key,)).fetchone()
            return str(row["value"]) if row else None
        finally:
            conn.close()

    def set_meta(self, key: str, value: str) -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ci_meta(key, value) VALUES (?, ?)", (key, value)
            )

    # ------------------------------------------------------------------
    # Blob SHA lookups (skip-unchanged detection)
    # ------------------------------------------------------------------

    def get_indexed_blob_shas(self) -> dict[str, str]:
        """Return mapping of path → blob_sha for all non-stale chunks."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT path, blob_sha FROM ci_chunks WHERE is_stale = 0"
            ).fetchall()
            # If a path has multiple blob_shas (shouldn't happen in practice),
            # keep the most recent by taking the last value.
            result: dict[str, str] = {}
            for row in rows:
                result[str(row["path"])] = str(row["blob_sha"])
            return result
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Chunk operations
    # ------------------------------------------------------------------

    def upsert_chunks(self, chunks: list[IndexChunk]) -> None:
        """Insert or replace a batch of chunks atomically."""
        if not chunks:
            return
        with self._transaction() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO ci_chunks
                   (chunk_id, blob_sha, commit_sha, path, symbol, kind,
                    start_line, end_line, language, is_test, is_stale,
                    trust_level, indexed_at, content)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        c.chunk_id,
                        c.blob_sha,
                        c.commit_sha,
                        c.path,
                        c.symbol,
                        c.kind,
                        c.start_line,
                        c.end_line,
                        c.language,
                        int(c.is_test),
                        int(c.is_stale),
                        c.trust_level,
                        c.indexed_at,
                        c.content,
                    )
                    for c in chunks
                ],
            )

    def delete_chunks_for_path(self, path: str) -> list[str]:
        """Delete all chunks for *path*.  Returns the deleted chunk_ids."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT chunk_id FROM ci_chunks WHERE path = ?", (path,)
            ).fetchall()
            chunk_ids = [str(r["chunk_id"]) for r in rows]
            if chunk_ids:
                with conn:
                    conn.execute("DELETE FROM ci_chunks WHERE path = ?", (path,))
            return chunk_ids
        finally:
            conn.close()

    def get_chunk(self, chunk_id: str) -> IndexChunk | None:
        """Return a single chunk by ID, or None if not found."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM ci_chunks WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
            return _row_to_chunk(row) if row else None
        finally:
            conn.close()

    def get_chunks_for_path(self, path: str) -> list[IndexChunk]:
        """Return all chunks for a given file path."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM ci_chunks WHERE path = ? ORDER BY start_line",
                (path,),
            ).fetchall()
            return [_row_to_chunk(r) for r in rows]
        finally:
            conn.close()

    def get_chunks_for_symbol(self, symbol: str) -> list[IndexChunk]:
        """Return all chunks with the given symbol name."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM ci_chunks WHERE symbol = ? ORDER BY path, start_line",
                (symbol,),
            ).fetchall()
            return [_row_to_chunk(r) for r in rows]
        finally:
            conn.close()

    def search_chunks_by_symbol_substr(self, substr: str) -> list[IndexChunk]:
        """Return chunks whose symbol name contains *substr* (case-insensitive)."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM ci_chunks WHERE symbol LIKE ? ORDER BY path, start_line",
                (f"%{substr}%",),
            ).fetchall()
            return [_row_to_chunk(r) for r in rows]
        finally:
            conn.close()

    def mark_stale(self, paths: list[str]) -> None:
        """Mark chunks for *paths* as stale (blob no longer in HEAD)."""
        if not paths:
            return
        with self._transaction() as conn:
            conn.executemany(
                "UPDATE ci_chunks SET is_stale = 1 WHERE path = ?",
                [(p,) for p in paths],
            )

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def upsert_edges(self, edges: list[IndexEdge]) -> None:
        """Insert or replace a batch of edges atomically."""
        if not edges:
            return
        with self._transaction() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO ci_edges
                   (src_path, src_symbol, dst_path, dst_symbol, edge_type)
                   VALUES (?,?,?,?,?)""",
                [
                    (e.src_path, e.src_symbol, e.dst_path, e.dst_symbol, e.edge_type)
                    for e in edges
                ],
            )

    def delete_edges_for_path(self, path: str) -> None:
        """Delete all outgoing edges owned by *path*."""
        with self._transaction() as conn:
            conn.execute("DELETE FROM ci_edges WHERE src_path = ?", (path,))

    def get_outgoing_edges(self, path: str, symbol: str) -> list[IndexEdge]:
        """Return edges where (src_path, src_symbol) == (path, symbol)."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM ci_edges WHERE src_path = ? AND src_symbol = ?",
                (path, symbol),
            ).fetchall()
            return [_row_to_edge(r) for r in rows]
        finally:
            conn.close()

    def get_incoming_edges(self, path: str, symbol: str) -> list[IndexEdge]:
        """Return edges where (dst_path, dst_symbol) == (path, symbol)."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM ci_edges WHERE dst_path = ? AND dst_symbol = ?",
                (path, symbol),
            ).fetchall()
            return [_row_to_edge(r) for r in rows]
        finally:
            conn.close()

    def get_callers(self, path: str, symbol: str) -> list[IndexEdge]:
        """Return callee edges pointing TO (path, symbol)."""
        _sql = (
            "SELECT * FROM ci_edges"
            " WHERE dst_path = ? AND dst_symbol = ? AND edge_type = 'callee'"
        )
        conn = self._connect()
        try:
            rows = conn.execute(_sql, (path, symbol)).fetchall()
            return [_row_to_edge(r) for r in rows]
        finally:
            conn.close()

    def get_callees(self, path: str, symbol: str) -> list[IndexEdge]:
        """Return callee edges going FROM (path, symbol)."""
        _sql = (
            "SELECT * FROM ci_edges"
            " WHERE src_path = ? AND src_symbol = ? AND edge_type = 'callee'"
        )
        conn = self._connect()
        try:
            rows = conn.execute(_sql, (path, symbol)).fetchall()
            return [_row_to_edge(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> IndexStats:
        """Compute and return current index statistics."""
        conn = self._connect()
        try:
            total_chunks = int(
                conn.execute("SELECT COUNT(*) FROM ci_chunks").fetchone()[0]
            )
            total_edges = int(
                conn.execute("SELECT COUNT(*) FROM ci_edges").fetchone()[0]
            )
            total_files = int(
                conn.execute("SELECT COUNT(DISTINCT path) FROM ci_chunks").fetchone()[0]
            )
            stale_chunks = int(
                conn.execute("SELECT COUNT(*) FROM ci_chunks WHERE is_stale = 1").fetchone()[0]
            )
            lang_rows = conn.execute(
                "SELECT language, COUNT(*) as cnt FROM ci_chunks GROUP BY language"
            ).fetchall()
            languages: dict[str, int] = {
                str(r["language"]): int(r["cnt"]) for r in lang_rows
            }
            commit_sha = self.get_meta("commit_sha") or ""
            built_at = self.get_meta("built_at") or ""
            excluded_files = int(self.get_meta("excluded_files") or "0")

            return IndexStats(
                total_chunks=total_chunks,
                total_edges=total_edges,
                total_files=total_files,
                stale_chunks=stale_chunks,
                excluded_files=excluded_files,
                languages=languages,
                commit_sha=commit_sha,
                built_at=built_at,
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Dump helpers (for idempotency checks)
    # ------------------------------------------------------------------

    def dump_canonical(self) -> dict[str, Any]:
        """Return a canonical, sorted representation of the full index.

        Used by tests to assert that two index states are identical.
        """
        conn = self._connect()
        try:
            chunk_rows = conn.execute(
                "SELECT chunk_id, blob_sha, path, symbol, kind, start_line, end_line, "
                "language, is_test, is_stale, trust_level "
                "FROM ci_chunks ORDER BY chunk_id"
            ).fetchall()
            edge_rows = conn.execute(
                "SELECT src_path, src_symbol, dst_path, dst_symbol, edge_type "
                "FROM ci_edges ORDER BY src_path, src_symbol, dst_path, dst_symbol, edge_type"
            ).fetchall()
            return {
                "chunks": [dict(r) for r in chunk_rows],
                "edges": [dict(r) for r in edge_rows],
            }
        finally:
            conn.close()

    def path_exists(self) -> bool:
        """Return True if the DB file exists on disk."""
        return self._db_path.exists()


# ---------------------------------------------------------------------------
# Row conversion helpers
# ---------------------------------------------------------------------------

def _row_to_chunk(row: sqlite3.Row) -> IndexChunk:
    return IndexChunk(
        chunk_id=str(row["chunk_id"]),
        blob_sha=str(row["blob_sha"]),
        commit_sha=str(row["commit_sha"]),
        path=str(row["path"]),
        symbol=str(row["symbol"]),
        kind=str(row["kind"]),  # type: ignore[arg-type]
        start_line=int(row["start_line"]),
        end_line=int(row["end_line"]),
        language=str(row["language"]),  # type: ignore[arg-type]
        is_test=bool(row["is_test"]),
        is_stale=bool(row["is_stale"]),
        trust_level=str(row["trust_level"]),
        indexed_at=str(row["indexed_at"]),
        content=str(row["content"]),
    )


def _row_to_edge(row: sqlite3.Row) -> IndexEdge:
    return IndexEdge(
        src_path=str(row["src_path"]),
        src_symbol=str(row["src_symbol"]),
        dst_path=str(row["dst_path"]),
        dst_symbol=str(row["dst_symbol"]),
        edge_type=str(row["edge_type"]),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Store factory
# ---------------------------------------------------------------------------

def open_store(repo_root: Path) -> CodeIndexStore:
    """Return a :class:`CodeIndexStore` for *repo_root*.

    The DB file lives at ``<repo_root>/.onmc/codeindex.db``.
    """
    db_path = repo_root / ".onmc" / _DB_NAME
    return CodeIndexStore(db_path)


def dump_store_as_json(store: CodeIndexStore) -> str:
    """Return the index state as a deterministic JSON string (for tests)."""
    return json.dumps(store.dump_canonical(), sort_keys=True)
