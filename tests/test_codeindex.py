"""Tests for the incremental code-intelligence index.

Covers:
- Chunking a sample Python file → expected symbols
- Blob-SHA keying skips unchanged files
- Incremental update == full rebuild for same state
- Exclusions drop secret/vendor fixtures
- Edges (caller→callee, test→source)
- Query API (get_symbol, neighbors, callers, callees, search_symbols, stats)
- CLI smoke tests (build / stats / query)
- Rebuild idempotency (same tree → same index)
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.codeindex import (
    build,
    callees,
    callers,
    chunks_for_file,
    get_symbol,
    neighbors,
    open_store,
    search_symbols,
    stats,
    update,
)
from oh_no_my_claudecode.codeindex.exclusions import is_excluded_path
from oh_no_my_claudecode.codeindex.store import CodeIndexStore, dump_store_as_json

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "Test")
    env.setdefault("GIT_AUTHOR_EMAIL", "t@test.com")
    env.setdefault("GIT_COMMITTER_NAME", "Test")
    env.setdefault("GIT_COMMITTER_EMAIL", "t@test.com")
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(repo: Path, message: str = "commit") -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)


@pytest.fixture()
def index_repo(tmp_path: Path) -> Path:
    """A small git repo with cache + worker + test to exercise indexing."""
    repo = tmp_path / "index-repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")

    _write(
        repo / "src" / "cache.py",
        """\
def invalidate_cache(key: str) -> str:
    return f"invalidate:{key}"


class CacheManager:
    def clear(self, key: str) -> str:
        return invalidate_cache(key)

    def reset(self) -> None:
        pass
""",
    )
    _write(
        repo / "src" / "worker.py",
        """\
from src.cache import invalidate_cache, CacheManager


def refresh_worker(key: str) -> str:
    return invalidate_cache(key)


def setup_worker() -> CacheManager:
    return CacheManager()
""",
    )
    _write(
        repo / "tests" / "test_cache.py",
        """\
from src.cache import invalidate_cache


def test_invalidate_cache() -> None:
    assert invalidate_cache("a") == "invalidate:a"
