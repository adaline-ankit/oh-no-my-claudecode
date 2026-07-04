"""Core Protocol and registry for external memory-provider adapters.

The :class:`MemoryProvider` Protocol defines the contract every adapter must
satisfy.  The :class:`ProviderRegistry` discovers and caches all registered
providers, exposing them in a deterministic order (builtin first, then sorted
by name).

Design rules
------------
- The ``builtin`` provider is always registered first and is always available.
- Optional providers (mem0, supermemory) self-report their availability; the
  registry never crashes when they are absent.
- Providers augment built-in memory — they never replace it.
- No network calls are made at import or registry-build time; only when
  ``search()`` is called.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class MemoryHit:
    """A single result returned by a provider's ``search`` method.

    Attributes
    ----------
    provider_name:
        Name of the provider that produced this hit (e.g. ``"builtin"``).
    content:
        The text content of the memory entry.
    score:
        Relevance score in ``[0.0, 1.0]``.  Higher is more relevant.
        Providers that do not expose scores should return ``1.0``.
    metadata:
        Optional dict of provider-specific metadata (e.g. tags, kind, id).
    """

    __slots__ = ("content", "metadata", "provider_name", "score")

    def __init__(
        self,
        *,
        provider_name: str,
        content: str,
        score: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.content = content
        self.score = score
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "provider": self.provider_name,
            "content": self.content,
            "score": self.score,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        return (
            f"MemoryHit(provider={self.provider_name!r}, score={self.score:.3f},"
            f" content={self.content[:60]!r})"
        )


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class MemoryProvider(Protocol):
    """Protocol for an external memory-provider adapter.

    All methods must be safe to call when the provider is unavailable — they
    should raise ``RuntimeError`` or return empty results rather than crashing.

    Implementations must be stateless or lazily initialise state on first use.
    """

    @property
    def name(self) -> str:
        """Stable identifier for this provider (e.g. ``"builtin"``, ``"mem0"``)."""
        ...

    def available(self) -> bool:
        """Return True if this provider is ready to serve requests.

        A provider is available when:
        - Its optional dependency is importable, AND
        - Any required credentials (API keys, etc.) are present.

        This check must be fast (no network calls) and side-effect-free.
        """
        ...

    def add(self, entry: str, *, metadata: dict[str, Any] | None = None) -> None:
        """Add a memory entry to this provider's store.

        Parameters
        ----------
        entry:
            The text content to add.
        metadata:
            Optional dict of provider-specific metadata.

        Raises
        ------
        RuntimeError
            When the provider is unavailable or the operation fails.
        """
        ...

    def search(self, query: str, *, limit: int = 10) -> list[MemoryHit]:
        """Return up to *limit* hits relevant to *query*.

        Results are attributed to this provider via :attr:`MemoryHit.provider_name`.
        Returns an empty list when the provider is unavailable or has no results.

        Parameters
        ----------
        query:
            Free-text search query.
        limit:
            Maximum number of hits to return.
        """
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ProviderRegistry:
    """Discovers and caches all registered memory providers.

    Providers are discovered lazily on first access (``providers`` property or
    ``search``).  The registry is not a singleton — callers that need process-wide
    sharing should use :func:`get_registry` instead.
    """

    def __init__(self) -> None:
        self._providers: list[MemoryProvider] | None = None

    def _build(self) -> list[MemoryProvider]:
        """Import and instantiate all providers.  Called once on first access."""
        from oh_no_my_claudecode.memprovider.adapters import (  # noqa: PLC0415
            BuiltinMemoryProvider,
            Mem0MemoryProvider,
            SupermemoryProvider,
        )

        all_providers: list[MemoryProvider] = [
            BuiltinMemoryProvider(),  # always first
        ]

        # Optional providers — import errors are already swallowed inside the
        # adapter module; we catch any remaining surprises here.
        for cls in (Mem0MemoryProvider, SupermemoryProvider):
            try:
                all_providers.append(cls())
            except Exception:  # noqa: BLE001
                logger.debug("memprovider: failed to instantiate %s", cls.__name__, exc_info=True)

        return all_providers

    @property
    def providers(self) -> list[MemoryProvider]:
        """All registered providers in deterministic order (builtin first)."""
        if self._providers is None:
            self._providers = self._build()
        return self._providers

    def available_providers(self) -> list[MemoryProvider]:
        """Return only providers that report :meth:`~MemoryProvider.available`."""
        return [p for p in self.providers if p.available()]

    def get(self, name: str) -> MemoryProvider | None:
        """Return the provider with *name*, or ``None`` if not registered."""
        for p in self.providers:
            if p.name == name:
                return p
        return None

    def search(
        self,
        query: str,
        *,
        provider: str | None = None,
        limit: int = 10,
    ) -> list[MemoryHit]:
        """Search across available providers, attributed by name.

        Parameters
        ----------
        query:
            Free-text search query.
        provider:
            When set, restrict search to the provider with this name.
            Raises :exc:`ValueError` when the name is unknown.
        limit:
            Maximum number of hits **per provider**.
        """
        if provider is not None:
            p = self.get(provider)
            if p is None:
                avail = [x.name for x in self.providers]
                msg = f"unknown provider {provider!r}; available: {avail}"
                raise ValueError(msg)
            if not p.available():
                return []
            return p.search(query, limit=limit)

        hits: list[MemoryHit] = []
        for p in self.available_providers():
            try:
                hits.extend(p.search(query, limit=limit))
            except Exception:  # noqa: BLE001
                logger.debug("memprovider: %s.search() raised", p.name, exc_info=True)
        return hits


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_REGISTRY: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    """Return the process-wide :class:`ProviderRegistry` singleton.

    The registry is built lazily on first access and cached for the lifetime
    of the process.  Tests may reset it by calling :func:`_reset_registry`.
    """
    global _REGISTRY  # noqa: PLW0603
    if _REGISTRY is None:
        _REGISTRY = ProviderRegistry()
    return _REGISTRY


def _reset_registry() -> None:
    """Reset the process-wide registry singleton.  For testing only."""
    global _REGISTRY  # noqa: PLW0603
    _REGISTRY = None
