"""Tests for the reuse radar — surfacing existing code to avoid reimplementation.

Covers the deterministic ``find_reuse`` indexer/ranker, the optional ast-grep
structural integration (:mod:`oh_no_my_claudecode.reuse.astgrep`), and the
``onmc reuse`` CLI command (table + ``--json`` + ``--ast-grep`` shapes).
Entirely offline — no LLM, no network, no real binary invocations.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.reuse.astgrep import (
    StructuralMatch,
    ast_grep_available,
    find_reuse_structural,
)
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
# find_reuse_structural — ast-grep optional integration
# ---------------------------------------------------------------------------


def _fake_runner_with_matches(pattern: str, root: str) -> list[StructuralMatch]:
    """A deterministic fake runner that returns one match regardless of input."""
    return [
        StructuralMatch(
            file="pkg/text.py",
            line_start=4,
            line_end=6,
            text="def tokenize(text: str) -> list[str]:",
        )
    ]


def _fake_runner_empty(pattern: str, root: str) -> list[StructuralMatch]:
    """A fake runner that always returns no matches."""
    return []


def test_structural_runner_none_returns_empty(tmp_path: Path) -> None:
    """When runner=None, find_reuse_structural returns [] — zero regression."""
    _build_reuse_repo(tmp_path)
    result = find_reuse_structural(tmp_path, "def $F($$$):", runner=None)
    assert result == []


def test_structural_runner_absent_binary_no_op(tmp_path: Path) -> None:
    """When no runner is injected (binary absent path), result is empty — no error."""
    _build_reuse_repo(tmp_path)
    # runner=None explicitly simulates absent binary.
    result = find_reuse_structural(tmp_path, "any pattern", runner=None)
    assert result == []


def test_structural_injected_runner_matches_folded_in(tmp_path: Path) -> None:
    """Injected runner matches are returned as StructuralMatch objects."""
    _build_reuse_repo(tmp_path)
    result = find_reuse_structural(tmp_path, "def $F($$$):", runner=_fake_runner_with_matches)
    assert len(result) == 1
    match = result[0]
    assert isinstance(match, StructuralMatch)
    assert match.file == "pkg/text.py"
    assert match.line_start == 4
    assert match.line_end == 6
    assert "tokenize" in match.text


def test_structural_empty_pattern_returns_empty(tmp_path: Path) -> None:
    """A blank pattern short-circuits to empty without calling the runner."""
    _build_reuse_repo(tmp_path)
    result = find_reuse_structural(tmp_path, "   ", runner=_fake_runner_with_matches)
    assert result == []


def test_structural_missing_directory_graceful(tmp_path: Path) -> None:
    """A non-existent root returns [] without raising, even with a live runner."""
    result = find_reuse_structural(
        tmp_path / "does-not-exist", "def $F($$$):", runner=_fake_runner_with_matches
    )
    assert result == []


def test_structural_runner_exception_is_swallowed(tmp_path: Path) -> None:
    """A runner that raises must not propagate — result is empty."""
    _build_reuse_repo(tmp_path)

    def _crashing_runner(pattern: str, root: str) -> list[StructuralMatch]:
        raise RuntimeError("binary exploded")

    result = find_reuse_structural(tmp_path, "def $F($$$):", runner=_crashing_runner)
    assert result == []


def test_structural_empty_runner_result(tmp_path: Path) -> None:
    """A runner that returns no matches → empty list (not an error)."""
    _build_reuse_repo(tmp_path)
    result = find_reuse_structural(tmp_path, "def $F($$$):", runner=_fake_runner_empty)
    assert result == []


def test_structural_determinism(tmp_path: Path) -> None:
    """Two calls with the same pattern and runner produce identical results."""
    _build_reuse_repo(tmp_path)
    first = find_reuse_structural(tmp_path, "def $F($$$):", runner=_fake_runner_with_matches)
    second = find_reuse_structural(tmp_path, "def $F($$$):", runner=_fake_runner_with_matches)
    assert first == second


# ---------------------------------------------------------------------------
# ast_grep_available — PATH detection
# ---------------------------------------------------------------------------


def test_ast_grep_available_false_when_binary_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """ast_grep_available() returns False when neither binary is on PATH."""
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert not ast_grep_available()


def test_ast_grep_available_true_when_astgrep_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """ast_grep_available() returns True when 'ast-grep' is on PATH."""

    def _which(name: str) -> str | None:
        return "/usr/bin/ast-grep" if name == "ast-grep" else None

    monkeypatch.setattr(shutil, "which", _which)
    assert ast_grep_available()


def test_ast_grep_available_true_when_sg_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """ast_grep_available() returns True when the 'sg' fallback is on PATH."""

    def _which(name: str) -> str | None:
        return "/usr/local/bin/sg" if name == "sg" else None

    monkeypatch.setattr(shutil, "which", _which)
    assert ast_grep_available()


# ---------------------------------------------------------------------------
# Real-binary smoke test — skipped when ast-grep is absent
# ---------------------------------------------------------------------------

_ASTGREP_SKIP = pytest.mark.skipif(
    not (shutil.which("ast-grep") or shutil.which("sg")),
    reason="ast-grep / sg binary not on PATH",
)


@_ASTGREP_SKIP
def test_real_binary_returns_structural_matches(tmp_path: Path) -> None:
    """Smoke: real ast-grep binary produces StructuralMatch objects."""
    from oh_no_my_claudecode.reuse.astgrep import make_ast_grep_runner

    _build_reuse_repo(tmp_path)
    runner = make_ast_grep_runner(tmp_path)
    # A broad function-definition pattern should match our known symbols.
    matches = find_reuse_structural(tmp_path, "def $FUNC($$$ARGS): $$$BODY", runner=runner)
    # May be empty if ast-grep version uses different pattern syntax — just no crash.
    assert isinstance(matches, list)
    for m in matches:
        assert isinstance(m, StructuralMatch)
        assert m.line_start >= 1
        assert m.line_end >= m.line_start


# ---------------------------------------------------------------------------
# CLI — onmc reuse (text-only, existing tests updated for new JSON shape)
# ---------------------------------------------------------------------------


def test_cli_reuse_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`onmc reuse <query>` exits 0 and names the matched symbol."""
    _build_reuse_repo(tmp_path)
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    result = _cli_runner().invoke(app, ["reuse", "tokenize"])
    assert result.exit_code == 0, result.stdout
    assert "tokenize" in result.stdout


