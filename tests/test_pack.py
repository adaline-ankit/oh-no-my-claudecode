"""Tests for the ``pack`` feature — per-task context pack.

Covers the auto-discovery ``onmc pack`` command and the underlying
:func:`oh_no_my_claudecode.pack.builder.build_pack`:

- a seeded dead-end, decision, reuse symbol and context file all surface;
- a fresh (empty) brain yields a valid, non-crashing empty pack;
- the rendered markdown is bounded by the budget;
- the ``--json`` CLI surface is parseable;
- output is deterministic across repeated builds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode import init
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.models import MemoryKind, SourceType
from oh_no_my_claudecode.models.memory import MemoryEntry
from oh_no_my_claudecode.pack.builder import build_pack, render_pack_markdown
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now

runner = CliRunner()


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def _seed_memory(
    storage: SQLiteStorage,
    *,
    kind: MemoryKind,
    title: str,
    summary: str,
    details: str,
) -> str:
    now = utc_now()
    entry = MemoryEntry(
        id=stable_id(kind.value, title, summary, "test:seed", prefix="test"),
        kind=kind,
        title=title,
        summary=summary,
        details=details,
        source_type=SourceType.MANUAL,
        source_ref="test:seed",
        tags=[kind.value],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return entry.id


def _storage(sample_repo: Path) -> SQLiteStorage:
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()
    return storage


# ---------------------------------------------------------------------------
# build_pack: content surfacing
# ---------------------------------------------------------------------------


def test_build_pack_surfaces_all_sources(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    _seed_memory(
        storage,
        kind=MemoryKind.FAILED_APPROACH,
        title="Bypass cache via direct Redis writes",
        summary="Tried writing cache invalidation keys directly to Redis.",
        details="Bypassing the cache module broke invalidation consistency.",
    )
    _seed_memory(
        storage,
        kind=MemoryKind.DECISION,
        title="Cache invalidation goes through the cache module",
        summary="All cache invalidation must flow through invalidate_cache.",
        details="Keeps the invalidation boundary single-sourced.",
    )

    pack = build_pack(storage, sample_repo, "fix cache invalidation bug")

    # dead-end surfaced
    assert any("bypass" in d.title.lower() for d in pack.dead_ends)
    # decision surfaced (and only decision-kind memories)
    assert any("invalidation" in d.title.lower() for d in pack.decisions)
    # reuse hint surfaced from the sample repo's cache symbol
    assert any("cache" in h.symbol.lower() for h in pack.reuse_hints)
    # context file surfaced
    assert any("cache" in path.lower() for path in pack.context_files)

    markdown = render_pack_markdown(pack)
    assert "# Context Pack" in markdown
    assert "Dead ends" in markdown
    assert "Decisions" in markdown


def test_build_pack_decisions_exclude_non_decision_kinds(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    _seed_memory(
        storage,
        kind=MemoryKind.GOTCHA,
        title="Cache gotcha not a decision",
        summary="A cache gotcha that should not appear under decisions.",
        details="Some gotcha about cache.",
    )

    pack = build_pack(storage, sample_repo, "cache gotcha")
    assert all("gotcha" not in d.title.lower() for d in pack.decisions)


# ---------------------------------------------------------------------------
# build_pack: empty brain / graceful degradation
# ---------------------------------------------------------------------------


def test_build_pack_empty_brain_does_not_crash(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)  # nothing seeded beyond ambient ingest

    # No dead-ends were seeded, so that section is genuinely empty.
    pack = build_pack(storage, sample_repo, "fix cache invalidation bug")

    assert pack.dead_ends == []
    markdown = render_pack_markdown(pack)
    assert "# Context Pack" in markdown
    assert "_(none recorded)_" in markdown  # the empty dead-ends section renders
    assert markdown.endswith("\n")


def test_build_pack_unknown_goal_yields_empty_sections(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    # A goal with no token overlap with the repo or brain → empty everything.
    pack = build_pack(storage, sample_repo, "zzqq nonexistent quantum widget")

    assert pack.dead_ends == []
    assert pack.decisions == []
    assert pack.reuse_hints == []
    assert pack.context_files == []
    assert pack.is_empty
    markdown = render_pack_markdown(pack)
    assert markdown.count("_(none") + markdown.count("_(no candidates)_") >= 4


# ---------------------------------------------------------------------------
# Budget bounds
# ---------------------------------------------------------------------------


def test_build_pack_respects_budget(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    pack = build_pack(storage, sample_repo, "cache invalidation worker", budget=500)
    markdown = render_pack_markdown(pack)
    assert len(markdown) <= 500


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_build_pack_is_deterministic(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    first = render_pack_markdown(build_pack(storage, sample_repo, "cache worker tests"))
    second = render_pack_markdown(build_pack(storage, sample_repo, "cache worker tests"))
    assert first == second


# ---------------------------------------------------------------------------
# CLI surface (auto-discovered command)
# ---------------------------------------------------------------------------


def test_pack_cli_json(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_repo)
    _storage(sample_repo)

    result = runner.invoke(app, ["pack", "fix cache invalidation", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["goal"] == "fix cache invalidation"
    assert "markdown" in payload
    assert "dead_ends" in payload


def test_pack_cli_markdown(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_repo)
    _storage(sample_repo)

    result = runner.invoke(app, ["pack", "fix cache invalidation", "--budget", "1500"])
    assert result.exit_code == 0, result.stdout
    assert "# Context Pack" in result.stdout
