"""Concrete memory-provider adapters.

``BuiltinMemoryProvider``
    Always available.  Wraps onmc's own SQLite memory store via
    :func:`~oh_no_my_claudecode.storage.sqlite.SQLiteStorage.list_memories` /
    :func:`~oh_no_my_claudecode.storage.sqlite.SQLiteStorage.search_memories`.
    Uses :class:`~oh_no_my_claudecode.core.service.OnmcService` to discover the
    repo root and database path.  Requires a git repo with onmc initialized; if
    no repo is found it degrades gracefully (returns empty results, no crash).

``Mem0MemoryProvider``
    Optional.  Available when ``mem0ai`` is installed **and**
    ``MEM0_API_KEY`` is set.  Add via ``pip install oh-no-my-claudecode[mem0]``.

``SupermemoryProvider``
    Optional.  Available when ``supermemory`` is installed **and**
    ``SUPERMEMORY_API_KEY`` is set.  Add via
    ``pip install oh-no-my-claudecode[supermemory]``.

All adapters follow the :class:`~oh_no_my_claudecode.memprovider.base.MemoryProvider`
Protocol.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.memprovider.base import MemoryHit

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Builtin adapter (always available — wraps onmc SQLite store)
# ---------------------------------------------------------------------------


class BuiltinMemoryProvider:
    """Memory provider backed by onmc's own SQLite store.

    This adapter is always registered first and is always available from the
    protocol perspective.  However, if onmc is not initialised in the current
    repository, :meth:`search` returns an empty list and :meth:`add` raises
    :exc:`RuntimeError`.
    """

    @property
    def name(self) -> str:
        return "builtin"

    def available(self) -> bool:
        """Always True — the builtin adapter has no optional dependencies."""
        return True

    def _get_storage(self) -> Any:  # returns SQLiteStorage | None
        """Resolve and return the SQLiteStorage for the current repo.

        Returns ``None`` gracefully when onmc is not initialised.
        """
        try:
            from oh_no_my_claudecode.core.service import OnmcService  # noqa: PLC0415

            service = OnmcService(Path.cwd())
            _repo_root, _config, storage = service._load_context()
            return storage
        except (FileNotFoundError, Exception):  # noqa: BLE001
            return None

    def add(self, entry: str, *, metadata: dict[str, Any] | None = None) -> None:
        """Add a memory entry to the builtin store.

        Raises
        ------
        RuntimeError
            When onmc is not initialised in the current repo.
        """
        from datetime import UTC, datetime  # noqa: PLC0415

        from oh_no_my_claudecode.models.memory import (  # noqa: PLC0415
            MemoryEntry,
            MemoryKind,
            SourceType,
        )
        from oh_no_my_claudecode.utils.text import stable_id  # noqa: PLC0415

        storage = self._get_storage()
        if storage is None:
            msg = "builtin provider: onmc is not initialised in this repo — run `onmc init` first"
            raise RuntimeError(msg)

        meta = metadata or {}
        now = datetime.now(tz=UTC)
        mem_entry = MemoryEntry(
            id=stable_id("memprovider", entry[:200], prefix="mp"),
            kind=MemoryKind(meta.get("kind", MemoryKind.DOC_FACT)),
            title=meta.get("title", entry[:80]),
            summary=entry[:500],
            details=entry,
            source_type=SourceType(meta.get("source_type", SourceType.MANUAL)),
            source_ref=meta.get("source_ref", "memprovider"),
            tags=meta.get("tags", []),
            confidence=float(meta.get("confidence", 0.8)),
            created_at=now,
            updated_at=now,
        )
        storage.upsert_memories([mem_entry])

    def search(self, query: str, *, limit: int = 10) -> list[MemoryHit]:
        """Search onmc's own memory store and return attributed hits."""
        storage = self._get_storage()
        if storage is None:
            return []

        try:
            entries = storage.search_memories(query, limit=limit)
        except Exception:  # noqa: BLE001
            logger.debug("builtin provider: search_memories raised", exc_info=True)
            return []

        hits: list[MemoryHit] = []
        for entry in entries:
            content = f"{entry.title}\n{entry.summary}"
            if entry.details and entry.details != entry.summary:
                content = f"{entry.title}\n{entry.summary}\n{entry.details}"
            hits.append(
                MemoryHit(
                    provider_name=self.name,
                    content=content.strip(),
                    score=float(entry.confidence),
                    metadata={
                        "id": entry.id,
                        "kind": entry.kind.value,
                        "source_type": entry.source_type.value,
                        "tags": entry.tags,
                    },
                )
            )
        return hits


# ---------------------------------------------------------------------------
# Mem0 adapter (optional — requires mem0ai extra + MEM0_API_KEY)
# ---------------------------------------------------------------------------


def _mem0_importable() -> bool:
    """Return True if the mem0ai package is importable."""
    try:
        import mem0  # type: ignore[import-not-found]  # noqa: F401, PLC0415
        return True
    except ImportError:
        return False


