"""Cross-repo brain federation: import another repo's .agent-memory/ into this brain.

Federated memories are namespaced with a ``federated:<repo-label>`` tag so they
are clearly attributed to their source repository and never confused with local
memories.  Re-pulling is idempotent: memories already present in the local store
(matched by their stable id) are counted as skipped rather than re-imported.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from oh_no_my_claudecode.models import MemoryEntry
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.sync.schema import ExportedMemoryRecord, SyncManifest


@dataclass
class PullResult:
    """Result of a ``onmc pull`` federation import."""

    source: str
    """Absolute path of the source ``.agent-memory/`` directory that was read."""

    repo_label: str
    """Short repo name derived from the source path (used as the federation namespace)."""

    imported: int
    """Number of new memories inserted into the local store."""

    skipped: int
    """Number of memories skipped because they were already present (dedup by id)."""


def _resolve_agent_memory_dir(source: Path) -> Path:
    """Return the ``.agent-memory/`` directory for *source*.

    Accepts either:
    - a path directly to a ``.agent-memory/`` directory (contains ``manifest.json``), or
    - a path to a repo root that contains a ``.agent-memory/`` sub-directory.

    Raises ``FileNotFoundError`` if neither layout is found.
    """
    # Case 1: caller pointed directly at the .agent-memory dir.
    candidate_manifest = source / "manifest.json"
    if candidate_manifest.exists():
        return source

    # Case 2: caller pointed at a repo root — look for .agent-memory/ inside it.
    nested = source / ".agent-memory"
    if (nested / "manifest.json").exists():
        return nested

    msg = (
        f"No .agent-memory/manifest.json found at '{source}' or '{source / '.agent-memory'}'.\n"
        "Run `onmc sync --commit` on the source repo to produce an export first."
    )
    raise FileNotFoundError(msg)


def _repo_label_from_path(agent_memory_dir: Path) -> str:
    """Derive a short repo label from the .agent-memory dir path.

    For a path like ``/home/user/my-project/.agent-memory`` this returns
    ``my-project``.  Falls back to the directory name itself if the parent is
    the root or the empty string.
    """
    parent = agent_memory_dir.parent
    label = parent.name
    return label if label else agent_memory_dir.name


def _federation_tag(repo_label: str) -> str:
    """Return the canonical federation tag for *repo_label*."""
    return f"federated:{repo_label}"


def _stamp_federated(memory: MemoryEntry, *, repo_label: str) -> MemoryEntry:
    """Return a copy of *memory* with the federation tag added to its tags list.

    If the tag is already present (e.g. from a previous pull) the memory is
    returned unchanged to preserve idempotency.
    """
    tag = _federation_tag(repo_label)
    if tag in memory.tags:
        return memory
    return memory.model_copy(update={"tags": [*memory.tags, tag]})


def pull_memories(
    storage: SQLiteStorage,
    source_dir: Path,
    *,
    repo_label: str | None = None,
) -> PullResult:
    """Import memories from *source_dir* into *storage*, namespaced as federated.

    Parameters
    ----------
    storage:
        The local brain's SQLiteStorage instance (already initialised).
    source_dir:
        Path to either the source repo root or its ``.agent-memory/`` directory.
    repo_label:
        Optional override for the federation namespace label.  When omitted the
        label is derived from the source directory name.

    Returns
    -------
    PullResult
        Summary counts: how many memories were imported vs. skipped.

    Raises
    ------
    FileNotFoundError
        When *source_dir* does not contain a valid ``.agent-memory/`` export.
    """
    agent_memory_dir = _resolve_agent_memory_dir(source_dir)

    # Validate the manifest so we fail fast on corrupt exports.
    manifest_path = agent_memory_dir / "manifest.json"
    SyncManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))

    resolved_label = repo_label or _repo_label_from_path(agent_memory_dir)

    imported = 0
    skipped = 0

    memories_dir = agent_memory_dir / "memories"
    if memories_dir.exists():
        for payload_path in sorted(memories_dir.glob("*/*.json")):
            exported = ExportedMemoryRecord.model_validate(
                json.loads(payload_path.read_text(encoding="utf-8"))
            )
            original: MemoryEntry = exported.memory

            # Dedup: if the memory id already exists locally, skip it.
            if storage.get_memory(original.id) is not None:
                skipped += 1
                continue

            stamped = _stamp_federated(original, repo_label=resolved_label)
            storage.upsert_memories([stamped])
            imported += 1

    return PullResult(
        source=agent_memory_dir.as_posix(),
        repo_label=resolved_label,
        imported=imported,
        skipped=skipped,
    )
