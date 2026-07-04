"""External memory-provider adapter interface.

Defines a :class:`MemoryProvider` Protocol that allows external memory backends
(Mem0, Supermemory, etc.) to augment onmc's built-in memory store.  Providers
are discovered automatically and run **alongside** the built-in store — they
never replace it.

Built-in adapters
-----------------
``builtin``
    Always available.  Wraps onmc's own SQLite memory store.

``mem0``
    Optional.  Available when the ``mem0ai`` package is installed **and** an
    ``MEM0_API_KEY`` environment variable is set.  Add with::

        pip install oh-no-my-claudecode[mem0]

``supermemory``
    Optional.  Available when the ``supermemory`` package is installed **and**
    a ``SUPERMEMORY_API_KEY`` environment variable is set.  Add with::

        pip install oh-no-my-claudecode[supermemory]

CLI surface
-----------
``onmc memprovider list``
    List all registered providers and their availability.

``onmc memprovider search <query> [--provider <name>] [--json]``
    Query across available providers; hits are attributed to their source provider.
"""

from oh_no_my_claudecode.memprovider.base import (
    MemoryHit,
    MemoryProvider,
    ProviderRegistry,
    get_registry,
)

__all__ = [
    "MemoryHit",
    "MemoryProvider",
    "ProviderRegistry",
    "get_registry",
]
