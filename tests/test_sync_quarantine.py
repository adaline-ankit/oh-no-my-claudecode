"""Quarantine containment across the .agent-memory/ export boundary.

Background: memory an agent wrote autonomously about its own run (autopilot
WIN/plan staging, MCP ``record_memory``) is quarantined in-repo by the reserved
``unpromoted:`` ``source_ref`` prefix and is never auto-injected into prompts.
That quarantine used to be repo-local while the export was not, so a
never-human-approved entry could leave the repo that quarantined it and be
restored — or federated — somewhere that had forgotten it was quarantined.

Covers:
- export flags quarantined entries and preserves the ``source_ref`` prefix verbatim
- export/restore round-trip keeps a quarantined entry quarantined
- restore honours the ``unpromoted`` flag even if the prefix was stripped
- a ``"unpromoted": false`` flag cannot launder an already-prefixed source_ref
- an OLD export (no ``unpromoted`` key at all) still restores
- federated inbound memory is force-quarantined whatever the sender claimed
- federated inbound memory is not auto-injected into prompts
- federated inbound from an old-format export is quarantined too (safe side)
- re-pulling does not double-prefix (idempotent)
- an ordinary promoted memory is unaffected and stays recallable
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from oh_no_my_claudecode.federation.pull import _federation_tag, pull_memories
from oh_no_my_claudecode.hooks.prompt_recall import (
    compile_prompt_recall,
    is_unpromoted_source,
    unpromoted_source_ref,
)
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, ProjectConfig, SourceType
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.sync.exporter import export_agent_memory
from oh_no_my_claudecode.sync.importer import restore_agent_memory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, tzinfo=UTC)

# A memory an agent wrote about its own run: quarantined at rest.
_QUARANTINED_REF = unpromoted_source_ref("mcp:record_memory")

# A memory with ordinary reviewed provenance: freely recallable.
_PROMOTED_REF = "docs/architecture.md"


def _memory(
    memory_id: str,
    *,
    source_ref: str,
    title: str = "Cache invalidation boundary",
) -> MemoryEntry:
    return MemoryEntry(
        id=memory_id,
        kind=MemoryKind.DECISION,
        title=title,
        summary="Cache invalidation must go through the shared boundary.",
        details="Recorded during a task about the cache invalidation regression.",
        source_type=SourceType.MANUAL,
        source_ref=source_ref,
        tags=["cache"],
        confidence=0.9,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _storage(db_path: Path) -> SQLiteStorage:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    return storage


def _export(
    repo: Path,
    storage: SQLiteStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Run the real exporter into ``<repo>/.agent-memory`` and return that dir.

    ``export_agent_memory`` stamps the running ONMC version into the manifest
    via ``importlib.metadata``; that lookup is patched out so these tests do not
    depend on the package being installed in the running interpreter.
    """
    monkeypatch.setattr(
        "oh_no_my_claudecode.sync.exporter.version",
        lambda _name: "0.0.0-test",
    )
    output_dir = repo / ".agent-memory"
    export_agent_memory(
        repo_root=repo,
        config=ProjectConfig(repo_root=str(repo)),
        storage=storage,
        output_dir=output_dir,
    )
    return output_dir


def _memory_payload(agent_memory_dir: Path, memory_id: str) -> dict[str, Any]:
    matches = [
        path
        for path in agent_memory_dir.glob("memories/*/*.json")
        if path.stem == memory_id
    ]
    assert matches, f"no exported record for {memory_id!r}"
    payload: dict[str, Any] = json.loads(matches[0].read_text(encoding="utf-8"))
    return payload


