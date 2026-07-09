"""Continuous Hermes memory mirror.

The existing :mod:`oh_no_my_claudecode.importers.hermes` importer is *one-shot*:
every run re-parses ``MEMORY.md`` / ``USER.md`` and relies on the store's
content-derived ids to dedup.  This module adds a *continuous* mirror on top of
it — the shape you want when Hermes is a live, self-improving memory source that
keeps changing:

- It reuses the existing importer's parser wholesale
  (:func:`oh_no_my_claudecode.importers.hermes.resolve_hermes_files` +
  :func:`~oh_no_my_claudecode.importers.hermes.parse`) — it never re-implements
  the ``##``-section parsing or the kind heuristics.
- It keeps a watermark under ``.onmc/connect/hermes-state.json`` mapping each
  imported memory id → a content hash, and imports only entries that are new or
  whose content changed since the last sync.  Re-running with no source changes
  therefore imports nothing (``imported == 0``) — idempotent by construction.
- It never crashes on a missing source: an absent path / directory returns an
  empty :class:`HermesSyncResult`.

The store write is done through an injectable ``storage`` seam (any object with
``upsert_memories``); the default opens the repo's SQLite store.  Tests inject a
fake store so they stay fully offline.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from oh_no_my_claudecode.importers import hermes as _hermes
from oh_no_my_claudecode.models import MemoryEntry

__all__ = ["HermesSyncResult", "MemoryStore", "sync_hermes"]

#: Watermark file, relative to the repo root.
_STATE_REL = Path(".onmc") / "connect" / "hermes-state.json"
_STATE_VERSION = 1


class MemoryStore(Protocol):
    """Minimal structural contract for a store the mirror can write to.

    :class:`oh_no_my_claudecode.storage.sqlite.SQLiteStorage` satisfies this;
    tests provide a tiny fake so the mirror is exercised without a database.
    """

    def upsert_memories(self, entries: list[MemoryEntry]) -> tuple[int, int]: ...


@dataclass(frozen=True)
class HermesSyncResult:
    """Summary of one :func:`sync_hermes` run.

    Attributes
    ----------
    imported:
        Entries that were new or changed since the last sync (and, when not a
        dry run, written to the store + recorded in the watermark).
    skipped:
        Entries already mirrored unchanged.
    total:
        Total entries parsed from the Hermes source.
    dry_run:
        ``True`` when nothing was written (parse + diff + report only).
    """

    imported: int
    skipped: int
    total: int
    dry_run: bool


def _now_ms() -> int:
    """Wall-clock milliseconds — isolated so callers can inject a fixed clock."""
    return int(time.time() * 1000)


def _state_path(repo_root: Path) -> Path:
    """Absolute path to the watermark file under *repo_root*."""
    return repo_root / _STATE_REL


def _entry_hash(entry: MemoryEntry) -> str:
    """Stable content hash of a memory — changes iff the mirrored content does."""
    digest = hashlib.sha256()
    for part in (entry.kind.value, entry.title, entry.details):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _load_state(path: Path) -> dict[str, str]:
    """Load the ``{memory_id: hash}`` watermark, or ``{}`` when absent/corrupt."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {k: v for k, v in entries.items() if isinstance(k, str) and isinstance(v, str)}


def _write_state(path: Path, entries: dict[str, str], *, now_ms: int) -> None:
    """Persist the watermark deterministically (sorted keys)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": _STATE_VERSION, "updated_at_ms": now_ms, "entries": entries}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _open_store(repo_root: Path) -> MemoryStore:
    """Open the repo's SQLite memory store (default write target).

    Imported lazily so merely importing this module never touches the DB layer.
    """
    from oh_no_my_claudecode.config import (
        config_exists,
        database_path,
        default_config,
        load_config,
    )
    from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

    config = load_config(repo_root) if config_exists(repo_root) else default_config(repo_root)
    store = SQLiteStorage(database_path(config, repo_root))
    store.initialize()
    return store


def sync_hermes(
    repo_root: Path | str,
    hermes_root: Path | str,
    *,
    dry_run: bool = True,
    now_ms: int | None = None,
    storage: MemoryStore | None = None,
) -> HermesSyncResult:
    """Mirror the delta of a Hermes memory source into onmc, idempotently.

    Parameters
    ----------
    repo_root:
        onmc repo root; the watermark lives at
        ``<repo_root>/.onmc/connect/hermes-state.json``.
    hermes_root:
        Path to a Hermes ``MEMORY.md`` / ``USER.md`` file or a directory holding
        them (delegated to the existing importer's resolver).
    dry_run:
        When ``True`` (default) parse + diff + report only — no store write, no
        watermark update.
    now_ms:
        Injectable clock for the watermark's ``updated_at_ms`` (defaults to now).
    storage:
        Injectable write target (any :class:`MemoryStore`).  Defaults to the
        repo's SQLite store — only opened on a non-dry run with a real delta.

    Returns
    -------
    HermesSyncResult
        Counts for this run.  A missing source yields an all-zero result rather
        than raising.
    """
    root = Path(repo_root)
    try:
        files = _hermes.resolve_hermes_files(Path(hermes_root))
    except FileNotFoundError:
        return HermesSyncResult(imported=0, skipped=0, total=0, dry_run=dry_run)

    memories = _hermes.parse(files)
    total = len(memories)

    state = _load_state(_state_path(root))
    delta = [m for m in memories if state.get(m.id) != _entry_hash(m)]
    imported = len(delta)
    skipped = total - imported

    if dry_run:
        return HermesSyncResult(imported=imported, skipped=skipped, total=total, dry_run=True)

    if delta:
        store = storage if storage is not None else _open_store(root)
        store.upsert_memories(delta)

    new_state = dict(state)
    for memory in memories:
        new_state[memory.id] = _entry_hash(memory)
    _write_state(_state_path(root), new_state, now_ms=now_ms if now_ms is not None else _now_ms())

    return HermesSyncResult(imported=imported, skipped=skipped, total=total, dry_run=False)
