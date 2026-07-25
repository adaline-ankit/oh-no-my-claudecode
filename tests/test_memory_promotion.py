"""First-class promotion state on memory entries, and its schema migration.

Quarantine used to live in a reserved ``unpromoted:`` prefix on ``source_ref``.
It now lives in :class:`PromotionState` on ``MemoryEntry`` and in the
``promotion_state`` column, with the prefix kept as a synchronized compat
mirror for modules that still consult it.

Covered here:

- the duplicated prefix constant stays equal to the hook's constant
- a fresh database round-trips ``promotion_state`` (both values)
- the persisted ``source_ref`` column is pure provenance — no prefix on disk
- a legacy v7 row carrying the prefix migrates to quarantined + clean ref
- a legacy ordinary row stays injectable (the safe default)
- the migration loses nothing and is idempotent
- the field survives ``update_memory`` and re-``upsert_memories``
- promote/revoke expressed only through the prefix still work
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oh_no_my_claudecode.hooks.prompt_recall import (
    UNPROMOTED_SOURCE_PREFIX,
    is_unpromoted_source,
    unpromoted_source_ref,
)
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, PromotionState, SourceType
from oh_no_my_claudecode.models import memory as memory_model
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.storage import sqlite as sqlite_storage
from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now

_LEGACY_SCHEMA_VERSION = 7


def _entry(
    memory_id: str,
    *,
    source_ref: str = "docs/architecture.md",
    promotion_state: PromotionState = PromotionState.INJECTABLE,
) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=memory_id,
        kind=MemoryKind.DECISION,
        title=f"Title {memory_id}",
        summary=f"Summary {memory_id}",
        details=f"Details {memory_id}",
        source_type=SourceType.DOC,
        source_ref=source_ref,
        tags=["alpha"],
        confidence=0.8,
        created_at=now,
        updated_at=now,
        promotion_state=promotion_state,
    )


def _raw_rows(db_path: Path) -> dict[str, sqlite3.Row]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM memories").fetchall()
    return {str(row["id"]): row for row in rows}


def _legacy_database(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create a genuine pre-v8 database (schema_version 7, no promotion column)."""
    monkeypatch.setattr(
        sqlite_storage,
        "_MIGRATIONS",
        sqlite_storage._MIGRATIONS[:_LEGACY_SCHEMA_VERSION],
    )
    SQLiteStorage(db_path).initialize()
    monkeypatch.undo()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        version = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        assert int(version["value"]) == _LEGACY_SCHEMA_VERSION
        columns = {str(r["name"]) for r in conn.execute("PRAGMA table_info(memories)")}
        assert "promotion_state" not in columns


def _insert_legacy_row(
    db_path: Path,
    memory_id: str,
    source_ref: str,
    *,
    feedback_score: float = 0.0,
) -> None:
    """Insert a row the way a pre-v8 ONMC would have — prefix and all."""
    now = isoformat_utc(utc_now())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO memories (
                id, kind, title, summary, details, source_type, source_ref,
                tags_json, confidence, feedback_score, created_at, updated_at,
                staleness
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                MemoryKind.DECISION.value,
                f"Title {memory_id}",
                f"Summary {memory_id}",
                f"Details {memory_id}",
                SourceType.SESSION.value,
                source_ref,
                '["legacy"]',
                0.6,
                feedback_score,
                now,
                now,
                "fresh",
            ),
        )


# ---------------------------------------------------------------------------
# The compat mirror
# ---------------------------------------------------------------------------


def test_prefix_constant_matches_hook_helpers() -> None:
    """models.memory duplicates the prefix (import cycle); pin them together."""
    assert memory_model.UNPROMOTED_SOURCE_PREFIX == UNPROMOTED_SOURCE_PREFIX
    assert memory_model.add_unpromoted_prefix("autopilot:engine") == unpromoted_source_ref(
        "autopilot:engine"
    )
    assert memory_model.has_unpromoted_prefix("unpromoted:docs/x.md")
    assert is_unpromoted_source(memory_model.add_unpromoted_prefix("docs/x.md"))
    assert not memory_model.has_unpromoted_prefix("docs/x.md")
    assert memory_model.strip_unpromoted_prefix("unpromoted:unpromoted:docs/x.md") == "docs/x.md"
    assert memory_model.strip_unpromoted_prefix(UNPROMOTED_SOURCE_PREFIX) == "unknown"


def test_model_syncs_state_and_prefix_in_both_directions() -> None:
    from_prefix = _entry("m-1", source_ref=unpromoted_source_ref("autopilot:engine"))
    assert from_prefix.promotion_state is PromotionState.QUARANTINED

    from_state = _entry("m-2", source_ref="docs/x.md", promotion_state=PromotionState.QUARANTINED)
    assert is_unpromoted_source(from_state.source_ref)
    assert from_state.source_ref == "unpromoted:docs/x.md"

    ordinary = _entry("m-3")
    assert ordinary.promotion_state is PromotionState.INJECTABLE
    assert not is_unpromoted_source(ordinary.source_ref)


