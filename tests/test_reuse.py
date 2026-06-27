"""Tests for the reuse radar — surfacing existing code to avoid reimplementation.

Covers the deterministic ``find_reuse`` indexer/ranker and the ``onmc reuse``
CLI command (table + ``--json`` shapes).  Entirely offline — no LLM, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.reuse.radar import ReuseHit, find_reuse


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _build_reuse_repo(root: Path) -> None:
    """Write a small repo with known symbols, plus skip-dir noise."""
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "text.py").write_text(
        '''from __future__ import annotations


def tokenize(text: str) -> list[str]:
    """Split text into lowercased word tokens for matching."""
    return text.lower().split()


def slugify(value: str) -> str:
    """Turn a value into a url-safe slug."""
    return value.replace(" ", "-")
''',
        encoding="utf-8",
    )
    (pkg / "store.py").write_text(
        '''from __future__ import annotations


class CacheStore:
    """Hold cached invalidation rules for worker jobs."""

    def get(self, key: str) -> str:
        return key
''',
        encoding="utf-8",
    )
    # Private symbol — must be skipped.
    (pkg / "internal.py").write_text(
        '''def _private_helper(x: int) -> int:
    """An internal helper nobody should reuse."""
    return x
''',
        encoding="utf-8",
    )
    # A skipped directory with a tempting symbol that must never surface.
    venv = root / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "vendored.py").write_text(
        '''def tokenize(text: str) -> list[str]:
    """Vendored tokenize that should be skipped."""
    return [text]
''',
        encoding="utf-8",
    )
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_thing.py").write_text(
        '''def test_tokenize() -> None:
    """A test function that should be skipped."""
    assert True
''',
        encoding="utf-8",
    )
    # An unparseable file — must not break the scan.
    (pkg / "broken.py").write_text("def oops( :\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# find_reuse — core behaviour
# ---------------------------------------------------------------------------


def test_query_matching_function_name_ranks_first(tmp_path: Path) -> None:
    """A query naming an existing function returns it ranked first."""
    _build_reuse_repo(tmp_path)
    hits = find_reuse(tmp_path, "tokenize")
    assert hits, "expected at least one hit"
    assert hits[0].symbol == "tokenize"
    assert hits[0].kind == "function"
    # The vendored copy under .venv/ and the test fn must not appear.
    files = {hit.file for hit in hits}
    assert all(".venv" not in f for f in files)
    assert all("tests/" not in f for f in files)


def test_docstring_match_surfaces_symbol(tmp_path: Path) -> None:
    """A query matching a docstring (not the name) still finds the symbol."""
    _build_reuse_repo(tmp_path)
    hits = find_reuse(tmp_path, "invalidation rules worker jobs")
    symbols = {hit.symbol for hit in hits}
    assert "CacheStore" in symbols
    cache_hit = next(hit for hit in hits if hit.symbol == "CacheStore")
    assert cache_hit.kind == "class"


def test_signature_and_doc_excerpt_captured(tmp_path: Path) -> None:
    """Hits capture a signature with arg names and the first docstring line."""
    _build_reuse_repo(tmp_path)
    hits = find_reuse(tmp_path, "tokenize")
    hit = hits[0]
    assert hit.signature == "tokenize(text)"
    assert hit.doc_excerpt == "Split text into lowercased word tokens for matching."
    assert hit.file == "pkg/text.py"
    assert hit.lineno > 0


def test_unrelated_query_returns_empty(tmp_path: Path) -> None:
    """A query with no token overlap returns no hits."""
    _build_reuse_repo(tmp_path)
    hits = find_reuse(tmp_path, "kubernetes ingress gateway routing")
    assert hits == []


def test_private_symbols_skipped(tmp_path: Path) -> None:
    """Private/underscore-prefixed symbols are never returned."""
    _build_reuse_repo(tmp_path)
    hits = find_reuse(tmp_path, "helper internal")
    assert all(not hit.symbol.startswith("_") for hit in hits)


def test_deterministic_across_runs(tmp_path: Path) -> None:
    """Two runs with the same query produce identical ordered output."""
    _build_reuse_repo(tmp_path)
    first = find_reuse(tmp_path, "text token slug value")
    second = find_reuse(tmp_path, "text token slug value")
    assert first == second
    # Ordering is stable: scores are non-increasing.
    scores = [hit.score for hit in first]
    assert scores == sorted(scores, reverse=True)


def test_limit_respected(tmp_path: Path) -> None:
    """The limit bounds the number of returned hits."""
    _build_reuse_repo(tmp_path)
    hits = find_reuse(tmp_path, "text token slug value worker cache", limit=1)
    assert len(hits) <= 1


def test_empty_repo_graceful(tmp_path: Path) -> None:
    """An empty repo (no indexable code) returns an empty list, not an error."""
    empty = tmp_path / "empty"
    empty.mkdir()
    assert find_reuse(empty, "anything") == []


def test_missing_directory_graceful(tmp_path: Path) -> None:
    """A non-existent directory returns an empty list without raising."""
    assert find_reuse(tmp_path / "does-not-exist", "tokenize") == []


def test_blank_query_returns_empty(tmp_path: Path) -> None:
    """A blank query short-circuits to an empty result."""
    _build_reuse_repo(tmp_path)
    assert find_reuse(tmp_path, "   ") == []


def test_returns_reuse_hit_instances(tmp_path: Path) -> None:
    """Results are ``ReuseHit`` dataclass instances with the documented fields."""
    _build_reuse_repo(tmp_path)
    hits = find_reuse(tmp_path, "slug")
    assert hits
    assert all(isinstance(hit, ReuseHit) for hit in hits)


# ---------------------------------------------------------------------------
# CLI — onmc reuse
# ---------------------------------------------------------------------------


def test_cli_reuse_table(tmp_path: Path, monkeypatch) -> None:
    """`onmc reuse <query>` exits 0 and names the matched symbol."""
    _build_reuse_repo(tmp_path)
    # Make it a git repo so repo discovery succeeds.
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    result = _cli_runner().invoke(app, ["reuse", "tokenize"])
    assert result.exit_code == 0, result.stdout
    assert "tokenize" in result.stdout


def test_cli_reuse_json_shape(tmp_path: Path, monkeypatch) -> None:
    """`onmc reuse <query> --json` emits a list of hit objects."""
    _build_reuse_repo(tmp_path)
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    result = _cli_runner().invoke(app, ["reuse", "tokenize", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert payload, "expected at least one hit in JSON"
    first = payload[0]
    assert set(first) == {
        "symbol",
        "kind",
        "file",
        "lineno",
        "signature",
        "doc_excerpt",
        "score",
    }
    assert first["symbol"] == "tokenize"


def test_cli_reuse_json_empty_on_no_match(tmp_path: Path, monkeypatch) -> None:
    """`--json` emits an empty list when nothing matches."""
    _build_reuse_repo(tmp_path)
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    result = _cli_runner().invoke(app, ["reuse", "kubernetes ingress routing", "--json"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout) == []