class Mem0MemoryProvider:
    """Memory provider backed by Mem0 (https://mem0.ai).

    Requirements
    ------------
    - ``pip install oh-no-my-claudecode[mem0]`` (installs ``mem0ai``).
    - ``MEM0_API_KEY`` environment variable set.

    When either requirement is missing, :meth:`available` returns ``False``
    and all operations degrade gracefully.
    """

    def __init__(self) -> None:
        self._client: Any = None

    @property
    def name(self) -> str:
        return "mem0"

    def available(self) -> bool:
        """Return True when mem0ai is installed and MEM0_API_KEY is set."""
        if not _mem0_importable():
            return False
        return bool(os.environ.get("MEM0_API_KEY", "").strip())

    def _get_client(self) -> Any:
        """Lazily initialise and cache the mem0 client."""
        if self._client is not None:
            return self._client
        try:
            from mem0 import MemoryClient  # noqa: PLC0415

            api_key = os.environ.get("MEM0_API_KEY", "")
            self._client = MemoryClient(api_key=api_key)
        except Exception:  # noqa: BLE001
            logger.debug("mem0 provider: failed to initialise client", exc_info=True)
            return None
        return self._client

    def add(self, entry: str, *, metadata: dict[str, Any] | None = None) -> None:
        """Add a memory entry via the Mem0 API.

        Raises
        ------
        RuntimeError
            When the provider is unavailable or the API call fails.
        """
        if not self.available():
            msg = "mem0 provider: not available (mem0ai not installed or MEM0_API_KEY missing)"
            raise RuntimeError(msg)
        client = self._get_client()
        if client is None:
            msg = "mem0 provider: client initialisation failed"
            raise RuntimeError(msg)
        meta = metadata or {}
        user_id = meta.get("user_id", "onmc")
        try:
            client.add(entry, user_id=user_id, metadata=meta)
        except Exception as exc:  # noqa: BLE001
            msg = f"mem0 provider: add() failed: {exc}"
            raise RuntimeError(msg) from exc

    def search(self, query: str, *, limit: int = 10) -> list[MemoryHit]:
        """Search via the Mem0 API and return attributed hits."""
        if not self.available():
            return []
        client = self._get_client()
        if client is None:
            return []
        try:
            results = client.search(query, limit=limit)
        except Exception:  # noqa: BLE001
            logger.debug("mem0 provider: search() raised", exc_info=True)
            return []

        hits: list[MemoryHit] = []
        for item in results if isinstance(results, list) else []:
            # Mem0 returns dicts with at minimum a "memory" key.
            if isinstance(item, dict):
                content = item.get("memory", "")
                score = float(item.get("score", 1.0))
                meta: dict[str, Any] = {k: v for k, v in item.items() if k != "memory"}
            else:
                content = str(item)
                score = 1.0
                meta = {}
            hits.append(
                MemoryHit(
                    provider_name=self.name,
                    content=content,
                    score=score,
                    metadata=meta,
                )
            )
        return hits


# ---------------------------------------------------------------------------
# Supermemory adapter (optional — requires supermemory extra + SUPERMEMORY_API_KEY)
# ---------------------------------------------------------------------------


def _supermemory_importable() -> bool:
    """Return True if the supermemory package is importable."""
    try:
        import supermemory  # type: ignore[import-not-found]  # noqa: F401, PLC0415
        return True
    except ImportError:
        return False


class SupermemoryProvider:
    """Memory provider backed by Supermemory (https://supermemory.ai).

    Requirements
    ------------
    - ``pip install oh-no-my-claudecode[supermemory]`` (installs ``supermemory``).
    - ``SUPERMEMORY_API_KEY`` environment variable set.

    When either requirement is missing, :meth:`available` returns ``False``
    and all operations degrade gracefully.
    """

    def __init__(self) -> None:
        self._client: Any = None

    @property
    def name(self) -> str:
        return "supermemory"

    def available(self) -> bool:
        """Return True when supermemory is installed and SUPERMEMORY_API_KEY is set."""
        if not _supermemory_importable():
            return False
        return bool(os.environ.get("SUPERMEMORY_API_KEY", "").strip())

    def _get_client(self) -> Any:
        """Lazily initialise and cache the Supermemory client."""
        if self._client is not None:
            return self._client
        try:
            import supermemory  # noqa: PLC0415

            api_key = os.environ.get("SUPERMEMORY_API_KEY", "")
            self._client = supermemory.Supermemory(api_key=api_key)
        except Exception:  # noqa: BLE001
            logger.debug("supermemory provider: failed to initialise client", exc_info=True)
            return None
        return self._client

    def add(self, entry: str, *, metadata: dict[str, Any] | None = None) -> None:
        """Add a memory entry via the Supermemory API.

        Raises
        ------
        RuntimeError
            When the provider is unavailable or the API call fails.
        """
        if not self.available():
            msg = (
                "supermemory provider: not available"
                " (supermemory not installed or SUPERMEMORY_API_KEY missing)"
            )
            raise RuntimeError(msg)
        client = self._get_client()
        if client is None:
            msg = "supermemory provider: client initialisation failed"
            raise RuntimeError(msg)
        try:
            client.memories.add(content=entry, metadata=metadata or {})
        except Exception as exc:  # noqa: BLE001
            msg = f"supermemory provider: add() failed: {exc}"
            raise RuntimeError(msg) from exc

    def search(self, query: str, *, limit: int = 10) -> list[MemoryHit]:
        """Search via the Supermemory API and return attributed hits."""
        if not self.available():
            return []
        client = self._get_client()
        if client is None:
            return []
        try:
            response = client.memories.search(query=query, limit=limit)
        except Exception:  # noqa: BLE001
            logger.debug("supermemory provider: search() raised", exc_info=True)
            return []

        hits: list[MemoryHit] = []
        # Supermemory SDK wraps results in a response object; the .results
        # attribute (or iteration) yields individual memory objects.
        items = response if isinstance(response, list) else getattr(response, "results", response)
        for item in items if items is not None else []:
            content = getattr(item, "content", "") or str(item)
            score = float(getattr(item, "score", 1.0))
            meta_obj = getattr(item, "metadata", {})
            meta: dict[str, Any] = dict(meta_obj) if meta_obj else {}
            hits.append(
                MemoryHit(
                    provider_name=self.name,
                    content=content,
                    score=score,
                    metadata=meta,
                )
            )
        return hits
