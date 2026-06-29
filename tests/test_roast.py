"""Tests for the ``onmc roast`` agent-readiness score.

Covers:
- the score is computed deterministically on a seeded repo + brain
- a repo with uncovered hotspots scores lower AND emits a finding
- a clean, well-covered repo scores high
- an empty store is graceful (no div-by-zero, valid score)
- the --json shape matches RoastReport.to_dict()
- weights sum to 100 (documented model invariant)

Never asserts against Rich/`--help` output.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.conventions.detector import conventions_path
from oh_no_my_claudecode.models import FileStat, MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.roast.scorer import (
    BRAIN_FULL,
    W_AUDIT,
    W_BRAIN,
    W_CONVENTIONS,
    W_HOTSPOT,
    compute_roast,
)
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory(*, idx: int, source_ref: str) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=f"mem-{idx}",
        kind=MemoryKind.DOC_FACT,
        title=f"Memory {idx}",
        summary=f"Summary for memory {idx}",
        details=f"Details for memory {idx}",
        source_type=SourceType.DOC,
        source_ref=source_ref,
        tags=[],
        confidence=0.8,
        created_at=now,
        updated_at=now,
    )


def _make_stat(path: str, *, churn: int = 5, recent: int = 2) -> FileStat:
    return FileStat(
        path=path,
        change_count=churn,
        recent_change_count=recent,
        last_modified_at=None,
        is_test=False,
        top_level_dir=path.split("/")[0] if "/" in path else ".",
    )


def _seed_storage(
    tmp_path: Path,
    *,
    file_stats: list[FileStat],
    memories: list[MemoryEntry],
) -> SQLiteStorage:
    db = SQLiteStorage(tmp_path / "mem.db")
    db.initialize()
    db.replace_file_stats(file_stats)
    if memories:
        db.upsert_memories(memories)
    return db


def _add_conventions(repo_root: Path) -> None:
    path = conventions_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# conventions\n")


# ---------------------------------------------------------------------------
# Documented-model invariant
# ---------------------------------------------------------------------------


def test_weights_sum_to_100() -> None:
    """The documented weighted blend must total 100 points."""
    assert W_HOTSPOT + W_AUDIT + W_BRAIN + W_CONVENTIONS == 100


# ---------------------------------------------------------------------------
# compute_roast — pure & deterministic
# ---------------------------------------------------------------------------


def test_roast_deterministic_on_seeded_repo(tmp_path: Path) -> None:
    """Same seeded repo + brain → identical report across runs."""
    stats = [_make_stat("src/cache.py", churn=10), _make_stat("src/worker.py", churn=8)]
    memories = [
        _make_memory(idx=1, source_ref="src/cache.py"),
        _make_memory(idx=2, source_ref="src/worker.py"),
    ]
    db = _seed_storage(tmp_path, file_stats=stats, memories=memories)

    first = compute_roast(db, tmp_path)
    second = compute_roast(db, tmp_path)
    assert first.to_dict() == second.to_dict()
    assert 0 <= first.score <= 100


def test_clean_repo_scores_high(tmp_path: Path) -> None:
    """Fully-covered hotspots + healthy brain + conventions + clean audit → high score."""
    stats = [_make_stat("src/cache.py", churn=10), _make_stat("src/worker.py", churn=8)]
    memories = [
        _make_memory(idx=i, source_ref=ref)
        for i, ref in enumerate(
            ["src/cache.py", "src/worker.py"] + [f"src/other{n}.py" for n in range(BRAIN_FULL)]
        )
    ]
    db = _seed_storage(tmp_path, file_stats=stats, memories=memories)
    _add_conventions(tmp_path)

    report = compute_roast(db, tmp_path)
    assert report.score >= 90
    assert report.grade == "A"
    assert report.findings == []
    assert report.uncovered_hotspots == 0


def test_uncovered_hotspots_score_lower_and_emit_finding(tmp_path: Path) -> None:
    """A repo with uncovered hotspots scores lower than a covered one + names them."""
    stats = [
        _make_stat("src/cache.py", churn=20, recent=5),
        _make_stat("src/worker.py", churn=15, recent=3),
    ]
    # Same stats, two brains: one covers the hotspots, one does not.
    covered_db = _seed_storage(
        tmp_path / "a",
        file_stats=stats,
        memories=[
            _make_memory(idx=1, source_ref="src/cache.py"),
            _make_memory(idx=2, source_ref="src/worker.py"),
        ],
    )
    uncovered_db = _seed_storage(tmp_path / "b", file_stats=stats, memories=[])
    (tmp_path / "a").mkdir(exist_ok=True)
    (tmp_path / "b").mkdir(exist_ok=True)

    covered = compute_roast(covered_db, tmp_path / "a")
    uncovered = compute_roast(uncovered_db, tmp_path / "b")

    assert uncovered.score < covered.score
    assert uncovered.uncovered_hotspots == 2
    assert any("hotspot" in f.lower() and "zero memory" in f.lower() for f in uncovered.findings)
    # The finding must name the actual offending files.
    assert any("src/cache.py" in f for f in uncovered.findings)


def test_empty_store_is_graceful(tmp_path: Path) -> None:
    """No file stats and no memories → valid score, no div-by-zero, emits findings."""
    db = SQLiteStorage(tmp_path / "mem.db")
    db.initialize()

    report = compute_roast(db, tmp_path)
    assert 0 <= report.score <= 100
    assert report.memory_count == 0
    assert report.uncovered_hotspots == 0
    # Empty brain + missing conventions must both be flagged.
    assert any("EMPTY" in f or "empty" in f for f in report.findings)
    assert any("conventions" in f.lower() for f in report.findings)


def test_empty_brain_finding_present(tmp_path: Path) -> None:
    """A repo with hotspots but zero memory flags the empty brain explicitly."""
    stats = [_make_stat("src/cache.py", churn=10)]
    db = _seed_storage(tmp_path, file_stats=stats, memories=[])
    report = compute_roast(db, tmp_path)
    assert report.memory_count == 0
    assert any("brain is EMPTY" in f for f in report.findings)


# ---------------------------------------------------------------------------
# RoastReport shape
# ---------------------------------------------------------------------------


def test_to_dict_shape(tmp_path: Path) -> None:
    """to_dict exposes exactly the documented JSON keys with the right types."""
    db = SQLiteStorage(tmp_path / "mem.db")
    db.initialize()
    report = compute_roast(db, tmp_path)
    payload = report.to_dict()

    assert set(payload) == {
        "score",
        "grade",
        "findings",
        "memory_count",
        "uncovered_hotspots",
        "audit_grade",
        "quips",
    }
    assert isinstance(payload["score"], int)
    assert isinstance(payload["grade"], str)
    assert isinstance(payload["findings"], list)
    assert isinstance(payload["quips"], list)
    # Round-trips through json without error.
    assert json.loads(json.dumps(payload)) == payload


# ---------------------------------------------------------------------------
# CLI surface (auto-discovered) — never asserts on Rich/--help text
# ---------------------------------------------------------------------------


def test_cli_roast_json_in_initialized_repo(tmp_path: Path, monkeypatch) -> None:
    """`onmc roast --json` in an initialised repo emits a valid RoastReport dict."""
    from oh_no_my_claudecode.config import database_path, default_config, write_config
    from oh_no_my_claudecode.core.repo import discover_repo_root

    # Make tmp_path a git repo so discover_repo_root resolves it.
    (tmp_path / ".git").mkdir()
    config = default_config(tmp_path)
    write_config(config, tmp_path)
    repo_root = discover_repo_root(tmp_path)
    db = SQLiteStorage(database_path(config, repo_root))
    db.initialize()

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["roast", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload["score"], int)
    assert 0 <= payload["score"] <= 100
    assert payload["grade"] in {"A", "B", "C", "D", "F"}


def test_roast_command_is_registered() -> None:
    """The roast command self-registered via auto-discovery (no cli.py edit)."""
    from oh_no_my_claudecode.command_registry import register_feature_commands

    register_feature_commands(app, strict=False)
    names = [c.name for c in app.registered_commands]
    assert "roast" in names
