"""Optional ``sqlite-vec`` semantic vector backend.

This module adds a *real* approximate/exact nearest-neighbour search backend on
top of the existing embedding infrastructure, mirroring the optional-backend
pattern already used for ``sentence-transformers`` in :mod:`.core`.

Why
---
onmc's default :class:`~oh_no_my_claudecode.embeddings.core.HashNgramEmbedder`
is a zero-dependency hashed-n-gram embedder — cheap and deterministic, but a
weak semantic signal.  When the *optional* ``sqlite-vec`` package is installed,
this module exposes a ``vec0`` virtual-table KNN index so a query vector can be
matched against every stored memory vector in a single indexed SQL query,
instead of the O(n) Python cosine loop in :mod:`.rerank`.

Zero-regression contract
-------------------------
- ``sqlite-vec`` is an **optional** extra (``pip install oh-no-my-claudecode[sqlitevec]``).
- The import is guarded (:func:`sqlitevec_available`).  When it is missing —
  or extension loading is unsupported by the host Python — every entry point
  degrades gracefully and the caller falls back to the existing
  hash-embedder + Python-cosine rerank path.  Nothing in the default install
  path changes.
- The backend **reuses** the ``memory_vectors`` table (migration v6) as the
  source of truth for cached vectors; the ``vec0`` virtual table is a derived
  index that is (re)built from it.  It is created lazily and never as part of
  the core migration chain, so a fresh zero-dep database is byte-for-byte
  unchanged.

Selection
---------
The backend is used only when **both** hold:

1. ``sqlite-vec`` is importable (:func:`sqlitevec_available`), and
2. it is *configured* — ``ONMC_VEC_BACKEND=sqlite-vec`` (case-insensitive) or
   the caller passes ``prefer=True`` explicitly.

See :func:`sqlitevec_selected`.
"""

from __future__ import annotations

import os
import sqlite3
import struct
from contextlib import closing
from typing import TYPE_CHECKING

from oh_no_my_claudecode.embeddings.core import (
    EmbeddingVector,
    embeddings_enabled,
    get_embedder,
)

if TYPE_CHECKING:
    from oh_no_my_claudecode.embeddings.core import Embedder
    from oh_no_my_claudecode.models import MemoryEntry
    from oh_no_my_claudecode.storage.sqlite import SQLiteStorage


# ---------------------------------------------------------------------------
# Availability / selection
# ---------------------------------------------------------------------------


def sqlitevec_available() -> bool:
    """Return True when the optional ``sqlite-vec`` package can be loaded.

    Checks both that the Python package is importable *and* that the host
    ``sqlite3`` build permits loading extensions (some system Pythons compile
    it out).  Any failure returns False so callers fall back cleanly.
    """
    try:
        import sqlite_vec  # noqa: F401, PLC0415
    except ImportError:
        return False

    # Extension loading must be supported by this sqlite3 build.
    try:
        with closing(sqlite3.connect(":memory:")) as conn:
            return hasattr(conn, "enable_load_extension")
    except Exception:  # noqa: BLE001
        return False


def sqlitevec_selected(*, prefer: bool | None = None) -> bool:
    """Return True when the sqlite-vec backend should be used.

    Requires both availability and configuration:
    - *prefer* True  → forces on (still requires availability).
    - *prefer* False → forces off.
    - *prefer* None  → read ``ONMC_VEC_BACKEND``; on when it equals
      ``sqlite-vec`` / ``sqlitevec`` / ``vec`` (case-insensitive).
    """
    if not embeddings_enabled():
        return False
    if not sqlitevec_available():
        return False
    if prefer is not None:
        return prefer
    raw = os.environ.get("ONMC_VEC_BACKEND", "").strip().lower()
    return raw in {"sqlite-vec", "sqlitevec", "vec"}


# ---------------------------------------------------------------------------
# Vector (de)serialisation — sqlite-vec expects raw little-endian float32 blobs
# ---------------------------------------------------------------------------