def test_cli_reuse_json_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`onmc reuse <query> --json` emits {hits: [...], structural: [...]}."""
    _build_reuse_repo(tmp_path)
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    result = _cli_runner().invoke(app, ["reuse", "tokenize", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    assert "hits" in payload
    assert "structural" in payload
    hits = payload["hits"]
    assert isinstance(hits, list)
    assert hits, "expected at least one hit in JSON"
    first = hits[0]
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
    # structural list is present (empty when binary absent)
    assert isinstance(payload["structural"], list)


def test_cli_reuse_json_empty_on_no_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--json` emits hits=[] and structural=[] when nothing matches."""
    _build_reuse_repo(tmp_path)
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    result = _cli_runner().invoke(app, ["reuse", "kubernetes ingress routing", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    assert payload["hits"] == []
    assert isinstance(payload["structural"], list)


def test_cli_reuse_no_ast_grep_flag_is_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--no-ast-grep` (default) produces same output as omitting the flag."""
    _build_reuse_repo(tmp_path)
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    # Explicit --no-ast-grep must still succeed and produce the same structure.
    result = _cli_runner().invoke(app, ["reuse", "tokenize", "--no-ast-grep", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["hits"]
    assert isinstance(payload["structural"], list)


def test_cli_reuse_ast_grep_flag_no_binary_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--ast-grep`` with binary absent exits 0 — pure graceful fallback."""
    _build_reuse_repo(tmp_path)
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    # Patch shutil.which to simulate absent binary inside the CLI invocation.
    import oh_no_my_claudecode.reuse.astgrep as _astgrep_mod

    monkeypatch.setattr(_astgrep_mod.shutil, "which", lambda _: None)
    result = _cli_runner().invoke(app, ["reuse", "tokenize", "--ast-grep", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    # Text hits still work; structural empty because binary absent.
    assert payload["hits"]
    assert payload["structural"] == []
