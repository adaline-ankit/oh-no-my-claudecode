"""Atomic full rebuild and incremental one-file update for the code index.

**Atomic full rebuild** (``build``):

1. Walk every indexable source file under *repo_root* (using
   :func:`~oh_no_my_claudecode.codeindex.exclusions.should_index` + extension
   check to filter).
2. Fetch all git blob SHAs via ``git ls-files -s``.
3. For each file: chunk it, compute edges.
4. Write all chunks and edges inside a single SQLite transaction — the index
   is either fully written or unchanged.

**Incremental one-file update** (``update``):

1. Recompute the blob SHA for the changed file.
2. If the blob SHA matches what is stored → no-op (file unchanged).
3. Otherwise: delete the file's old chunks + outgoing edges, re-chunk, re-insert.

Both operations are **deterministic** — same working tree → same index state.
A test in ``tests/test_codeindex.py`` asserts that incremental update produces
the same index as a full rebuild.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from oh_no_my_claudecode.codeindex.chunker import (
    build_import_edges,
    chunk_file,
    compute_blob_sha,
    get_blob_shas,
    get_head_commit_sha,
    should_chunk_extension,
)
from oh_no_my_claudecode.codeindex.exclusions import EXCLUDE_DIRS, should_index
from oh_no_my_claudecode.codeindex.models import IndexEdge
from oh_no_my_claudecode.codeindex.store import CodeIndexStore, open_store

# Hard cap on files to prevent runaway behaviour on huge monorepos.
_MAX_FILES = 5000


def _discover_indexable_files(repo_root: Path) -> list[str]:
    """Return sorted repo-relative paths of all files worth indexing.

    Applies directory exclusions, extension filter, and
    :func:`~oh_no_my_claudecode.codeindex.exclusions.should_index` (path +
    secret-content check).
    """
    found: list[str] = []
    for current_root, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith(".git")
        )
        for filename in sorted(filenames):
            abs_file = Path(current_root) / filename
            if abs_file.is_symlink():
                continue
            try:
                rel = abs_file.resolve().relative_to(repo_root.resolve()).as_posix()
            except ValueError:
                continue
            if not should_chunk_extension(rel):
                continue
            if not should_index(abs_file, repo_root):
                continue
            found.append(rel)
            if len(found) >= _MAX_FILES:
                break
        if len(found) >= _MAX_FILES:
            break

    found.sort()
    return found


def _resolve_callee_edges(
    caller_path: str,
    call_edges: list[tuple[str, str]],
    symbol_to_paths: dict[str, list[str]],
) -> list[IndexEdge]:
    """Convert raw (caller_symbol, called_name) pairs into :class:`IndexEdge` objects.

    Looks up each called name in *symbol_to_paths* (a mapping of symbol →
    file paths where it is defined).  Returns one edge per unique
    (src, dst) pair.  Skips self-calls and ambiguous calls to symbols
    defined in more than three files (too noisy).
    """
    edges: list[IndexEdge] = []
    seen: set[tuple[str, str, str, str]] = set()
    for caller_sym, called_name in call_edges:
        dst_paths = symbol_to_paths.get(called_name, [])
        if not dst_paths or len(dst_paths) > 3:  # noqa: PLR2004
            continue
        for dst_path in dst_paths:
            if dst_path == caller_path:
                continue  # skip self-calls
            key = (caller_path, caller_sym, dst_path, called_name)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                IndexEdge(
                    src_path=caller_path,
                    src_symbol=caller_sym,
                    dst_path=dst_path,
                    dst_symbol=called_name,
                    edge_type="callee",
                )
            )
    return edges


def build(repo_root: Path, *, store: CodeIndexStore | None = None) -> CodeIndexStore:
    """Atomically rebuild the full code index for *repo_root*.

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root.
    store:
        Optional pre-opened store (injected by tests).  When omitted, opens
        the default store at ``<repo_root>/.onmc/codeindex.db``.

    Returns
    -------
    CodeIndexStore
        The populated store.
    """
    repo_root = repo_root.resolve()
    if store is None:
        store = open_store(repo_root)

    commit_sha = get_head_commit_sha(repo_root)
    blob_sha_map = get_blob_shas(repo_root)
    built_at = datetime.now(tz=UTC).isoformat(timespec="seconds")

    indexable = _discover_indexable_files(repo_root)

    # First pass: chunk every file, accumulate symbol→paths index.
    all_chunks = []
    all_call_edges: dict[str, list[tuple[str, str]]] = {}  # path → [(caller_sym, called)]
    symbol_to_paths: dict[str, list[str]] = {}
    excluded_count = 0

    for rel_path in indexable:
        abs_path = repo_root / rel_path
        blob_sha = blob_sha_map.get(rel_path) or compute_blob_sha(abs_path)
        if not blob_sha:
            excluded_count += 1
            continue

        chunks, call_edges = chunk_file(abs_path, rel_path, blob_sha, commit_sha)
        if not chunks:
            excluded_count += 1
            continue

        all_chunks.extend(chunks)
        all_call_edges[rel_path] = call_edges

        # Build symbol→paths index from chunks in this file
        for chunk in chunks:
            if chunk.symbol != "__module__":
                symbol_to_paths.setdefault(chunk.symbol, [])
                if rel_path not in symbol_to_paths[chunk.symbol]:
                    symbol_to_paths[chunk.symbol].append(rel_path)

    # Second pass: build edges.
    indexed_paths = set(indexable)
    all_edges: list[IndexEdge] = []

    for rel_path in indexable:
        # Import edges (Python only)
        import_edges = build_import_edges(rel_path, repo_root, {}, indexed_paths)
        all_edges.extend(import_edges)

        # Callee edges
        call_edges = all_call_edges.get(rel_path, [])
        all_edges.extend(_resolve_callee_edges(rel_path, call_edges, symbol_to_paths))

        # Test-to-source edges
        if _is_test_file(rel_path):
            for imp_edge in import_edges:
                if not _is_test_file(imp_edge.dst_path):
                    all_edges.append(
                        IndexEdge(
                            src_path=rel_path,
                            src_symbol="__module__",
                            dst_path=imp_edge.dst_path,
                            dst_symbol="__module__",
                            edge_type="test_to_source",
                        )
                    )

    # Deduplicate edges
    seen_edges: set[tuple[str, str, str, str, str]] = set()
    deduped_edges: list[IndexEdge] = []
    for edge in all_edges:
        key = (edge.src_path, edge.src_symbol, edge.dst_path, edge.dst_symbol, edge.edge_type)
        if key not in seen_edges:
            seen_edges.add(key)
            deduped_edges.append(edge)

    # Atomic write: clear old index, write new.
    with store._transaction() as conn:  # noqa: SLF001
        conn.execute("DELETE FROM ci_chunks")
        conn.execute("DELETE FROM ci_edges")
        conn.executemany(
            """INSERT OR REPLACE INTO ci_chunks
               (chunk_id, blob_sha, commit_sha, path, symbol, kind,
                start_line, end_line, language, is_test, is_stale,
                trust_level, indexed_at, content)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    c.chunk_id, c.blob_sha, c.commit_sha, c.path, c.symbol,
                    c.kind, c.start_line, c.end_line, c.language,
                    int(c.is_test), int(c.is_stale), c.trust_level,
                    c.indexed_at, c.content,
                )
                for c in all_chunks
            ],
        )
        conn.executemany(
            """INSERT OR REPLACE INTO ci_edges
               (src_path, src_symbol, dst_path, dst_symbol, edge_type)
               VALUES (?,?,?,?,?)""",
            [
                (e.src_path, e.src_symbol, e.dst_path, e.dst_symbol, e.edge_type)
                for e in deduped_edges
            ],
        )
        conn.execute(
            "INSERT OR REPLACE INTO ci_meta(key, value) VALUES (?, ?)",
            ("commit_sha", commit_sha),
        )
        conn.execute(
            "INSERT OR REPLACE INTO ci_meta(key, value) VALUES (?, ?)",
            ("built_at", built_at),
        )
        conn.execute(
            "INSERT OR REPLACE INTO ci_meta(key, value) VALUES (?, ?)",
            ("excluded_files", str(excluded_count)),
        )

    return store