def _serialize_f32(vector: EmbeddingVector) -> bytes:
    """Pack a float vector into a compact little-endian float32 blob."""
    return struct.pack(f"<{len(vector)}f", *vector)


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class SqliteVecStore:
    """A ``vec0`` KNN index derived from the ``memory_vectors`` cache.

    The index is keyed by an integer rowid; a side table maps rowid ⇆ the
    ``memory_id`` text primary key so results can be joined back to memories.

    Instances are cheap; each method opens its own short-lived connection with
    the extension loaded, matching :class:`SQLiteStorage`'s connection style.
    """

    _VEC_TABLE = "memory_vectors_vec"
    _MAP_TABLE = "memory_vectors_vec_map"

    def __init__(self, storage: SQLiteStorage, *, dim: int) -> None:
        self._storage = storage
        self._dim = dim

    # -- connection ---------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a connection with the sqlite-vec extension loaded.

        Raises on failure; callers guard with :func:`sqlitevec_available`.
        """
        import sqlite_vec  # noqa: PLC0415

        conn = sqlite3.connect(self._storage.db_path)
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
        finally:
            conn.enable_load_extension(False)
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        # Table names / dim are hardcoded class constants, never user input.
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {self._VEC_TABLE} "
            f"USING vec0(embedding float[{self._dim}])"
        )
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self._MAP_TABLE} ("
            "  rowid INTEGER PRIMARY KEY,"
            "  memory_id TEXT NOT NULL UNIQUE"
            ")"
        )

    # -- build --------------------------------------------------------------

    def rebuild(self, *, embedder: Embedder | None = None) -> int:
        """(Re)build the KNN index from cached vectors in ``memory_vectors``.

        Only rows whose ``embedder_id`` matches the active embedder and whose
        ``dim`` matches this index are indexed — a mixed-embedder cache stays
        consistent.  Returns the number of vectors indexed.

        This reuses the existing vector cache as the source of truth: callers
        should populate it first via
        :func:`~oh_no_my_claudecode.embeddings.rerank.build_vectors_for_all_memories`.
        """
        if embedder is None:
            embedder = get_embedder()
        embedder_id = embedder.embedder_id

        # Pull cached vectors from the memory_vectors table (public accessor).
        pairs = self._storage.iter_cached_vectors(embedder_id=embedder_id, dim=self._dim)

        indexed = 0
        # Table names below are hardcoded class constants, never user input —
        # the S608 interpolation warnings are false positives.
        with closing(self._connect()) as conn, conn:
            self._ensure_schema(conn)
            # Rebuild from scratch for a deterministic, consistent index.
            conn.execute(f"DELETE FROM {self._VEC_TABLE}")  # noqa: S608
            conn.execute(f"DELETE FROM {self._MAP_TABLE}")  # noqa: S608
            for rowid, (memory_id, vector) in enumerate(pairs, start=1):
                if len(vector) != self._dim:
                    continue
                conn.execute(
                    f"INSERT INTO {self._MAP_TABLE} (rowid, memory_id) VALUES (?, ?)",  # noqa: S608
                    (rowid, memory_id),
                )
                conn.execute(
                    f"INSERT INTO {self._VEC_TABLE} (rowid, embedding) VALUES (?, ?)",  # noqa: S608
                    (rowid, _serialize_f32(vector)),
                )
                indexed += 1
        return indexed

    # -- query --------------------------------------------------------------

    def knn(self, query_vector: EmbeddingVector, *, k: int) -> list[tuple[str, float]]:
        """Return the ``k`` nearest ``(memory_id, distance)`` pairs.

        ``distance`` is sqlite-vec's L2 distance (smaller is nearer).  For the
        unit-norm vectors this project produces, L2 ordering is equivalent to
        cosine ordering.  Returns an empty list when the index is empty or the
        query dimensionality does not match.
        """
        if k <= 0 or len(query_vector) != self._dim:
            return []
        with closing(self._connect()) as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                f"""
                SELECT m.memory_id AS memory_id, v.distance AS distance
                FROM {self._VEC_TABLE} v
                JOIN {self._MAP_TABLE} m ON m.rowid = v.rowid
                WHERE v.embedding MATCH ? AND k = ?
                ORDER BY v.distance
                """,  # noqa: S608
                (_serialize_f32(query_vector), k),
            ).fetchall()
        return [(str(r["memory_id"]), float(r["distance"])) for r in rows]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def semantic_search(
    storage: SQLiteStorage,
    query: str,
    *,
    limit: int = 8,
    embedder: Embedder | None = None,
    prefer: bool | None = None,
) -> list[MemoryEntry] | None:
    """Rank memories by semantic nearness to *query* using sqlite-vec.

    Returns a ranked list of :class:`MemoryEntry` (nearest first), or ``None``
    when the sqlite-vec backend is unavailable / not selected / errors — in
    which case the caller MUST fall back to the existing hash-embedder rerank
    path.  Returning ``None`` (rather than an empty list) is the explicit
    "backend unavailable, fall back" signal; an empty list means "backend ran
    but found no vectors".

    The vector cache is populated on demand from all memories, then the KNN
    index is rebuilt from it, so this is self-contained.
    """
    if not sqlitevec_selected(prefer=prefer):
        return None
    if not query.strip():
        return []

    if embedder is None:
        try:
            embedder = get_embedder()
        except Exception:  # noqa: BLE001
            return None

    try:
        # Lazy import to avoid a cycle at module import time.
        from oh_no_my_claudecode.embeddings.rerank import (  # noqa: PLC0415
            build_vectors_for_all_memories,
        )

        build_vectors_for_all_memories(storage, embedder=embedder)

        store = SqliteVecStore(storage, dim=embedder.dim)
        store.rebuild(embedder=embedder)

        query_vec = embedder.embed(query)
        hits = store.knn(query_vec, k=limit)
    except Exception:  # noqa: BLE001
        # Any backend failure → signal fallback.
        return None

    if not hits:
        return []

    by_id = {m.id: m for m in storage.list_memories()}
    ranked: list[MemoryEntry] = []
    for memory_id, _distance in hits:
        memory = by_id.get(memory_id)
        if memory is not None:
            ranked.append(memory)
    return ranked
