"""Tests for the ``onmc blackboard`` shared-memory coordination board."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oh_no_my_claudecode.blackboard import (
    BoardEntry,
    InvalidEntryError,
    append_entry,
    filter_entries,
    read_board,
    render_board,
)
from oh_no_my_claudecode.blackboard.commands import _most_recent_swarm_id, _resolve_swarm_id


def _board_path(tmp_path: Path, swarm_id: str = "sw-1") -> Path:
    return tmp_path / ".onmc" / "swarm" / swarm_id / "blackboard.jsonl"


def test_append_then_read_round_trips(tmp_path: Path) -> None:
    path = _board_path(tmp_path)
    entry = BoardEntry(ts=100.0, unit_id="unit-0000", kind="finding", note="found a bug")
    append_entry(path, entry)

    entries = read_board(path)
    assert len(entries) == 1
    assert entries[0] == entry


def test_append_creates_parent_dirs(tmp_path: Path) -> None:
    path = _board_path(tmp_path, "brand-new")
    assert not path.parent.exists()
    append_entry(path, BoardEntry(ts=1.0, unit_id="u", kind="finding", note="n"))
    assert path.exists()


def test_multiple_appends_preserve_order(tmp_path: Path) -> None:
    path = _board_path(tmp_path)
    for i in range(5):
        entry = BoardEntry(ts=float(i), unit_id=f"unit-{i}", kind="finding", note=f"note {i}")
        append_entry(path, entry)

    entries = read_board(path)
    assert [e.note for e in entries] == [f"note {i}" for i in range(5)]
    assert [e.ts for e in entries] == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_append_is_append_only_never_rewrites(tmp_path: Path) -> None:
    path = _board_path(tmp_path)
    append_entry(path, BoardEntry(ts=1.0, unit_id="a", kind="finding", note="first"))
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    append_entry(path, BoardEntry(ts=2.0, unit_id="b", kind="claim", note="second"))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == first_line
    assert len(lines) == 2


def test_read_board_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_board(_board_path(tmp_path)) == []


def test_read_board_skips_malformed_lines(tmp_path: Path) -> None:
    path = _board_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    good = BoardEntry(ts=1.0, unit_id="u", kind="finding", note="ok")
    path.write_text(
        "not json at all\n"
        + json.dumps(good.to_dict())
        + "\n"
        + json.dumps({"ts": 2.0, "unit_id": "u"})  # missing kind/note
        + "\n"
        + json.dumps({"ts": 3.0, "unit_id": "u", "kind": "bogus-kind", "note": "n"})  # invalid kind
        + "\n\n",  # blank line
        encoding="utf-8",
    )
    entries = read_board(path)
    assert entries == [good]


def test_invalid_kind_raises_on_append(tmp_path: Path) -> None:
    path = _board_path(tmp_path)
    with pytest.raises(InvalidEntryError):
        append_entry(path, BoardEntry(ts=1.0, unit_id="u", kind="not-a-kind", note="n"))
    # Nothing should have been written.
    assert not path.exists()


def test_filter_by_kind(tmp_path: Path) -> None:
    entries = [
        BoardEntry(ts=1.0, unit_id="a", kind="finding", note="x"),
        BoardEntry(ts=2.0, unit_id="b", kind="warning", note="y"),
        BoardEntry(ts=3.0, unit_id="c", kind="finding", note="z"),
    ]
    filtered = filter_entries(entries, kind="finding")
    assert [e.note for e in filtered] == ["x", "z"]


def test_filter_by_unit(tmp_path: Path) -> None:
    entries = [
        BoardEntry(ts=1.0, unit_id="unit-a", kind="finding", note="x"),
        BoardEntry(ts=2.0, unit_id="unit-b", kind="finding", note="y"),
        BoardEntry(ts=3.0, unit_id="unit-a", kind="claim", note="z"),
    ]
    filtered = filter_entries(entries, unit_id="unit-a")
    assert [e.note for e in filtered] == ["x", "z"]


def test_filter_by_kind_and_unit_combined(tmp_path: Path) -> None:
    entries = [
        BoardEntry(ts=1.0, unit_id="unit-a", kind="finding", note="x"),
        BoardEntry(ts=2.0, unit_id="unit-a", kind="warning", note="y"),
        BoardEntry(ts=3.0, unit_id="unit-b", kind="finding", note="z"),
    ]
    filtered = filter_entries(entries, kind="finding", unit_id="unit-a")
    assert [e.note for e in filtered] == ["x"]


def test_to_dict_is_json_serialisable() -> None:
    entry = BoardEntry(ts=1234.5, unit_id="unit-0000", kind="done", note="all finished")
    payload = entry.to_dict()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped == {
        "ts": 1234.5,
        "unit_id": "unit-0000",
        "kind": "done",
        "note": "all finished",
    }


def test_render_board_empty_state() -> None:
    rendered = render_board([])
    assert "empty" in rendered.lower()
    assert "haven't posted" in rendered


def test_render_board_shows_header_and_entries() -> None:
    entries = [
        BoardEntry(ts=1700000000.0, unit_id="unit-0000", kind="finding", note="found the bug"),
        BoardEntry(ts=1700000100.0, unit_id="unit-0001", kind="warning", note="watch the API"),
    ]
    rendered = render_board(entries)
    assert "2 entries" in rendered
    assert "2 unit(s)" in rendered
    assert "unit-0000" in rendered
    assert "finding" in rendered
    assert "found the bug" in rendered
    assert "unit-0001" in rendered
    assert "warning" in rendered
    assert "watch the API" in rendered


def test_render_board_singular_entry_count() -> None:
    rendered = render_board([BoardEntry(ts=1.0, unit_id="u", kind="finding", note="n")])
    assert "1 entry" in rendered
    assert "1 unit(s)" in rendered


def test_render_board_counts_distinct_units() -> None:
    entries = [
        BoardEntry(ts=1.0, unit_id="unit-a", kind="finding", note="x"),
        BoardEntry(ts=2.0, unit_id="unit-a", kind="claim", note="y"),
        BoardEntry(ts=3.0, unit_id="unit-b", kind="finding", note="z"),
    ]
    rendered = render_board(entries)
    assert "3 entries" in rendered
    assert "2 unit(s)" in rendered


def test_most_recent_swarm_id_picks_newest_mtime(tmp_path: Path) -> None:
    base = tmp_path / ".onmc" / "swarm"
    older = base / "sw-older"
    newer = base / "sw-newer"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / "manifest.json").write_text("{}", encoding="utf-8")
    (newer / "manifest.json").write_text("{}", encoding="utf-8")

    import os
    import time

    now = time.time()
    os.utime(older, (now - 100, now - 100))
    os.utime(newer, (now, now))

    assert _most_recent_swarm_id(base) == "sw-newer"


def test_most_recent_swarm_id_none_when_no_swarms(tmp_path: Path) -> None:
    base = tmp_path / ".onmc" / "swarm"
    assert _most_recent_swarm_id(base) is None


def test_resolve_swarm_id_prefers_explicit_id(tmp_path: Path) -> None:
    base = tmp_path / ".onmc" / "swarm"
    swarm_dir = base / "explicit-id"
    swarm_dir.mkdir(parents=True)
    (swarm_dir / "manifest.json").write_text("{}", encoding="utf-8")
    assert _resolve_swarm_id(base, "explicit-id") == "explicit-id"
    # Even an id with no manifest is accepted verbatim when given explicitly.
    assert _resolve_swarm_id(base, "unknown-id") == "unknown-id"


def test_resolve_swarm_id_falls_back_to_most_recent(tmp_path: Path) -> None:
    base = tmp_path / ".onmc" / "swarm"
    swarm_dir = base / "only-one"
    swarm_dir.mkdir(parents=True)
    (swarm_dir / "manifest.json").write_text("{}", encoding="utf-8")
    assert _resolve_swarm_id(base, None) == "only-one"