def _rewrite_memory_payload(
    agent_memory_dir: Path,
    memory_id: str,
    payload: dict[str, Any],
) -> None:
    matches = [
        path
        for path in agent_memory_dir.glob("memories/*/*.json")
        if path.stem == memory_id
    ]
    assert matches
    matches[0].write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_handmade_export(
    agent_memory_dir: Path,
    records: list[dict[str, Any]],
) -> Path:
    """Write an export directory literally, bypassing the current exporter.

    Used to simulate a *foreign* producer: an older ONMC that predates the
    quarantine marker, or any other writer of the open format.  ``records`` are
    written verbatim so a test can omit the ``unpromoted`` key entirely.
    """
    agent_memory_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        kind = record["memory"]["kind"]
        target = agent_memory_dir / "memories" / kind / f"{record['memory']['id']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (agent_memory_dir / "tasks").mkdir(exist_ok=True)
    manifest = {
        "version": "1",
        "repo_root": ".",
        "exported_at": _NOW.isoformat(),
        "onmc_version": "0.1.0",
        "counts": {
            "memories": len(records),
            "tasks": 0,
            "attempts": 0,
            "artifacts": 0,
            "skills": 0,
        },
    }
    (agent_memory_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return agent_memory_dir


def _legacy_record(memory: MemoryEntry) -> dict[str, Any]:
    """An export record in the OLD shape: no ``unpromoted`` key at all."""
    return {"memory": json.loads(memory.model_dump_json())}


# ---------------------------------------------------------------------------
# Export: quarantine is visible on disk and the prefix is preserved verbatim
# ---------------------------------------------------------------------------


def test_export_flags_quarantined_memory_and_preserves_source_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _storage(tmp_path / "brain.db")
    storage.upsert_memories(
        [
            _memory("mem-quarantined", source_ref=_QUARANTINED_REF),
            _memory("mem-promoted", source_ref=_PROMOTED_REF),
        ]
    )

    agent_memory_dir = _export(tmp_path, storage, monkeypatch)

    quarantined = _memory_payload(agent_memory_dir, "mem-quarantined")
    assert quarantined["unpromoted"] is True
    assert quarantined["memory"]["source_ref"] == _QUARANTINED_REF

    promoted = _memory_payload(agent_memory_dir, "mem-promoted")
    assert promoted["unpromoted"] is False
    assert promoted["memory"]["source_ref"] == _PROMOTED_REF


# ---------------------------------------------------------------------------
# Restore: round-trip preserves quarantine
# ---------------------------------------------------------------------------


def test_export_round_trip_restore_preserves_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _storage(tmp_path / "brain.db")
    source.upsert_memories(
        [
            _memory("mem-quarantined", source_ref=_QUARANTINED_REF),
            _memory("mem-promoted", source_ref=_PROMOTED_REF),
        ]
    )
    agent_memory_dir = _export(tmp_path, source, monkeypatch)

    restored_storage = _storage(tmp_path / "restored.db")
    result = restore_agent_memory(input_dir=agent_memory_dir, storage=restored_storage)

    assert result.memory_count == 2
    quarantined = restored_storage.get_memory("mem-quarantined")
    assert quarantined is not None
    assert quarantined.source_ref == _QUARANTINED_REF
    assert is_unpromoted_source(quarantined.source_ref)

    promoted = restored_storage.get_memory("mem-promoted")
    assert promoted is not None
    assert promoted.source_ref == _PROMOTED_REF
    assert not is_unpromoted_source(promoted.source_ref)


def test_restore_honours_unpromoted_flag_when_prefix_was_stripped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The explicit flag is a second, independent quarantine signal."""
    storage = _storage(tmp_path / "brain.db")
    storage.upsert_memories([_memory("mem-quarantined", source_ref=_QUARANTINED_REF)])
    agent_memory_dir = _export(tmp_path, storage, monkeypatch)

    payload = _memory_payload(agent_memory_dir, "mem-quarantined")
    payload["memory"]["source_ref"] = "docs/looks-reviewed.md"
    assert payload["unpromoted"] is True
    _rewrite_memory_payload(agent_memory_dir, "mem-quarantined", payload)

    restored_storage = _storage(tmp_path / "restored.db")
    restore_agent_memory(input_dir=agent_memory_dir, storage=restored_storage)

    restored = restored_storage.get_memory("mem-quarantined")
    assert restored is not None
    assert is_unpromoted_source(restored.source_ref)
    assert restored.source_ref == "unpromoted:docs/looks-reviewed.md"


def test_restore_flag_false_cannot_launder_prefixed_source_ref(
    tmp_path: Path,
) -> None:
    """Quarantine is a union of both signals; the flag can only ever add it."""
    agent_memory_dir = _write_handmade_export(
        tmp_path / ".agent-memory",
        [
            {
                "memory": json.loads(
                    _memory("mem-quarantined", source_ref=_QUARANTINED_REF).model_dump_json()
                ),
                "unpromoted": False,
            }
        ],
    )

    storage = _storage(tmp_path / "restored.db")
    restore_agent_memory(input_dir=agent_memory_dir, storage=storage)

    restored = storage.get_memory("mem-quarantined")
    assert restored is not None
    assert restored.source_ref == _QUARANTINED_REF


# ---------------------------------------------------------------------------
# Backward compatibility: an OLD export with no `unpromoted` key still restores
# ---------------------------------------------------------------------------


def test_old_format_export_without_flag_still_restores(tmp_path: Path) -> None:
    records = [
        _legacy_record(_memory("mem-promoted", source_ref=_PROMOTED_REF)),
        _legacy_record(_memory("mem-quarantined", source_ref=_QUARANTINED_REF)),
    ]
    assert all("unpromoted" not in record for record in records)
    agent_memory_dir = _write_handmade_export(tmp_path / ".agent-memory", records)

    storage = _storage(tmp_path / "restored.db")
    result = restore_agent_memory(input_dir=agent_memory_dir, storage=storage)

    assert result.memory_count == 2
    promoted = storage.get_memory("mem-promoted")
    assert promoted is not None
    assert promoted.source_ref == _PROMOTED_REF

    # Falling back to the prefix alone is exactly the previous behaviour.
    quarantined = storage.get_memory("mem-quarantined")
    assert quarantined is not None
    assert is_unpromoted_source(quarantined.source_ref)


# ---------------------------------------------------------------------------
# Federation inbound: force-quarantine regardless of what the sender claimed
# ---------------------------------------------------------------------------


def test_federated_inbound_memory_arrives_quarantined(tmp_path: Path) -> None:
    """A sender claiming clean, human-reviewed provenance is not believed."""
    remote = _write_handmade_export(
        tmp_path / "other-repo" / ".agent-memory",
        [
            {
                "memory": json.loads(
                    _memory("mem-from-elsewhere", source_ref=_PROMOTED_REF).model_dump_json()
                ),
                "unpromoted": False,
            }
        ],
    )

    storage = _storage(tmp_path / "local.db")
    result = pull_memories(storage, remote)

    assert result.imported == 1
    imported = storage.get_memory("mem-from-elsewhere")
    assert imported is not None
    assert is_unpromoted_source(imported.source_ref)
    # The sender's provenance pointer is kept behind the prefix, not discarded.
    assert imported.source_ref == f"unpromoted:{_PROMOTED_REF}"
    assert _federation_tag("other-repo") in imported.tags


def test_federated_inbound_is_not_auto_injected_into_prompts(tmp_path: Path) -> None:
    """The end-to-end property: inbound federated memory cannot arrive active."""
    remote = _write_handmade_export(
        tmp_path / "other-repo" / ".agent-memory",
        [
            {
                "memory": json.loads(
                    _memory("mem-from-elsewhere", source_ref=_PROMOTED_REF).model_dump_json()
                ),
                "unpromoted": False,
            }
        ],
    )

    storage = _storage(tmp_path / "local.db")
    pull_memories(storage, remote)

    text, tokens = compile_prompt_recall(storage, "cache invalidation boundary", limit=5)

    assert (text, tokens) == ("", 0)
    # ...but it is still stored and reachable through explicit human surfaces.
    assert storage.get_memory("mem-from-elsewhere") is not None


def test_federated_inbound_from_old_format_export_is_quarantined(tmp_path: Path) -> None:
    """Unknown provenance resolves to the safe side, not to 'promoted'."""
    remote = _write_handmade_export(
        tmp_path / "legacy-repo" / ".agent-memory",
        [_legacy_record(_memory("mem-legacy", source_ref=_PROMOTED_REF))],
    )

    storage = _storage(tmp_path / "local.db")
    result = pull_memories(storage, remote)

    assert result.imported == 1
    imported = storage.get_memory("mem-legacy")
    assert imported is not None
    assert is_unpromoted_source(imported.source_ref)


def test_federated_pull_quarantine_is_idempotent(tmp_path: Path) -> None:
    remote = _write_handmade_export(
        tmp_path / "other-repo" / ".agent-memory",
        [_legacy_record(_memory("mem-from-elsewhere", source_ref=_PROMOTED_REF))],
    )

    storage = _storage(tmp_path / "local.db")
    first = pull_memories(storage, remote)
    second = pull_memories(storage, remote)

    assert (first.imported, first.skipped) == (1, 0)
    assert (second.imported, second.skipped) == (0, 1)

    imported = storage.get_memory("mem-from-elsewhere")
    assert imported is not None
    assert imported.source_ref == f"unpromoted:{_PROMOTED_REF}"
    assert imported.tags.count(_federation_tag("other-repo")) == 1


# ---------------------------------------------------------------------------
# Control: ordinary promoted memory is untouched by all of the above
# ---------------------------------------------------------------------------


def test_promoted_memory_survives_round_trip_and_stays_recallable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _storage(tmp_path / "brain.db")
    original = _memory("mem-promoted", source_ref=_PROMOTED_REF)
    source.upsert_memories([original])
    agent_memory_dir = _export(tmp_path, source, monkeypatch)

    restored_storage = _storage(tmp_path / "restored.db")
    restore_agent_memory(input_dir=agent_memory_dir, storage=restored_storage)

    restored = restored_storage.get_memory("mem-promoted")
    assert restored is not None
    assert restored.source_ref == original.source_ref
    assert restored.tags == original.tags

    text, tokens = compile_prompt_recall(
        restored_storage, "cache invalidation boundary", limit=5
    )
    assert original.title in text
    assert tokens > 0