# ---------------------------------------------------------------------------
# Fresh database round-trip
# ---------------------------------------------------------------------------


def test_fresh_db_round_trips_promotion_state(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    storage = SQLiteStorage(db_path)
    storage.initialize()

    quarantined = _entry(
        "agent-1",
        source_ref="autopilot:engine",
        promotion_state=PromotionState.QUARANTINED,
    )
    injectable = _entry("doc-1", source_ref="docs/architecture.md")
    storage.upsert_memories([quarantined, injectable])

    reloaded_quarantined = storage.get_memory("agent-1")
    reloaded_injectable = storage.get_memory("doc-1")
    assert reloaded_quarantined is not None
    assert reloaded_injectable is not None
    assert reloaded_quarantined.promotion_state is PromotionState.QUARANTINED
    assert reloaded_injectable.promotion_state is PromotionState.INJECTABLE

    # Backward compatibility: prefix-consulting code still sees quarantine.
    assert is_unpromoted_source(reloaded_quarantined.source_ref)
    assert not is_unpromoted_source(reloaded_injectable.source_ref)

    # ...but the column itself is pure provenance and SQL-queryable.
    rows = _raw_rows(db_path)
    assert rows["agent-1"]["source_ref"] == "autopilot:engine"
    assert rows["agent-1"]["promotion_state"] == PromotionState.QUARANTINED.value
    assert rows["doc-1"]["source_ref"] == "docs/architecture.md"
    assert rows["doc-1"]["promotion_state"] == PromotionState.INJECTABLE.value

    with sqlite3.connect(db_path) as conn:
        quarantined_ids = [
            str(row[0])
            for row in conn.execute(
                "SELECT id FROM memories WHERE promotion_state = ?",
                (PromotionState.QUARANTINED.value,),
            )
        ]
    assert quarantined_ids == ["agent-1"]


def test_prefix_written_by_a_legacy_writer_is_not_persisted_into_source_ref(
    tmp_path: Path,
) -> None:
    """A writer still stamping the prefix gets a clean column + the new field."""
    storage = SQLiteStorage(tmp_path / "memory.db")
    storage.initialize()
    storage.upsert_memories([_entry("agent-1", source_ref=unpromoted_source_ref("docs/x.md"))])

    rows = _raw_rows(tmp_path / "memory.db")
    assert rows["agent-1"]["source_ref"] == "docs/x.md"
    assert rows["agent-1"]["promotion_state"] == PromotionState.QUARANTINED.value

    reloaded = storage.get_memory("agent-1")
    assert reloaded is not None
    assert reloaded.promotion_state is PromotionState.QUARANTINED
    assert reloaded.source_ref == "unpromoted:docs/x.md"


# ---------------------------------------------------------------------------
# Migration of existing databases
# ---------------------------------------------------------------------------


def test_legacy_prefixed_row_migrates_to_quarantined_with_clean_source_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "memory.db"
    _legacy_database(db_path, monkeypatch)
    _insert_legacy_row(db_path, "agent-1", "unpromoted:docs/x.md", feedback_score=0.25)

    storage = SQLiteStorage(db_path)
    storage.initialize()

    row = _raw_rows(db_path)["agent-1"]
    assert row["source_ref"] == "docs/x.md"
    assert row["promotion_state"] == PromotionState.QUARANTINED.value
    # Nothing else about the row was touched.
    assert row["feedback_score"] == 0.25
    assert row["staleness"] == "fresh"
    assert row["title"] == "Title agent-1"

    migrated = storage.get_memory("agent-1")
    assert migrated is not None
    assert migrated.promotion_state is PromotionState.QUARANTINED
    # The compat mirror is reconstructed on read, so prefix readers agree.
    assert is_unpromoted_source(migrated.source_ref)


def test_legacy_ordinary_row_stays_injectable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The safe default: pre-concept rows keep behaving exactly as before."""
    db_path = tmp_path / "memory.db"
    _legacy_database(db_path, monkeypatch)
    _insert_legacy_row(db_path, "doc-1", "docs/architecture.md")
    _insert_legacy_row(db_path, "manual-1", "manual")

    SQLiteStorage(db_path).initialize()

    rows = _raw_rows(db_path)
    for memory_id, source_ref in (("doc-1", "docs/architecture.md"), ("manual-1", "manual")):
        assert rows[memory_id]["source_ref"] == source_ref
        assert rows[memory_id]["promotion_state"] == PromotionState.INJECTABLE.value

    entries = {entry.id: entry for entry in SQLiteStorage(db_path).list_memories()}
    assert all(
        entry.promotion_state is PromotionState.INJECTABLE for entry in entries.values()
    )
    assert not any(is_unpromoted_source(entry.source_ref) for entry in entries.values())


def test_migration_preserves_every_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "memory.db"
    _legacy_database(db_path, monkeypatch)
    _insert_legacy_row(db_path, "agent-1", "unpromoted:autopilot:engine")
    _insert_legacy_row(db_path, "agent-2", "unpromoted:unpromoted:docs/doubled.md")
    _insert_legacy_row(db_path, "doc-1", "docs/architecture.md")

    storage = SQLiteStorage(db_path)
    storage.initialize()

    assert storage.memory_count() == 3
    rows = _raw_rows(db_path)
    assert set(rows) == {"agent-1", "agent-2", "doc-1"}
    assert rows["agent-2"]["source_ref"] == "docs/doubled.md"
    assert rows["agent-2"]["promotion_state"] == PromotionState.QUARANTINED.value


def test_migration_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "memory.db"
    _legacy_database(db_path, monkeypatch)
    _insert_legacy_row(db_path, "agent-1", "unpromoted:docs/x.md")
    _insert_legacy_row(db_path, "doc-1", "docs/architecture.md")

    SQLiteStorage(db_path).initialize()
    first = {key: dict(row) for key, row in _raw_rows(db_path).items()}

    # Re-running initialize() (schema_version gate) changes nothing...
    SQLiteStorage(db_path).initialize()
    assert {key: dict(row) for key, row in _raw_rows(db_path).items()} == first

    # ...and neither does invoking the migration directly, twice, bypassing
    # the version gate entirely.
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        sqlite_storage._migrate_v8(conn)
        sqlite_storage._migrate_v8(conn)
    assert {key: dict(row) for key, row in _raw_rows(db_path).items()} == first


def test_migration_records_schema_version_8(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "memory.db"
    _legacy_database(db_path, monkeypatch)
    SQLiteStorage(db_path).initialize()

    with sqlite3.connect(db_path) as conn:
        version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    assert int(version[0]) == 8


# ---------------------------------------------------------------------------
# The field survives writes
# ---------------------------------------------------------------------------


def test_promotion_state_survives_update_and_upsert(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "memory.db")
    storage.initialize()
    entry = _entry(
        "agent-1",
        source_ref="autopilot:engine",
        promotion_state=PromotionState.QUARANTINED,
    )
    storage.upsert_memories([entry])

    stored = storage.get_memory("agent-1")
    assert stored is not None
    storage.update_memory(stored.model_copy(update={"summary": "Edited", "feedback_score": 0.5}))
    after_update = storage.get_memory("agent-1")
    assert after_update is not None
    assert after_update.summary == "Edited"
    assert after_update.promotion_state is PromotionState.QUARANTINED
    assert is_unpromoted_source(after_update.source_ref)

    # Re-upserting the reloaded entry must not launder the quarantine.
    storage.upsert_memories([after_update])
    after_upsert = storage.get_memory("agent-1")
    assert after_upsert is not None
    assert after_upsert.promotion_state is PromotionState.QUARANTINED

    # replace_generated_memories re-inserts non-protected rows wholesale.
    storage.replace_generated_memories([after_upsert])
    after_replace = storage.get_memory("agent-1")
    assert after_replace is not None
    assert after_replace.promotion_state is PromotionState.QUARANTINED
    assert _raw_rows(tmp_path / "memory.db")["agent-1"]["source_ref"] == "autopilot:engine"


def test_prefix_only_promote_and_revoke_still_work(tmp_path: Path) -> None:
    """The existing promote/revoke path mutates only ``source_ref`` (via
    ``model_copy``, which skips validation).  The prefix stays the tiebreaker,
    so that path keeps working and never leaves the two views disagreeing in
    storage."""
    storage = SQLiteStorage(tmp_path / "memory.db")
    storage.initialize()
    storage.upsert_memories(
        [_entry("agent-1", source_ref=unpromoted_source_ref("autopilot:engine"))]
    )

    quarantined = storage.get_memory("agent-1")
    assert quarantined is not None
    promoted = quarantined.model_copy(update={"source_ref": "autopilot:engine"})
    storage.update_memory(promoted)

    reloaded = storage.get_memory("agent-1")
    assert reloaded is not None
    assert reloaded.promotion_state is PromotionState.INJECTABLE
    assert not is_unpromoted_source(reloaded.source_ref)

    revoked = reloaded.model_copy(
        update={"source_ref": unpromoted_source_ref(reloaded.source_ref)}
    )
    storage.update_memory(revoked)
    re_reloaded = storage.get_memory("agent-1")
    assert re_reloaded is not None
    assert re_reloaded.promotion_state is PromotionState.QUARANTINED
    assert is_unpromoted_source(re_reloaded.source_ref)
