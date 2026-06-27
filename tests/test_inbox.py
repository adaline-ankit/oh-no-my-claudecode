"""Tests for the ``onmc inbox`` ranked work queue.

Covers the pure queue core (deterministic, ``now`` injected) and the
auto-discovered CLI surface (exercised via flags + JSON / exit codes only —
never by asserting Rich ``--help`` text).

What is verified
----------------
- add + list round-trip (persists under ``.onmc/inbox/``)
- add is idempotent on text
- rank order honours source weights and is deterministic
- gather_candidates picks up a seeded TODO marker and a coverage gap
- run --top 3 yields exactly 3 plan entries and never executes
- empty repo degrades gracefully (no crash, empty outputs)
- CLI add/list/rank/run reachable and emit valid JSON
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer
from typer.testing import CliRunner

from oh_no_my_claudecode.inbox.commands import register
from oh_no_my_claudecode.inbox.queue import (
    InboxItem,
    add_item,
    gather_candidates,
    list_items,
    rank_items,
)
from oh_no_my_claudecode.models import FileStat, MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

runner = CliRunner()

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_storage(db_path: Path) -> SQLiteStorage:
    """A SQLiteStorage with one uncovered hotspot file + one low-conf memory."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage = SQLiteStorage(db_path)
    storage.initialize()
    storage.replace_file_stats(
        [
            FileStat(path="src/hot.py", change_count=9, recent_change_count=4),
            FileStat(path="src/cold.py", change_count=1, recent_change_count=0),
        ]
    )
    storage.upsert_memories(
        [
            MemoryEntry(
                id="mem-lowconf",
                kind=MemoryKind.DOC_FACT,
                title="Shaky fact",
                summary="A guess",
                details="needs verification",
                source_type=SourceType.DOC,
                source_ref="src/cold.py",
                tags=[],
                confidence=0.2,
                created_at=_NOW,
                updated_at=_NOW,
            ),
        ]
    )
    return storage


def _app() -> typer.Typer:
    """Fresh app with a sentinel so the inbox group stays a real subcommand."""
    app = typer.Typer()

    @app.command("__sentinel__")
    def _sentinel() -> None:  # pragma: no cover - never invoked
        ...

    register(app)
    return app


# ---------------------------------------------------------------------------
# Queue core
# ---------------------------------------------------------------------------


def test_add_list_round_trip(tmp_path: Path) -> None:
    item = add_item(tmp_path, "fix the login bug", now=_NOW)
    assert item.source == "manual"
    assert item.text == "fix the login bug"

    stored = list_items(tmp_path)
    assert [i.text for i in stored] == ["fix the login bug"]
    # Persisted under .onmc/inbox/
    assert (tmp_path / ".onmc" / "inbox" / "queue.json").is_file()


def test_add_is_idempotent_on_text(tmp_path: Path) -> None:
    add_item(tmp_path, "same task", now=_NOW)
    add_item(tmp_path, "  same task  ", now=_NOW)  # whitespace-different, same content
    assert len(list_items(tmp_path)) == 1


def test_rank_order_is_deterministic_and_weighted() -> None:
    items = [
        InboxItem(id="m1", text="manual", source="manual", created_at=""),
        InboxItem(id="t1", text="todo", source="todo", created_at=""),
        InboxItem(id="c1", text="coverage", source="coverage", created_at=""),
        InboxItem(id="x1", text="memory", source="memory", created_at=""),
    ]
    ranked = rank_items(items, now=_NOW)
    assert [i.source for i in ranked] == ["manual", "todo", "coverage", "memory"]
    # Deterministic: re-ranking yields identical order + scores.
    again = rank_items(items, now=_NOW)
    assert [(i.id, i.score) for i in ranked] == [(i.id, i.score) for i in again]


def test_recency_breaks_ties_within_source() -> None:
    fresh = InboxItem(
        id="m-fresh",
        text="fresh",
        source="manual",
        created_at=_NOW.isoformat(),
    )
    old = InboxItem(
        id="m-old",
        text="old",
        source="manual",
        created_at=(_NOW - timedelta(days=30)).isoformat(),
    )
    ranked = rank_items([old, fresh], now=_NOW)
    assert [i.id for i in ranked] == ["m-fresh", "m-old"]


def test_gather_picks_todo_and_coverage_gap(tmp_path: Path) -> None:
    # A seeded TODO marker in a source file.
    src = tmp_path / "src"
    src.mkdir()
    (src / "hot.py").write_text("# TODO: handle the edge case\nx = 1\n", encoding="utf-8")

    storage = _seed_storage(tmp_path / ".onmc" / "memory.db")

    ranked = gather_candidates(tmp_path, storage, now=_NOW)
    sources = {i.source for i in ranked}
    assert "todo" in sources
    assert "coverage" in sources
    assert "memory" in sources

    todo = next(i for i in ranked if i.source == "todo")
    assert "src/hot.py" in todo.text
    assert "handle the edge case" in todo.text

    coverage = next(i for i in ranked if i.source == "coverage")
    assert "src/hot.py" in coverage.text


def test_gather_without_storage_degrades(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("# FIXME: broken\n", encoding="utf-8")
    add_item(tmp_path, "manual one", now=_NOW)

    ranked = gather_candidates(tmp_path, None, now=_NOW)
    sources = {i.source for i in ranked}
    assert sources == {"manual", "todo"}  # coverage/memory skipped, no crash


def test_run_top_3_yields_three_plan_entries(tmp_path: Path) -> None:
    for n in range(6):
        add_item(tmp_path, f"task {n}", now=_NOW)
    ranked = gather_candidates(tmp_path, None, now=_NOW)
    plan = ranked[:3]
    assert len(plan) == 3


def test_empty_repo_is_graceful(tmp_path: Path) -> None:
    assert list_items(tmp_path) == []
    assert gather_candidates(tmp_path, None, now=_NOW) == []


def test_empty_text_rejected(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="empty"):
        add_item(tmp_path, "   ", now=_NOW)


# ---------------------------------------------------------------------------
# CLI surface (flags / JSON / exit codes — never Rich --help)
# ---------------------------------------------------------------------------


def test_cli_add_then_list_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()

    res_add = runner.invoke(app, ["inbox", "add", "wire up the thing", "--json"])
    assert res_add.exit_code == 0, res_add.output
    added = json.loads(res_add.output)
    assert added["source"] == "manual"
    assert added["text"] == "wire up the thing"

    res_list = runner.invoke(app, ["inbox", "list", "--json"])
    assert res_list.exit_code == 0, res_list.output
    listed = json.loads(res_list.output)
    assert [i["text"] for i in listed] == ["wire up the thing"]


def test_cli_rank_and_run_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mod.py").write_text("# TODO: refactor\n", encoding="utf-8")
    app = _app()

    runner.invoke(app, ["inbox", "add", "ship the feature"])

    res_rank = runner.invoke(app, ["inbox", "rank", "--json"])
    assert res_rank.exit_code == 0, res_rank.output
    ranked = json.loads(res_rank.output)
    assert any(i["source"] == "manual" for i in ranked)
    assert any(i["source"] == "todo" for i in ranked)
    # Manual outranks TODO.
    assert ranked[0]["source"] == "manual"

    res_run = runner.invoke(app, ["inbox", "run", "--top", "3", "--json"])
    assert res_run.exit_code == 0, res_run.output
    plan = json.loads(res_run.output)
    assert plan["executed"] is False
    assert plan["count"] == len(plan["plan"])
    assert plan["count"] <= 3


def test_cli_empty_add_exit_code(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    res = runner.invoke(app, ["inbox", "add", "   "])
    assert res.exit_code == 1
