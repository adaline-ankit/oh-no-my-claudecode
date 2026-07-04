from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.codegraph import (
    CodeGraph,
    build_codegraph,
    context_files,
    neighbors,
    treesitter_ext,
)
from oh_no_my_claudecode.core.service import OnmcService

runner = CliRunner()


# ---------------------------------------------------------------------------
# Builder — symbols, imports, blast radius, tests
# ---------------------------------------------------------------------------


def test_build_indexes_symbols_and_imports(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)

    # Symbols collected per file.
    assert graph.symbols_by_name["invalidate_cache"] == ["src/cache.py"]
    assert graph.symbols_by_name["refresh_worker"] == ["src/worker.py"]
    cache_node = graph.nodes["src/cache.py"]
    assert [(s.name, s.kind) for s in cache_node.symbols] == [("invalidate_cache", "func")]

    # Import edge: worker imports cache.
    assert graph.nodes["src/worker.py"].imports == ["src/cache.py"]

    # Blast radius: cache is depended on by worker + the test.
    assert graph.dependents["src/cache.py"] == ["src/worker.py", "tests/test_cache.py"]


def test_test_files_map_to_imported_modules(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    assert graph.file_tests["src/cache.py"] == ["tests/test_cache.py"]
    # A non-test file never appears as a test mapping value source.
    assert graph.nodes["tests/test_cache.py"].is_test is True
    assert graph.nodes["src/cache.py"].is_test is False


def test_neighbors_of_symbol_returns_importers_and_tests(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    result = neighbors(graph, "invalidate_cache")

    assert result.target_files == ["src/cache.py"]
    assert "src/worker.py" in result.dependents
    assert result.tests == ["tests/test_cache.py"]
    # The symbol's own file has no in-repo imports.
    assert result.imports == []


def test_neighbors_of_file_path_and_suffix(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)

    by_full = neighbors(graph, "src/cache.py")
    by_suffix = neighbors(graph, "cache.py")
    assert by_full.dependents == by_suffix.dependents == [
        "src/worker.py",
        "tests/test_cache.py",
    ]


def test_neighbors_unknown_target_is_graceful(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    result = neighbors(graph, "does_not_exist")
    assert result.target_files == []
    assert result.dependents == []
    assert result.tests == []


# ---------------------------------------------------------------------------
# context_files — bounded selection
# ---------------------------------------------------------------------------


def test_context_returns_bounded_relevant_files(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    selection = context_files(graph, "fix cache invalidation bug", budget=2)

    assert selection.budget == 2
    assert len(selection.files) <= 2
    assert "src/cache.py" in selection.files
    assert "cache" in selection.matched_terms


def test_context_caps_at_budget(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    # A broad goal could match many files; budget=1 must still return exactly 1.
    selection = context_files(graph, "cache worker test", budget=1)
    assert len(selection.files) == 1


def test_context_empty_goal_returns_nothing(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    selection = context_files(graph, "   ", budget=5)
    assert selection.files == []
    assert selection.matched_terms == []


def test_context_no_match_returns_empty(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    selection = context_files(graph, "zzzznonexistenttoken", budget=5)
    assert selection.files == []


# ---------------------------------------------------------------------------
# Edge cases — empty / odd files graceful
# ---------------------------------------------------------------------------


def test_build_handles_empty_and_syntax_error_files(tmp_path: Path) -> None:
    repo = tmp_path / "odd"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "empty.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "broken.py").write_text("def (:\n  oops\n", encoding="utf-8")
    (repo / "pkg" / "ok.py").write_text("def good() -> int:\n    return 1\n", encoding="utf-8")

    graph = build_codegraph(repo)
    assert graph.file_count == 3
    # Empty + broken files yield empty symbol lists, never raise.
    assert graph.nodes["pkg/empty.py"].symbols == []
    assert graph.nodes["pkg/broken.py"].symbols == []
    assert graph.symbols_by_name["good"] == ["pkg/ok.py"]


def test_build_skips_excluded_dirs(tmp_path: Path) -> None:
    repo = tmp_path / "withvenv"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "a.py").write_text("def a() -> None:\n    pass\n", encoding="utf-8")
    (repo / ".venv" / "lib").mkdir(parents=True)
    dep_py = repo / ".venv" / "lib" / "dep.py"
    dep_py.write_text("def dep() -> None:\n    pass\n", encoding="utf-8")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "c.py").write_text("def c() -> None:\n    pass\n", encoding="utf-8")

    graph = build_codegraph(repo)
    assert graph.file_count == 1
    assert "src/a.py" in graph.nodes
    assert "dep" not in graph.symbols_by_name


# ---------------------------------------------------------------------------
# Determinism + serialisation round-trip
# ---------------------------------------------------------------------------


def test_build_is_deterministic(sample_repo: Path) -> None:
    first = build_codegraph(sample_repo).to_dict()
    second = build_codegraph(sample_repo).to_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_codegraph_dict_roundtrip(sample_repo: Path) -> None:
    graph = build_codegraph(sample_repo)
    restored = CodeGraph.from_dict(graph.to_dict())
    assert restored.file_count == graph.file_count
    assert restored.symbols_by_name == graph.symbols_by_name
    assert restored.dependents == graph.dependents
    assert restored.file_tests == graph.file_tests


def test_from_dict_tolerates_missing_keys() -> None:
    graph = CodeGraph.from_dict({})
    assert graph.file_count == 0
    assert graph.nodes == {}


# ---------------------------------------------------------------------------
# Service — build caches + reloads
# ---------------------------------------------------------------------------


def test_service_build_caches_and_reloads(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)  # type: ignore[attr-defined]
    service = OnmcService(sample_repo)
    service.init_project()

    cache_path, graph = service.codegraph_build()
    assert cache_path.exists()
    assert cache_path.name == "codegraph.json"
    assert graph.file_count > 0

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["file_count"] == graph.file_count

    # Neighbors loads from the cache (no rebuild required) and matches.
    result = service.codegraph_neighbors("invalidate_cache")
    assert "src/worker.py" in result.dependents


def test_service_context_builds_on_demand_without_cache(
    sample_repo: Path, monkeypatch: object
) -> None:
    monkeypatch.chdir(sample_repo)  # type: ignore[attr-defined]
    service = OnmcService(sample_repo)
    service.init_project()

    # No build() called first — context must build on demand.
    selection = service.codegraph_context("cache invalidation", budget=3)
    assert "src/cache.py" in selection.files
    assert len(selection.files) <= 3


# ---------------------------------------------------------------------------
# CLI — flags → exit codes / JSON shapes (never assert --help text)
# ---------------------------------------------------------------------------


def _init(repo: Path) -> None:
    OnmcService(repo).init_project()


def test_cli_build_json_shape(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)  # type: ignore[attr-defined]
    _init(sample_repo)
    result = runner.invoke(app, ["codegraph", "build", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "nodes" in payload
    assert "dependents" in payload
    assert payload["file_count"] >= 1


def test_cli_neighbors_json_shape(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)  # type: ignore[attr-defined]
    _init(sample_repo)
    runner.invoke(app, ["codegraph", "build"])
    result = runner.invoke(app, ["codegraph", "neighbors", "src/cache.py", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["target"] == "src/cache.py"
    assert "src/worker.py" in payload["dependents"]


def test_cli_context_json_shape(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)  # type: ignore[attr-defined]
    _init(sample_repo)
    result = runner.invoke(
        app, ["codegraph", "context", "cache invalidation", "--budget", "2", "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["budget"] == 2
    assert len(payload["files"]) <= 2
    assert "src/cache.py" in payload["files"]


def test_cli_neighbors_human_output(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)  # type: ignore[attr-defined]
    _init(sample_repo)
    runner.invoke(app, ["codegraph", "build"])
    result = runner.invoke(app, ["codegraph", "neighbors", "invalidate_cache"])
    assert result.exit_code == 0
    assert "Blast radius" in result.stdout


def test_cli_summary_still_works(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)  # type: ignore[attr-defined]
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    result = runner.invoke(app, ["codegraph", "summary", "--max-files", "3"])
    assert result.exit_code == 0
    assert "# ONMC Codegraph" in result.stdout


# ---------------------------------------------------------------------------
# Fallback (no tree-sitter required) — non-.py files behave predictably
# ---------------------------------------------------------------------------


def test_language_detection_maps_extensions() -> None:
    # Pure table lookup — no tree-sitter needed.
    assert treesitter_ext.language_for_path("src/app.ts") == "typescript"
    assert treesitter_ext.language_for_path("src/app.tsx") == "tsx"
    assert treesitter_ext.language_for_path("src/app.js") == "javascript"
    assert treesitter_ext.language_for_path("main.go") == "go"
    assert treesitter_ext.language_for_path("lib.rs") == "rust"
    assert treesitter_ext.language_for_path("App.java") == "java"
    assert treesitter_ext.language_for_path("notes.md") is None


def test_build_without_treesitter_ignores_non_python(
    tmp_path: Path, monkeypatch: object
) -> None:
    # Force the "not installed" path regardless of the local environment: when
    # tree-sitter is unavailable, only *.py files are ever discovered.
    monkeypatch.setattr(  # type: ignore[attr-defined]
        treesitter_ext, "treesitter_available", lambda: False
    )
    repo = tmp_path / "mixed"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "a.py").write_text("def a() -> None:\n    pass\n", encoding="utf-8")
    (repo / "src" / "app.ts").write_text("export function foo() {}\n", encoding="utf-8")
    (repo / "main.go").write_text("package main\nfunc Foo() {}\n", encoding="utf-8")

    graph = build_codegraph(repo)
    # Only the Python file is indexed — exact original behaviour.
    assert graph.file_count == 1
    assert "src/a.py" in graph.nodes
    assert "src/app.ts" not in graph.nodes
    assert "main.go" not in graph.nodes
    assert "foo" not in graph.symbols_by_name


# ---------------------------------------------------------------------------
# tree-sitter multi-language path (skipped when the extra is not installed)
# ---------------------------------------------------------------------------

pytestmark_ts = pytest.mark.skipif(
    not treesitter_ext.treesitter_available(),
    reason="tree-sitter optional extra not installed",
)


@pytestmark_ts
def test_treesitter_extracts_js_ts_symbols(tmp_path: Path) -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_language_pack")

    repo = tmp_path / "jsrepo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "cache.ts").write_text(
        "export function invalidateCache(key: string): string {\n"
        "  return key;\n"
        "}\n"
        "export class CacheStore {}\n"
        "interface Options {}\n",
        encoding="utf-8",
    )
    (repo / "src" / "worker.ts").write_text(
        'import { invalidateCache } from "./cache";\n'
        "export function refreshWorker(k: string): string {\n"
        "  return invalidateCache(k);\n"
        "}\n",
        encoding="utf-8",
    )

    graph = build_codegraph(repo)

    # Symbols from the TS files land in the same model the Python path uses.
    assert graph.symbols_by_name["invalidateCache"] == ["src/cache.ts"]
    assert graph.symbols_by_name["CacheStore"] == ["src/cache.ts"]
    assert graph.symbols_by_name["Options"] == ["src/cache.ts"]
    assert graph.symbols_by_name["refreshWorker"] == ["src/worker.ts"]

    cache_kinds = {(s.name, s.kind) for s in graph.nodes["src/cache.ts"].symbols}
    assert ("invalidateCache", "func") in cache_kinds
    assert ("CacheStore", "class") in cache_kinds

    # Relative import edge resolved worker.ts → cache.ts.
    assert graph.nodes["src/worker.ts"].imports == ["src/cache.ts"]
    assert graph.dependents["src/cache.ts"] == ["src/worker.ts"]


@pytestmark_ts
def test_treesitter_extracts_go_rust_java_symbols(tmp_path: Path) -> None:
    pytest.importorskip("tree_sitter_language_pack")

    repo = tmp_path / "polyrepo"
    repo.mkdir()
    (repo / "main.go").write_text(
        "package main\n\nfunc RunServer() {}\n\ntype Config struct{}\n",
        encoding="utf-8",
    )
    (repo / "lib.rs").write_text(
        "pub fn parse_input() {}\nstruct Parser;\ntrait Visitor {}\nenum Mode {}\n",
        encoding="utf-8",
    )
    (repo / "App.java").write_text(
        "package demo;\n\npublic class App {\n  void run() {}\n}\ninterface Runner {}\n",
        encoding="utf-8",
    )

    graph = build_codegraph(repo)

    assert graph.symbols_by_name["RunServer"] == ["main.go"]
    assert graph.symbols_by_name["Config"] == ["main.go"]
    assert graph.symbols_by_name["parse_input"] == ["lib.rs"]
    assert graph.symbols_by_name["Parser"] == ["lib.rs"]
    assert graph.symbols_by_name["Visitor"] == ["lib.rs"]
    assert graph.symbols_by_name["Mode"] == ["lib.rs"]
    assert graph.symbols_by_name["App"] == ["App.java"]
    assert graph.symbols_by_name["Runner"] == ["App.java"]

    # Kinds: functions map to "func", type-like decls map to "class".
    go_kinds = {(s.name, s.kind) for s in graph.nodes["main.go"].symbols}
    assert ("RunServer", "func") in go_kinds
    assert ("Config", "class") in go_kinds


@pytestmark_ts
def test_treesitter_python_path_unchanged_when_present(sample_repo: Path) -> None:
    # Even with tree-sitter installed, the Python indexing is byte-for-byte the
    # same as before (the sample repo has only *.py source).
    graph = build_codegraph(sample_repo)
    assert graph.symbols_by_name["invalidate_cache"] == ["src/cache.py"]
    assert graph.nodes["src/worker.py"].imports == ["src/cache.py"]
    assert graph.dependents["src/cache.py"] == ["src/worker.py", "tests/test_cache.py"]


@pytestmark_ts
def test_treesitter_malformed_file_yields_empty_symbols(tmp_path: Path) -> None:
    pytest.importorskip("tree_sitter_language_pack")
    repo = tmp_path / "broken"
    repo.mkdir()
    # Garbage TS — tree-sitter recovers, we must never raise.
    (repo / "broken.ts").write_text("function (((( ;;; \n", encoding="utf-8")
    (repo / "ok.ts").write_text("export function good() {}\n", encoding="utf-8")

    graph = build_codegraph(repo)
    assert "broken.ts" in graph.nodes  # discovered, just no clean symbols
    assert graph.symbols_by_name.get("good") == ["ok.ts"]
