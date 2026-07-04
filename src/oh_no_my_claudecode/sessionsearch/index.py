"""Core FTS5 search engine for ``onmc session-search``.

Design
------
We build an **in-memory** FTS5 index over the union of four text-rich tables
from the onmc SQLite store:

    memories        — title, summary, details, tags_json
    attempts        — summary, reasoning_summary, evidence_for, evidence_against
    tasks           — title, description, final_summary
    memory_artifacts — title, summary, why_it_matters, apply_when, avoid_when, evidence

The store's own ``memories_fts`` index (migration v2) only covers memories.
This module creates a fresh *in-memory* index (never touching the user's DB
schema) that spans all four corpora so ``onmc session-search`` finds results
across the entire history.

Ranking
-------
When FTS5 is available, results are ranked by BM25 score (lower = more
relevant in SQLite's FTS5).  The stable tie-break is ``rowid ASC`` (insertion
order), making results deterministic.

When FTS5 is unavailable (rare — Python's stdlib sqlite3 ships with FTS5 on
most platforms since 3.9) the module falls back to a LIKE scan over all text
columns, ordered by ``source`` then ``record_id``.

Snippet extraction
------------------
We produce a short snippet by scanning the joined text for the first window
of ~120 characters containing any query token.  This is done in Python (not
via FTS5 snippet()) so it works identically in both the FTS5 and LIKE paths.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from oh_no_my_claudecode.storage.sqlite import _sanitize_fts_query, fts5_available  # noqa: PLC2701

# ---------------------------------------------------------------------------
# Public data class
# ---------------------------------------------------------------------------

_SNIPPET_WINDOW = 120  # characters on each side of the first matched token
_SNIPPET_MAX = 240  # total snippet length cap


@dataclass(frozen=True)
class Hit:
    """One search result returned by :func:`search`."""

    record_id: str
    """Primary-key / id of the matching row."""

    source: str
    """Which corpus the hit came from: ``memory``, ``attempt``, ``task``,
    or ``memory_artifact``."""

    title: str
    """Human-readable title or first-line of the record."""

    snippet: str
    """Short excerpt (≤240 chars) showing the context around the match."""

    score: float
    """Relevance score.  Higher is more relevant.

    For FTS5 results this is ``-bm25(...)`` (negated so higher = better).
    For LIKE-fallback results this is the count of matched tokens, with a
    stable tie-break.
    """


# ---------------------------------------------------------------------------
# Corpus loader — reads from the user's DB (read-only)
# ---------------------------------------------------------------------------


def _load_corpus(db_path: Path) -> list[tuple[str, str, str, str]]:
    """Return ``(record_id, source, title, body)`` rows from all corpora.

    Opens the store in read-only URI mode so we never acquire a write lock.
    Returns an empty list when the DB does not exist yet.
    """
    if not db_path.exists():
        return []

    uri = db_path.as_uri() + "?mode=ro"
    rows: list[tuple[str, str, str, str]] = []
    try:
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            # memories
            try:
                for row in conn.execute(
                    "SELECT id, title,"
                    " (title || ' ' || summary || ' ' || details || ' ' || tags_json) AS body"
                    " FROM memories"
                ):
                    rows.append((str(row["id"]), "memory", str(row["title"]), str(row["body"])))
            except sqlite3.OperationalError:
                pass

            # attempts
            try:
                for row in conn.execute(
                    "SELECT attempt_id,"
                    " (summary || ' ' || COALESCE(reasoning_summary,'') ||"
                    "  ' ' || COALESCE(evidence_for,'') ||"
                    "  ' ' || COALESCE(evidence_against,'')) AS body"
                    " FROM attempts"
                ):
                    body = str(row["body"])
                    # derive a short title from the first 80 chars of body
                    title = body[:80].rstrip()
                    rows.append((str(row["attempt_id"]), "attempt", title, body))
            except sqlite3.OperationalError:
                pass

            # tasks
            try:
                for row in conn.execute(
                    "SELECT task_id, title,"
                    " (title || ' ' || description || ' ' || COALESCE(final_summary,'')) AS body"
                    " FROM tasks"
                ):
                    rows.append((str(row["task_id"]), "task", str(row["title"]), str(row["body"])))
            except sqlite3.OperationalError:
                pass

            # memory_artifacts
            try:
                for row in conn.execute(
                    "SELECT memory_id, title,"
                    " (title || ' ' || summary || ' ' || why_it_matters ||"
                    "  ' ' || COALESCE(apply_when,'') || ' ' || COALESCE(avoid_when,'') ||"
                    "  ' ' || evidence) AS body"
                    " FROM memory_artifacts"
                ):
                    rows.append(
                        (str(row["memory_id"]), "memory_artifact",
                         str(row["title"]), str(row["body"]))
                    )
            except sqlite3.OperationalError:
                pass
    except sqlite3.OperationalError:
        # DB file exists but is not a valid SQLite DB yet — treat as empty.
        return []
    return rows


# ---------------------------------------------------------------------------
# In-memory FTS5 index builder
# ---------------------------------------------------------------------------


def _build_fts_index(
    mem_conn: sqlite3.Connection,
    rows: list[tuple[str, str, str, str]],
) -> bool:
    """Populate an in-memory FTS5 index.  Returns True on success."""
    try:
        mem_conn.execute(
            "CREATE VIRTUAL TABLE corpus_fts USING fts5("
            "record_id UNINDEXED, source UNINDEXED, title UNINDEXED,"
            "body,"
            "tokenize='unicode61 remove_diacritics 1'"
            ")"
        )
        mem_conn.executemany(
            "INSERT INTO corpus_fts(record_id, source, title, body) VALUES (?,?,?,?)",
            rows,
        )
        return True
    except sqlite3.OperationalError:
        return False


# ---------------------------------------------------------------------------
# Snippet extraction
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _make_snippet(body: str, query: str) -> str:
    """Return a ≤240-char excerpt from *body* centred on the first query token."""
    tokens = [t.lower() for t in _TOKEN_RE.findall(query) if len(t) >= 2]
    body_lower = body.lower()
    best_pos = -1
    for tok in tokens:
        pos = body_lower.find(tok)
        if pos >= 0:
            best_pos = pos
            break
    if best_pos < 0:
        # No token found — return start of body
        return body[:_SNIPPET_MAX].strip()
    start = max(0, best_pos - _SNIPPET_WINDOW // 2)
    end = min(len(body), start + _SNIPPET_MAX)
    snippet = body[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(body):
        snippet = snippet + "…"
    return snippet


# ---------------------------------------------------------------------------
# Public search function
# ---------------------------------------------------------------------------


def search(
    db_path: Path,
    query: str,
    *,
    limit: int = 20,
) -> list[Hit]:
    """Return up to *limit* :class:`Hit` objects matching *query*.

    Opens the user's SQLite store read-only, loads all text corpora, builds
    an in-memory FTS5 index (or falls back to LIKE), and returns results
    ranked by relevance.

    Parameters
    ----------
    db_path:
        Path to the onmc SQLite database (typically ``<repo>/.onmc/onmc.db``).
    query:
        Free-text search string.  All alphanumeric tokens (≥2 chars) are
        matched.  Multi-word queries use OR so partial matches are included;
        a downstream token-overlap reranker applies precision ordering.
    limit:
        Maximum number of results.  Default: 20.
    """
    if not query.strip():
        return []

    corpus = _load_corpus(db_path)
    if not corpus:
        return []

    # --- Try FTS5 path first -----------------------------------------------
    with closing(sqlite3.connect(":memory:")) as mem_conn:
        mem_conn.row_factory = sqlite3.Row
        use_fts5 = fts5_available(mem_conn) and _build_fts_index(mem_conn, corpus)

        if use_fts5:
            match_expr = _sanitize_fts_query(query)
            if match_expr is not None:
                sql = (
                    "SELECT record_id, source, title, body,"
                    " -bm25(corpus_fts) AS score"
                    " FROM corpus_fts"
                    " WHERE corpus_fts MATCH ?"
                    " ORDER BY score DESC, rowid ASC"
                    " LIMIT ?"
                )
                fts_rows = mem_conn.execute(sql, (match_expr, limit)).fetchall()
                return [
                    Hit(
                        record_id=str(r["record_id"]),
                        source=str(r["source"]),
                        title=str(r["title"]),
                        snippet=_make_snippet(str(r["body"]), query),
                        score=float(r["score"]),
                    )
                    for r in fts_rows
                ]
            # empty sanitized query — fall through to LIKE scan

        # --- LIKE fallback ---------------------------------------------------
        # Build an in-memory plain table for LIKE scan.
        mem_conn.execute(
            "CREATE TABLE IF NOT EXISTS corpus_like"
            " (record_id TEXT, source TEXT, title TEXT, body TEXT)"
        )
        mem_conn.executemany(
            "INSERT INTO corpus_like(record_id, source, title, body) VALUES (?,?,?,?)",
            corpus,
        )

        like_pat = f"%{query.lower()}%"
        # Count how many of the query tokens match (simple relevance proxy).
        tokens = [t.lower() for t in _TOKEN_RE.findall(query) if len(t) >= 2]
        like_rows: list[sqlite3.Row] = mem_conn.execute(
            "SELECT record_id, source, title, body"
            " FROM corpus_like"
            " WHERE LOWER(body) LIKE ?"
            " ORDER BY source ASC, record_id ASC"
            " LIMIT ?",
            (like_pat, limit),
        ).fetchall()

        results: list[Hit] = []
        for r in like_rows:
            body_lower = str(r["body"]).lower()
            tok_count = sum(1 for t in tokens if t in body_lower)
            results.append(
                Hit(
                    record_id=str(r["record_id"]),
                    source=str(r["source"]),
                    title=str(r["title"]),
                    snippet=_make_snippet(str(r["body"]), query),
                    score=float(tok_count),
                )
            )
        # Re-sort by score desc, then stable key
        results.sort(key=lambda h: (-h.score, h.source, h.record_id))
        return results[:limit]
