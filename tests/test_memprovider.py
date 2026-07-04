"""Tests for the ``onmc memprovider`` external memory-provider adapter interface.

Covers
------
- Protocol conformance: BuiltinMemoryProvider, Mem0MemoryProvider,
  SupermemoryProvider all satisfy the MemoryProvider Protocol at runtime.
- Registry lists all three providers in deterministic order.
- Builtin adapter: add + search works with zero extra dependencies (no
  network, no API key).  Uses a real temporary SQLiteStorage instance.
- mem0 adapter: available() == False when mem0ai is not installed;
  graceful (no crash, empty results) when unavailable.
- supermemory adapter: available() == False when supermemory is not
  installed; graceful (no crash, empty results) when unavailable.
- Injected fake mem0 client: search() returns attributed MemoryHits when
  the extra IS present (monkeypatched — no real network call).
- Injected fake supermemory client: same pattern.
- ``--json`` envelope for ``memprovider list`` and ``memprovider search``
  has expected top-level keys.
- Unknown ``--provider`` raises ValueError from the registry and exits 1 via
  the CLI.
- ``memprovider list`` CLI: reachable, returns exit 0, correct output.
- ``memprovider search`` CLI: reachable, returns exit 0, JSON envelope valid.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from oh_no_my_claudecode.memprovider.adapters import (
    BuiltinMemoryProvider,
    Mem0MemoryProvider,
    SupermemoryProvider,
)
from oh_no_my_claudecode.memprovider.base import (
    MemoryHit,
    MemoryProvider,
    ProviderRegistry,
    _reset_registry,
    get_registry,
)
from oh_no_my_claudecode.memprovider.commands import register
from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cli() -> typer.Typer:
    """Return a fresh CLI app with memprovider registered."""
    app = typer.Typer()
    register(app)
    return app


def _make_storage(tmp_path: Path) -> SQLiteStorage:
    """Create and initialise a real SQLiteStorage backed by a temp file."""
    db_path = tmp_path / "onmc.db"
    storage = SQLiteStorage(db_path)
    storage.initialize()
    return storage


def _make_memory_entry(title: str = "Test memory") -> MemoryEntry:
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC)
    return MemoryEntry(
        id=f"mem-{abs(hash(title)):016x}",
        kind=MemoryKind.DOC_FACT,
        title=title,
        summary=f"Summary of {title}",
        details=f"Details for {title}",
        source_type=SourceType.MANUAL,
        source_ref="test",
        tags=["test"],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# 1. Protocol conformance
# ---------------------------------------------------------------------------


def test_builtin_satisfies_protocol() -> None:
    """BuiltinMemoryProvider satisfies the MemoryProvider Protocol."""
    provider = BuiltinMemoryProvider()
    assert isinstance(provider, MemoryProvider)


def test_mem0_satisfies_protocol() -> None:
    """Mem0MemoryProvider satisfies the MemoryProvider Protocol."""
    provider = Mem0MemoryProvider()
    assert isinstance(provider, MemoryProvider)


def test_supermemory_satisfies_protocol() -> None:
    """SupermemoryProvider satisfies the MemoryProvider Protocol."""
    provider = SupermemoryProvider()
    assert isinstance(provider, MemoryProvider)


# ---------------------------------------------------------------------------
# 2. Registry lists providers in deterministic order
# ---------------------------------------------------------------------------


def test_registry_lists_all_providers() -> None:
    """Registry exposes at least builtin + mem0 + supermemory."""
    _reset_registry()
    registry = ProviderRegistry()
    names = [p.name for p in registry.providers]
    assert names[0] == "builtin", "builtin must be first"
    assert "mem0" in names
    assert "supermemory" in names


def test_registry_singleton_is_same_instance() -> None:
    """get_registry() returns the same instance on repeated calls."""
    _reset_registry()
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2


def test_registry_reset_creates_fresh_instance() -> None:
    """_reset_registry() causes get_registry() to build a fresh registry."""
    _reset_registry()
    r1 = get_registry()
    _reset_registry()
    r2 = get_registry()
    assert r1 is not r2


# ---------------------------------------------------------------------------
# 3. Builtin adapter — add + search (real SQLiteStorage, no network)
# ---------------------------------------------------------------------------


def test_builtin_always_available() -> None:
    """BuiltinMemoryProvider.available() is always True."""
    assert BuiltinMemoryProvider().available() is True


def test_builtin_search_returns_empty_when_no_repo(tmp_path: Path) -> None:
    """Builtin search returns [] gracefully when onmc is not initialised."""
    provider = BuiltinMemoryProvider()
    # _get_storage returns None when repo discovery fails (cwd is tmp_path, no git repo).
    with patch.object(provider, "_get_storage", return_value=None):
        hits = provider.search("anything")
    assert hits == []


def test_builtin_search_returns_hits(tmp_path: Path) -> None:
    """Builtin search returns attributed MemoryHit objects from SQLiteStorage."""
    storage = _make_storage(tmp_path)
    entry = _make_memory_entry("Cache invalidation strategy")
    storage.upsert_memories([entry])

    provider = BuiltinMemoryProvider()
    with patch.object(provider, "_get_storage", return_value=storage):
        hits = provider.search("cache", limit=5)

    assert len(hits) >= 1
    assert all(isinstance(h, MemoryHit) for h in hits)
    assert all(h.provider_name == "builtin" for h in hits)
    contents = " ".join(h.content for h in hits)
    assert "Cache" in contents or "cache" in contents.lower()


def test_builtin_add_raises_when_no_repo() -> None:
    """Builtin add() raises RuntimeError when onmc is not initialised."""
    provider = BuiltinMemoryProvider()
    with (
        patch.object(provider, "_get_storage", return_value=None),
        pytest.raises(RuntimeError, match="not initialised"),
    ):
        provider.add("some text")


def test_builtin_add_stores_entry(tmp_path: Path) -> None:
    """Builtin add() writes a MemoryEntry to the SQLiteStorage."""
    storage = _make_storage(tmp_path)
    provider = BuiltinMemoryProvider()
    with patch.object(provider, "_get_storage", return_value=storage):
        provider.add("ETF allocation in IRA accounts", metadata={"title": "ETF IRA note"})

    all_memories = storage.list_memories()
    assert any("ETF" in m.title or "ETF" in m.summary for m in all_memories)


# ---------------------------------------------------------------------------
# 4. mem0 adapter — available() == False when extra absent
# ---------------------------------------------------------------------------


def test_mem0_unavailable_when_not_installed() -> None:
    """Mem0MemoryProvider.available() is False when mem0ai is not importable."""
    with patch(
        "oh_no_my_claudecode.memprovider.adapters._mem0_importable",
        return_value=False,
    ):
        provider = Mem0MemoryProvider()
        assert provider.available() is False


def test_mem0_search_returns_empty_when_unavailable() -> None:
    """Mem0 search returns [] gracefully when unavailable."""
    provider = Mem0MemoryProvider()
    with patch.object(provider, "available", return_value=False):
        hits = provider.search("anything")
    assert hits == []


def test_mem0_add_raises_when_unavailable() -> None:
    """Mem0 add() raises RuntimeError when unavailable."""
    provider = Mem0MemoryProvider()
    with (
        patch.object(provider, "available", return_value=False),
        pytest.raises(RuntimeError, match="not available"),
    ):
        provider.add("some entry")


# ---------------------------------------------------------------------------
# 5. supermemory adapter — available() == False when extra absent
# ---------------------------------------------------------------------------


def test_supermemory_unavailable_when_not_installed() -> None:
    """SupermemoryProvider.available() is False when supermemory is not importable."""
    with patch(
        "oh_no_my_claudecode.memprovider.adapters._supermemory_importable",
        return_value=False,
    ):
        provider = SupermemoryProvider()
        assert provider.available() is False


def test_supermemory_search_returns_empty_when_unavailable() -> None:
    """Supermemory search returns [] gracefully when unavailable."""
    provider = SupermemoryProvider()
    with patch.object(provider, "available", return_value=False):
        hits = provider.search("anything")
    assert hits == []


def test_supermemory_add_raises_when_unavailable() -> None:
    """Supermemory add() raises RuntimeError when unavailable."""
    provider = SupermemoryProvider()
    with (
        patch.object(provider, "available", return_value=False),
        pytest.raises(RuntimeError, match="not available"),
    ):
        provider.add("some entry")


# ---------------------------------------------------------------------------
# 6. Injected fake mem0 client — search returns attributed hits
# ---------------------------------------------------------------------------


def test_mem0_search_with_fake_client() -> None:
    """Injected fake mem0 client → search() returns attributed MemoryHits."""
    fake_results = [
        {"memory": "ETF recommendations for IRA", "score": 0.92},
        {"memory": "Tax-loss harvesting strategy", "score": 0.85},
    ]
    fake_client = MagicMock()
    fake_client.search.return_value = fake_results

    provider = Mem0MemoryProvider()
    provider._client = fake_client

    with patch.object(provider, "available", return_value=True):
        hits = provider.search("IRA investment", limit=5)

    assert len(hits) == 2
    assert all(isinstance(h, MemoryHit) for h in hits)
    assert all(h.provider_name == "mem0" for h in hits)
    assert hits[0].content == "ETF recommendations for IRA"
    assert abs(hits[0].score - 0.92) < 1e-6
    assert hits[1].content == "Tax-loss harvesting strategy"
    fake_client.search.assert_called_once_with("IRA investment", limit=5)


# ---------------------------------------------------------------------------
# 7. Injected fake supermemory client — search returns attributed hits
# ---------------------------------------------------------------------------


def test_supermemory_search_with_fake_client() -> None:
    """Injected fake supermemory client → search() returns attributed MemoryHits."""

    class _FakeItem:
        content = "Supermemory: cache layer design"
        score = 0.77
        metadata: dict[str, Any] = {"tag": "architecture"}

    fake_response = MagicMock()
    fake_response.results = [_FakeItem()]

    fake_memories = MagicMock()
    fake_memories.search.return_value = fake_response

    fake_client = MagicMock()
    fake_client.memories = fake_memories

    provider = SupermemoryProvider()
    provider._client = fake_client

    with patch.object(provider, "available", return_value=True):
        hits = provider.search("cache design", limit=3)

    assert len(hits) == 1
    assert hits[0].provider_name == "supermemory"
    assert hits[0].content == "Supermemory: cache layer design"
    assert abs(hits[0].score - 0.77) < 1e-6
    fake_memories.search.assert_called_once_with(query="cache design", limit=3)


# ---------------------------------------------------------------------------
# 8. Registry search — unknown provider → ValueError
# ---------------------------------------------------------------------------


def test_registry_search_unknown_provider() -> None:
    """Registry.search() raises ValueError for unknown --provider."""
    _reset_registry()
    registry = ProviderRegistry()
    with pytest.raises(ValueError, match="unknown provider"):
        registry.search("query", provider="nonexistent")


def test_registry_search_across_available() -> None:
    """Registry.search() merges hits from all available providers."""
    _reset_registry()
    registry = ProviderRegistry()

    fake_builtin = MagicMock()
    fake_builtin.name = "builtin"
    fake_builtin.available.return_value = True
    fake_builtin.search.return_value = [
        MemoryHit(provider_name="builtin", content="builtin result", score=0.9)
    ]

    registry._providers = [fake_builtin]

    hits = registry.search("test")
    assert len(hits) == 1
    assert hits[0].provider_name == "builtin"
    assert hits[0].content == "builtin result"


# ---------------------------------------------------------------------------
# 9. --json envelope for CLI commands
# ---------------------------------------------------------------------------


def test_memprovider_list_json() -> None:
    """``memprovider list --json`` emits valid JSON with expected keys."""
    app = _make_cli()
    result = runner.invoke(app, ["memprovider", "list", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "memprovider_list"
    assert isinstance(data["providers"], list)
    assert len(data["providers"]) >= 1
    first = data["providers"][0]
    assert "name" in first
    assert "available" in first
    assert first["name"] == "builtin"
    assert first["available"] is True


def test_memprovider_search_json(tmp_path: Path) -> None:
    """``memprovider search --json`` emits valid JSON with expected envelope."""
    app = _make_cli()

    fake_registry = MagicMock()
    fake_registry.search.return_value = [
        MemoryHit(provider_name="builtin", content="auth bug in session handler", score=0.9)
    ]
    with patch("oh_no_my_claudecode.memprovider.commands.get_registry", return_value=fake_registry):
        result = runner.invoke(app, ["memprovider", "search", "auth bug", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "memprovider_search"
    assert "query" in data
    assert isinstance(data["hits"], list)


# ---------------------------------------------------------------------------
# 10. Unknown --provider graceful via CLI
# ---------------------------------------------------------------------------


def test_cli_unknown_provider_exits_1() -> None:
    """``memprovider search --provider unknown`` exits with code 1."""
    app = _make_cli()
    _reset_registry()
    fake_registry = MagicMock()
    fake_registry.search.side_effect = ValueError("unknown provider 'does_not_exist'")
    with patch("oh_no_my_claudecode.memprovider.commands.get_registry", return_value=fake_registry):
        result = runner.invoke(
            app, ["memprovider", "search", "test query", "--provider", "does_not_exist"]
        )
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# 11. memprovider list CLI: human-readable output
# ---------------------------------------------------------------------------


def test_memprovider_list_human_readable() -> None:
    """``memprovider list`` (no --json) shows PROVIDER and AVAILABLE columns."""
    app = _make_cli()
    result = runner.invoke(app, ["memprovider", "list"])
    assert result.exit_code == 0, result.output
    assert "builtin" in result.output
    assert "yes" in result.output  # builtin is always available


# ---------------------------------------------------------------------------
# 12. MemoryHit.to_dict() structure
# ---------------------------------------------------------------------------


def test_memory_hit_to_dict() -> None:
    """MemoryHit.to_dict() returns a JSON-serialisable dict with all fields."""
    hit = MemoryHit(
        provider_name="builtin",
        content="some memory text",
        score=0.75,
        metadata={"id": "mem-abc", "kind": "doc_fact"},
    )
    d = hit.to_dict()
    assert d["provider"] == "builtin"
    assert d["content"] == "some memory text"
    assert abs(d["score"] - 0.75) < 1e-6
    assert d["metadata"]["id"] == "mem-abc"
    # Verify it is JSON-serialisable
    serialised = json.dumps(d)
    round_tripped = json.loads(serialised)
    assert round_tripped["provider"] == "builtin"
