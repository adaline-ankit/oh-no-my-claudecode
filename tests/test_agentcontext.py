"""Tests for ``onmc context`` — codegraph blast radius + relevant memory for a file.

Coverage (≥6 deterministic offline tests as required)
------------------------------------------------------
1. build_context() assembles blast radius fields from a fake Neighbors.
2. build_context() assembles memory hits from fake MemoryEntry list.
3. File not in graph sets in_graph=False with empty dependents/imports/tests.
4. --limit cap: only first N memory entries are surfaced.
5. to_dict() produces the correct --json wire shape.
6. build_context() with no memory entries returns empty memory list.
7. CLI --json on a real (tiny) repo builds the graph and returns valid JSON.
8. CLI file-not-in-graph path still exits 0 and sets in_graph=False in JSON.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from oh_no_my_claudecode.agentcontext.build import build_context
from oh_no_my_claudecode.codegraph.models import Neighbors
from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind, SourceType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:
    runner = CliRunner()

_NOW = datetime(2025, 1, 1, tzinfo=UTC)


def _fake_entry(
    *,
    id: str = "mem_001",
    kind: MemoryKind = MemoryKind.GOTCHA,
    title: str = "Test memory",
    summary: str = "A gotcha in the code",
    source_ref: str = "src/cache.py",
) -> MemoryEntry:
    return MemoryEntry(
        id=id,
        kind=kind,
        title=title,
        summary=summary,
        details="",
        source_type=SourceType.MANUAL,
        source_ref=source_ref,
        tags=[],
        confidence=0.9,
        feedback_score=0.0,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _fake_neighbors(
    target: str = "src/cache.py",
    *,
    target_files: list[str] | None = None,
    dependents: list[str] | None = None,
    imports: list[str] | None = None,
    tests: list[str] | None = None,
) -> Neighbors:
    return Neighbors(
        target=target,
        target_files=target_files if target_files is not None else [target],
        dependents=dependents or [],
        imports=imports or [],
        tests=tests or [],
    )


# ---------------------------------------------------------------------------
# Test 1: build_context() assembles blast radius from Neighbors
# ---------------------------------------------------------------------------


def test_build_context_blast_radius_fields() -> None:
    nbrs = _fake_neighbors(
        target="src/cache.py",
        dependents=["src/worker.py"],
        imports=["src/utils.py"],
        tests=["tests/test_cache.py"],
    )
    ctx = build_context("src/cache.py", nbrs, [])

    assert ctx.kind == "context"
    assert ctx.file == "src/cache.py"
    assert ctx.blast_radius.target == "src/cache.py"
    assert ctx.blast_radius.target_files == ["src/cache.py"]
    assert ctx.blast_radius.dependents == ["src/worker.py"]
    assert ctx.blast_radius.imports == ["src/utils.py"]
    assert ctx.blast_radius.tests == ["tests/test_cache.py"]
    assert ctx.blast_radius.in_graph is True


# ---------------------------------------------------------------------------
# Test 2: build_context() assembles MemoryHit list from MemoryEntry list
# ---------------------------------------------------------------------------


def test_build_context_memory_hits_assembled() -> None:
    entries = [
        _fake_entry(id="mem_001", title="Cache gotcha", kind=MemoryKind.GOTCHA),
        _fake_entry(id="mem_002", title="Cache decision", kind=MemoryKind.DECISION),
    ]
    ctx = build_context("src/cache.py", _fake_neighbors(), entries)

    assert len(ctx.memory) == 2  # noqa: PLR2004
    assert ctx.memory[0].id == "mem_001"
    assert ctx.memory[0].title == "Cache gotcha"
    assert ctx.memory[0].kind == "gotcha"
    assert ctx.memory[1].id == "mem_002"
    assert ctx.memory[1].kind == "decision"


# ---------------------------------------------------------------------------
# Test 3: file not in graph → in_graph=False, empty lists
# ---------------------------------------------------------------------------


def test_build_context_file_not_in_graph() -> None:
    nbrs = Neighbors(target="src/missing.py")  # target_files is empty by default

    ctx = build_context("src/missing.py", nbrs, [])

    assert ctx.blast_radius.in_graph is False
    assert ctx.blast_radius.target_files == []
    assert ctx.blast_radius.dependents == []
    assert ctx.blast_radius.imports == []
    assert ctx.blast_radius.tests == []


# ---------------------------------------------------------------------------
# Test 4: --limit caps memory entries
# ---------------------------------------------------------------------------


def test_build_context_limit_caps_memory() -> None:
    entries = [_fake_entry(id=f"mem_{i:03d}", title=f"Memory {i}") for i in range(10)]

    ctx = build_context("src/cache.py", _fake_neighbors(), entries, limit=3)

    assert len(ctx.memory) == 3  # noqa: PLR2004
    assert ctx.memory[0].id == "mem_000"
    assert ctx.memory[2].id == "mem_002"


# ---------------------------------------------------------------------------
# Test 5: to_dict() produces the correct --json wire shape
# ---------------------------------------------------------------------------


def test_agent_context_to_dict_wire_shape() -> None:
    nbrs = _fake_neighbors(
        target="src/cache.py",
        dependents=["src/worker.py"],
        imports=[],
        tests=["tests/test_cache.py"],
    )
    entries = [_fake_entry(id="mem_001", title="A gotcha", source_ref="src/cache.py")]
    ctx = build_context("src/cache.py", nbrs, entries)

    d = ctx.to_dict()
    assert d["kind"] == "context"
    assert d["file"] == "src/cache.py"

    br = d["blast_radius"]
    assert isinstance(br, dict)
    assert br["target"] == "src/cache.py"
    assert br["dependents"] == ["src/worker.py"]
    assert br["imports"] == []
    assert br["tests"] == ["tests/test_cache.py"]
    assert br["in_graph"] is True

    mem = d["memory"]
    assert isinstance(mem, list)
    assert len(mem) == 1
    assert mem[0]["id"] == "mem_001"
    assert mem[0]["kind"] == "gotcha"
    assert mem[0]["title"] == "A gotcha"
    assert mem[0]["source_ref"] == "src/cache.py"


# ---------------------------------------------------------------------------
# Test 6: empty memory list returns AgentContext with empty memory
# ---------------------------------------------------------------------------


def test_build_context_no_memory_entries() -> None:
    ctx = build_context("src/cache.py", _fake_neighbors(), [])

    assert ctx.memory == []
    assert ctx.blast_radius.in_graph is True


# ---------------------------------------------------------------------------
# Helpers for CLI tests — build a tiny real repo
# ---------------------------------------------------------------------------


def _build_tiny_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with two Python files + a test."""
    repo = tmp_path / "tiny-repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=repo, check=True, capture_output=True
    )

    (repo / "src").mkdir()
    (repo / "tests").mkdir()

    (repo / "src" / "cache.py").write_text("def invalidate():\n    pass\n", encoding="utf-8")
    (repo / "src" / "worker.py").write_text(
        "from src.cache import invalidate\ndef run(): invalidate()\n", encoding="utf-8"
    )
    (repo / "tests" / "test_cache.py").write_text(
        "from src.cache import invalidate\ndef test_it(): assert True\n", encoding="utf-8"
    )

    # Initialise onmc store via write_config (needs the correct YAML schema).
    from oh_no_my_claudecode.config import ProjectConfig, write_config  # noqa: PLC0415

    cfg = ProjectConfig(repo_root=str(repo))
    write_config(cfg, repo)

    subprocess.run(
        ["git", "add", "."], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init", "--allow-empty"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    return repo


# ---------------------------------------------------------------------------
# Test 7: CLI --json on a real tiny repo — valid JSON, correct shape
# ---------------------------------------------------------------------------


def test_cli_json_on_real_repo(tmp_path: Path, monkeypatch: Any) -> None:
    from oh_no_my_claudecode.cli import app  # noqa: PLC0415

    monkeypatch.chdir(_build_tiny_repo(tmp_path))
    result = runner.invoke(app, ["context", "src/cache.py", "--json"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    data: dict[str, Any] = json.loads(result.output)
    assert data["kind"] == "context"
    assert "blast_radius" in data
    assert "memory" in data
    assert isinstance(data["memory"], list)
    br = data["blast_radius"]
    # The codegraph is built on demand; src/cache.py exists so in_graph=True.
    assert br["in_graph"] is True
    assert isinstance(br["dependents"], list)
    assert isinstance(br["imports"], list)
    assert isinstance(br["tests"], list)


# ---------------------------------------------------------------------------
# Test 8: CLI --json for a file not in the graph — exits 0, in_graph False
# ---------------------------------------------------------------------------


def test_cli_json_file_not_in_graph(tmp_path: Path, monkeypatch: Any) -> None:
    from oh_no_my_claudecode.cli import app  # noqa: PLC0415

    monkeypatch.chdir(_build_tiny_repo(tmp_path))
    result = runner.invoke(
        app,
        ["context", "src/totally_nonexistent.py", "--json"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    data: dict[str, Any] = json.loads(result.output)
    assert data["kind"] == "context"
    assert data["blast_radius"]["in_graph"] is False
    assert data["blast_radius"]["dependents"] == []
    assert data["blast_radius"]["imports"] == []
    assert data["blast_radius"]["tests"] == []