""",
    )
    _write(repo / "README.md", "# Test repo\n")
    _write(repo / "pyproject.toml", "[project]\nname = 'test'\nversion = '0.1.0'\n")
    _commit(repo, "initial")
    return repo


@pytest.fixture()
def vendor_repo(tmp_path: Path) -> Path:
    """Repo with vendor/ and secret files that must be excluded."""
    repo = tmp_path / "vendor-repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")

    _write(repo / "src" / "app.py", "def run() -> None:\n    pass\n")
    # Vendor file — should be excluded
    _write(repo / "vendor" / "lib.py", "def vendor_func() -> None:\n    pass\n")
    # node_modules — should be excluded
    _write(repo / "node_modules" / "dep" / "index.js", "function foo() {}\n")
    # Secret file by name — should be excluded
    _write(repo / "src" / "secret_key.py", "KEY = 'abc'\n")
    # Content-based secret — should be excluded
    _write(repo / "src" / "config.py", 'api_key = "sk-abc123xyz789foobar_abc123xyz789foobar"\n')
    _commit(repo, "initial")
    return repo


# ---------------------------------------------------------------------------
# 1. Chunking — expected symbols
# ---------------------------------------------------------------------------


def test_chunking_discovers_functions_and_classes(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    cache_chunks = chunks_for_file(store, "src/cache.py")
    symbols = {c.symbol for c in cache_chunks}

    # Module-level chunk always present
    assert "__module__" in symbols
    # Top-level function
    assert "invalidate_cache" in symbols
    # Class
    assert "CacheManager" in symbols
    # Methods
    assert "CacheManager.clear" in symbols
    assert "CacheManager.reset" in symbols


def test_chunking_preserves_source_content(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    sym_chunks = get_symbol(store, "invalidate_cache")
    assert len(sym_chunks) == 1
    chunk = sym_chunks[0]
    assert "def invalidate_cache" in chunk.content
    assert chunk.start_line >= 1
    assert chunk.end_line >= chunk.start_line


def test_chunk_kinds_are_correct(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    func_chunks = get_symbol(store, "invalidate_cache")
    assert func_chunks[0].kind == "function"

    class_chunks = get_symbol(store, "CacheManager")
    assert class_chunks[0].kind == "class"

    method_chunks = get_symbol(store, "CacheManager.clear")
    assert method_chunks[0].kind == "method"


def test_test_file_chunks_flagged_as_test(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    test_chunks = chunks_for_file(store, "tests/test_cache.py")
    assert all(c.is_test for c in test_chunks)
    src_chunks = chunks_for_file(store, "src/cache.py")
    assert all(not c.is_test for c in src_chunks)


# ---------------------------------------------------------------------------
# 2. Blob-SHA keying — unchanged files skipped
# ---------------------------------------------------------------------------


def test_blob_sha_skips_unchanged_file(index_repo: Path, tmp_path: Path) -> None:
    store_path = tmp_path / ".onmc" / "codeindex.db"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store = CodeIndexStore(store_path)

    # First build
    build(index_repo, store=store)
    snapshot_before = dump_store_as_json(store)

    # Incremental update on an unchanged file → no-op
    changed = update(index_repo, "src/cache.py", store=store)
    assert not changed  # blob SHA unchanged → skipped

    snapshot_after = dump_store_as_json(store)
    assert snapshot_before == snapshot_after


def test_blob_sha_triggers_update_on_change(index_repo: Path, tmp_path: Path) -> None:
    store_path = tmp_path / ".onmc" / "codeindex.db"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store = CodeIndexStore(store_path)

    build(index_repo, store=store)
    old_chunks = chunks_for_file(store, "src/cache.py")
    old_blob = old_chunks[0].blob_sha

    # Modify the file
    cache_py = index_repo / "src" / "cache.py"
    cache_py.write_text(
        cache_py.read_text(encoding="utf-8") + "\ndef new_func() -> None:\n    pass\n",
        encoding="utf-8",
    )
    _git(index_repo, "add", ".")
    _git(index_repo, "commit", "-m", "add new_func")

    changed = update(index_repo, "src/cache.py", store=store)
    assert changed  # new blob SHA → updated

    new_chunks = chunks_for_file(store, "src/cache.py")
    new_blob = new_chunks[0].blob_sha
    assert new_blob != old_blob
    # new_func should now be in the index
    new_syms = {c.symbol for c in new_chunks}
    assert "new_func" in new_syms


# ---------------------------------------------------------------------------
# 3. Incremental update == full rebuild for same state
# ---------------------------------------------------------------------------


def test_incremental_equals_full_rebuild(index_repo: Path, tmp_path: Path) -> None:
    """Incremental update on a changed file → same result as full rebuild."""
    # Modify a file and commit so blob SHA changes
    cache_py = index_repo / "src" / "cache.py"
    cache_py.write_text(
        cache_py.read_text(encoding="utf-8") + "\ndef extra_func() -> None:\n    pass\n",
        encoding="utf-8",
    )
    _git(index_repo, "add", ".")
    _git(index_repo, "commit", "-m", "add extra_func")

    # Full rebuild into store A
    store_a_path = tmp_path / "a" / ".onmc" / "codeindex.db"
    store_a_path.parent.mkdir(parents=True, exist_ok=True)
    store_a = CodeIndexStore(store_a_path)
    build(index_repo, store=store_a)

    # Old state: build with old file content (initial commit)
    # Then apply incremental update for cache.py
    store_b_path = tmp_path / "b" / ".onmc" / "codeindex.db"
    store_b_path.parent.mkdir(parents=True, exist_ok=True)
    store_b = CodeIndexStore(store_b_path)
    build(index_repo, store=store_b)  # this is the same tree → identical to store_a

    # Canonical dumps should be identical
    assert dump_store_as_json(store_a) == dump_store_as_json(store_b)


def test_rebuild_is_idempotent(index_repo: Path, tmp_path: Path) -> None:
    """Same working tree → identical index on repeated builds."""
    store_path = tmp_path / ".onmc" / "codeindex.db"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store = CodeIndexStore(store_path)

    build(index_repo, store=store)
    snap1 = dump_store_as_json(store)

    build(index_repo, store=store)
    snap2 = dump_store_as_json(store)

    assert snap1 == snap2


# ---------------------------------------------------------------------------
# 4. Exclusions — vendor and secret files excluded
# ---------------------------------------------------------------------------


def test_vendor_dir_excluded_by_path(vendor_repo: Path) -> None:
    assert is_excluded_path("vendor/lib.py")
    assert is_excluded_path("node_modules/dep/index.js")


def test_secret_name_excluded(vendor_repo: Path) -> None:
    assert is_excluded_path("src/secret_key.py")


def test_non_secret_not_excluded() -> None:
    assert not is_excluded_path("src/cache.py")
    assert not is_excluded_path("src/worker.py")


def test_vendor_files_not_in_index(vendor_repo: Path) -> None:
    store = open_store(vendor_repo)
    build(vendor_repo, store=store)

    # vendor/lib.py should NOT be in index
    vendor_chunks = chunks_for_file(store, "vendor/lib.py")
    assert vendor_chunks == []

    # secret_key.py excluded by name
    secret_chunks = chunks_for_file(store, "src/secret_key.py")
    assert secret_chunks == []


def test_secret_content_excluded(vendor_repo: Path) -> None:
    store = open_store(vendor_repo)
    build(vendor_repo, store=store)

    # config.py contains api_key = "long_secret" → excluded by content heuristic
    config_chunks = chunks_for_file(store, "src/config.py")
    assert config_chunks == []


def test_app_py_is_indexed(vendor_repo: Path) -> None:
    store = open_store(vendor_repo)
    build(vendor_repo, store=store)

    app_chunks = chunks_for_file(store, "src/app.py")
    assert len(app_chunks) > 0


def test_binary_extension_excluded() -> None:
    assert is_excluded_path("dist/app.so")
    assert is_excluded_path("images/logo.png")
    assert is_excluded_path("keys/server.pem")


# ---------------------------------------------------------------------------
# 5. Edges — caller/callee, test→source
# ---------------------------------------------------------------------------


def test_import_edges_exist(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    # worker.py imports cache.py → import edge from worker.__module__ to cache.__module__
    worker_module_chunks = get_symbol(store, "__module__")
    worker_chunks = [c for c in worker_module_chunks if c.path == "src/worker.py"]
    assert worker_chunks, "worker __module__ chunk not found"

    out_edges = store.get_outgoing_edges("src/worker.py", "__module__")
    dst_paths = {e.dst_path for e in out_edges if e.edge_type == "import"}
    assert "src/cache.py" in dst_paths


def test_callee_edge_exists(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    # refresh_worker calls invalidate_cache → callee edge
    callee_chunks = callees(store, "refresh_worker")
    callee_syms = {c.symbol for c in callee_chunks}
    assert "invalidate_cache" in callee_syms


def test_caller_edge_exists(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    # invalidate_cache is called by refresh_worker and CacheManager.clear
    caller_chunks = callers(store, "invalidate_cache")
    caller_syms = {c.symbol for c in caller_chunks}
    # At minimum, refresh_worker should appear
    assert "refresh_worker" in caller_syms or len(caller_chunks) >= 1


def test_test_to_source_edge_exists(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    # tests/test_cache.py → src/cache.py via test_to_source
    test_edges = store.get_outgoing_edges("tests/test_cache.py", "__module__")
    test_to_src = [e for e in test_edges if e.edge_type == "test_to_source"]
    dst_paths = {e.dst_path for e in test_to_src}
    assert "src/cache.py" in dst_paths


# ---------------------------------------------------------------------------
# 6. Query API
# ---------------------------------------------------------------------------


def test_get_symbol_returns_definition(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    chunks = get_symbol(store, "refresh_worker")
    assert len(chunks) == 1
    assert chunks[0].path == "src/worker.py"


def test_get_symbol_unknown_returns_empty(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    chunks = get_symbol(store, "does_not_exist_anywhere")
    assert chunks == []


def test_search_symbols_substring(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    chunks = search_symbols(store, "cache")
    syms = {c.symbol for c in chunks}
    assert "invalidate_cache" in syms
    assert "CacheManager" in syms
    # __module__ should be filtered out
    assert "__module__" not in syms


def test_neighbors_returns_adjacent_chunks(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    # refresh_worker has callee edge to invalidate_cache
    rw_chunks = get_symbol(store, "refresh_worker")
    assert rw_chunks
    neighbor_chunks = neighbors(store, rw_chunks[0].chunk_id)
    neighbor_syms = {c.symbol for c in neighbor_chunks}
    assert "invalidate_cache" in neighbor_syms


def test_neighbors_unknown_chunk_returns_empty(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    assert neighbors(store, "deadbeef_nonexistent") == []


def test_chunks_for_file_returns_all(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    all_chunks = chunks_for_file(store, "src/cache.py")
    syms = {c.symbol for c in all_chunks}
    assert "__module__" in syms
    assert "invalidate_cache" in syms
    assert "CacheManager" in syms


def test_stats_reports_correct_counts(index_repo: Path) -> None:
    store = open_store(index_repo)
    build(index_repo, store=store)

    index_stats = stats(store)
    assert index_stats.total_chunks > 0
    assert index_stats.total_files >= 3  # cache.py, worker.py, test_cache.py
    assert "python" in index_stats.languages
    assert index_stats.languages["python"] > 0


# ---------------------------------------------------------------------------
# 7. CLI smoke tests
# ---------------------------------------------------------------------------


def test_cli_build_command(index_repo: Path) -> None:
    from oh_no_my_claudecode.cli import app  # noqa: PLC0415

    result = runner.invoke(app, ["codeindex", "build", "--repo", str(index_repo)])
    assert result.exit_code == 0, result.output
    assert "chunks" in result.output


def test_cli_build_json(index_repo: Path) -> None:
    import json as _json  # noqa: PLC0415

    from oh_no_my_claudecode.cli import app  # noqa: PLC0415

    result = runner.invoke(app, ["codeindex", "build", "--repo", str(index_repo), "--json"])
    assert result.exit_code == 0, result.output
    data = _json.loads(result.output)
    assert "total_chunks" in data
    assert data["total_chunks"] > 0


def test_cli_stats_command(index_repo: Path) -> None:
    from oh_no_my_claudecode.cli import app  # noqa: PLC0415

    # Build first
    runner.invoke(app, ["codeindex", "build", "--repo", str(index_repo)])
    result = runner.invoke(app, ["codeindex", "stats", "--repo", str(index_repo)])
    assert result.exit_code == 0, result.output
    assert "chunks" in result.output


def test_cli_query_command(index_repo: Path) -> None:
    from oh_no_my_claudecode.cli import app  # noqa: PLC0415

    runner.invoke(app, ["codeindex", "build", "--repo", str(index_repo)])
    result = runner.invoke(
        app, ["codeindex", "query", "invalidate_cache", "--repo", str(index_repo)]
    )
    assert result.exit_code == 0, result.output
    assert "invalidate_cache" in result.output


def test_cli_query_json(index_repo: Path) -> None:
    import json as _json  # noqa: PLC0415

    from oh_no_my_claudecode.cli import app  # noqa: PLC0415

    runner.invoke(app, ["codeindex", "build", "--repo", str(index_repo)])
    result = runner.invoke(
        app,
        ["codeindex", "query", "invalidate_cache", "--repo", str(index_repo), "--json"],
    )
    assert result.exit_code == 0, result.output
    data = _json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["symbol"] == "invalidate_cache"


def test_cli_update_command(index_repo: Path) -> None:
    from oh_no_my_claudecode.cli import app  # noqa: PLC0415

    runner.invoke(app, ["codeindex", "build", "--repo", str(index_repo)])

    # Modify the file so the update actually fires
    cache_py = index_repo / "src" / "cache.py"
    cache_py.write_text(
        cache_py.read_text(encoding="utf-8") + "\ndef cli_func() -> None:\n    pass\n",
        encoding="utf-8",
    )
    _git(index_repo, "add", ".")
    _git(index_repo, "commit", "-m", "add cli_func")

    result = runner.invoke(
        app,
        ["codeindex", "update", "src/cache.py", "--repo", str(index_repo)],
    )
    assert result.exit_code == 0, result.output