def update(
    repo_root: Path,
    changed_path: str,
    *,
    store: CodeIndexStore | None = None,
) -> bool:
    """Incrementally update one file in the code index.

    If the file's blob SHA matches what is stored → no-op, returns False.
    Otherwise: deletes old chunks and outgoing edges for *changed_path*,
    re-chunks the file, re-inserts chunks and edges.  Returns True.

    For the same working-tree state, ``update`` produces the same index as
    a full ``build`` for the affected file.  (A full build may produce a
    superset for other files, but the single-file slice is identical.)

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root.
    changed_path:
        Repo-relative POSIX path of the file to re-index.
    store:
        Optional pre-opened store (injected by tests).

    Returns
    -------
    bool
        True if the index was updated, False if the file was unchanged.
    """
    repo_root = repo_root.resolve()
    if store is None:
        store = open_store(repo_root)

    abs_path = repo_root / changed_path
    if not abs_path.exists():
        # File deleted — mark its chunks as stale.
        store.mark_stale([changed_path])
        store.delete_edges_for_path(changed_path)
        return True

    # Blob SHA check — skip if unchanged.
    current_blob_sha = compute_blob_sha(abs_path)
    if not current_blob_sha:
        return False

    indexed_shas = store.get_indexed_blob_shas()
    if indexed_shas.get(changed_path) == current_blob_sha:
        return False  # unchanged

    commit_sha = get_head_commit_sha(repo_root)

    # Delete old chunks and outgoing edges for this file.
    store.delete_chunks_for_path(changed_path)
    store.delete_edges_for_path(changed_path)

    # Re-chunk.
    if not should_chunk_extension(changed_path) or not should_index(abs_path, repo_root):
        return True  # file excluded — old chunks cleared, done

    chunks, call_edges = chunk_file(abs_path, changed_path, current_blob_sha, commit_sha)
    if not chunks:
        return True

    store.upsert_chunks(chunks)

    # Build symbol→paths from the FULL index (needed for callee resolution).
    # This is a light query — only reads the symbol+path columns.
    conn = store._connect()  # noqa: SLF001
    try:
        sym_rows = conn.execute(
            "SELECT symbol, path FROM ci_chunks WHERE symbol != '__module__'"
        ).fetchall()
    finally:
        conn.close()

    symbol_to_paths: dict[str, list[str]] = {}
    for row in sym_rows:
        sym = str(row["symbol"])
        path = str(row["path"])
        symbol_to_paths.setdefault(sym, [])
        if path not in symbol_to_paths[sym]:
            symbol_to_paths[sym].append(path)

    # Collect indexed paths for import resolution.
    conn2 = store._connect()  # noqa: SLF001
    try:
        path_rows = conn2.execute("SELECT DISTINCT path FROM ci_chunks").fetchall()
    finally:
        conn2.close()
    indexed_paths = {str(r["path"]) for r in path_rows}

    # Build edges.
    new_edges: list[IndexEdge] = []
    import_edges = build_import_edges(changed_path, repo_root, {}, indexed_paths)
    new_edges.extend(import_edges)
    new_edges.extend(_resolve_callee_edges(changed_path, call_edges, symbol_to_paths))

    if _is_test_file(changed_path):
        for imp_edge in import_edges:
            if not _is_test_file(imp_edge.dst_path):
                new_edges.append(
                    IndexEdge(
                        src_path=changed_path,
                        src_symbol="__module__",
                        dst_path=imp_edge.dst_path,
                        dst_symbol="__module__",
                        edge_type="test_to_source",
                    )
                )

    # Deduplicate
    seen_edges: set[tuple[str, str, str, str, str]] = set()
    deduped: list[IndexEdge] = []
    for edge in new_edges:
        key = (edge.src_path, edge.src_symbol, edge.dst_path, edge.dst_symbol, edge.edge_type)
        if key not in seen_edges:
            seen_edges.add(key)
            deduped.append(edge)

    store.upsert_edges(deduped)
    store.set_meta("commit_sha", commit_sha)
    return True


def _is_test_file(rel_path: str) -> bool:
    from oh_no_my_claudecode.core.repo import is_test_path  # noqa: PLC0415

    return is_test_path(rel_path)
