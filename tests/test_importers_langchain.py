"""Tests for the optional LangChain document-loader importer.

All tests are OFFLINE — no network, no real loaders hitting URLs or files
requiring the internet.  Real-library tests use ``pytest.importorskip`` and
inject fake ``Document`` objects via monkeypatching.  The no-langchain path
(``available() == False``) is exercised unconditionally.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from oh_no_my_claudecode.importers import ImportResult, run_import
from oh_no_my_claudecode.importers.langchain_loader import (
    _derive_title,
    available,
    parse_with_loader,
)
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

# ── Minimal fake Document (mirrors LangChain's Document interface) ─────────────


class _FakeDocument:
    """Minimal stand-in for ``langchain_core.documents.Document``."""

    def __init__(self, page_content: str, metadata: dict[str, Any] | None = None) -> None:
        self.page_content = page_content
        self.metadata: dict[str, Any] = metadata or {}


class _FakeLoader:
    """Fake LangChain loader — returns canned Documents, never touches the network."""

    def __init__(self, docs: list[_FakeDocument]) -> None:
        self._docs = docs

    def load(self) -> list[_FakeDocument]:
        return list(self._docs)


class _FakeSplitter:
    """Fake text splitter — splits each document into two halves."""

    def split_documents(self, docs: list[Any]) -> list[Any]:
        result: list[_FakeDocument] = []
        for doc in docs:
            content: str = doc.page_content
            mid = max(1, len(content) // 2)
            result.append(_FakeDocument(content[:mid], doc.metadata))
            result.append(_FakeDocument(content[mid:], doc.metadata))
        return result


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def brain(tmp_path: Path) -> SQLiteStorage:
    db = tmp_path / "brain.db"
    storage = SQLiteStorage(db)
    storage.initialize()
    return storage


@pytest.fixture()
def canned_docs() -> list[_FakeDocument]:
    return [
        _FakeDocument("First chunk content.", {"source": "fake.pdf"}),
        _FakeDocument("Second chunk content.", {"source": "fake.pdf"}),
    ]


@pytest.fixture()
def fake_loader(canned_docs: list[_FakeDocument]) -> _FakeLoader:
    return _FakeLoader(canned_docs)


# ── Test 1: available() returns False when extra absent ───────────────────────


class TestAvailableWithoutExtra:
    """These tests always run regardless of whether the extra is installed."""

    def test_available_returns_bool(self) -> None:
        result = available()
        assert isinstance(result, bool)

    def test_parse_with_loader_raises_runtime_error_when_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, fake_loader: _FakeLoader
    ) -> None:
        """When available() is False, parse_with_loader must raise RuntimeError."""
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers.langchain_loader.available",
            lambda: False,
        )
        with pytest.raises(RuntimeError, match="langchain"):
            parse_with_loader(fake_loader)

    def test_run_import_raises_value_error_when_unavailable(
        self, brain: SQLiteStorage, monkeypatch: pytest.MonkeyPatch, fake_loader: _FakeLoader
    ) -> None:
        """run_import(source='langchain') raises ValueError when extra absent."""
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers._langchain.available",
            lambda: False,
        )
        with pytest.raises(ValueError, match="langchain"):
            run_import(brain, "langchain", loader=fake_loader)

    def test_run_import_without_loader_raises_value_error(
        self, brain: SQLiteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_import(source='langchain') with no loader raises ValueError."""
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers._langchain.available",
            lambda: True,
        )
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers.langchain_loader.available",
            lambda: True,
        )
        with pytest.raises(ValueError, match="loader"):
            run_import(brain, "langchain", loader=None)

    def test_existing_importers_unaffected(self, brain: SQLiteStorage, tmp_path: Path) -> None:
        """omc/hermes/markdown importers continue to work regardless of langchain."""
        md = tmp_path / "MEMORY.md"
        md.write_text("## Fact\n\nSome detail.", encoding="utf-8")
        result = run_import(brain, "hermes", md, as_kind="memory")
        assert isinstance(result, ImportResult)
        assert result.as_kind == "memory"


# ── Tests 2-6: Injected fake loader → documents become memory candidates ──────
# These tests monkeypatch available()=True and inject a fake splitter/loader
# so NO real langchain code paths are invoked.


class TestParseWithFakeLoader:
    """Core contract tests using an injected fake loader."""

    def _patch_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers.langchain_loader.available",
            lambda: True,
        )
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers.langchain_loader._default_splitter",
            lambda: None,  # no splitter — docs used as-is
        )

    def test_documents_become_memory_entries(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_loader: _FakeLoader,
    ) -> None:
        self._patch_available(monkeypatch)
        memories = parse_with_loader(fake_loader, source_ref="test-source")
        assert len(memories) == 2  # noqa: PLR2004
        for mem in memories:
            assert isinstance(mem, MemoryEntry)

    def test_memory_entries_correct_shape(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_loader: _FakeLoader,
    ) -> None:
        self._patch_available(monkeypatch)
        memories = parse_with_loader(fake_loader, source_ref="test-source")
        first = memories[0]
        assert first.source_ref == "test-source"
        assert first.source_type == SourceType.MANUAL_SEED
        assert first.kind == MemoryKind.DOC_FACT
        assert "imported:langchain" in first.tags
        assert 0.0 <= first.confidence <= 1.0

    def test_memory_ids_are_stable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        canned_docs: list[_FakeDocument],
    ) -> None:
        """Calling parse_with_loader twice on identical docs yields the same IDs."""
        self._patch_available(monkeypatch)
        loader_a = _FakeLoader(canned_docs)
        loader_b = _FakeLoader(canned_docs)
        ids_a = {m.id for m in parse_with_loader(loader_a, source_ref="test-source")}
        ids_b = {m.id for m in parse_with_loader(loader_b, source_ref="test-source")}
        assert ids_a == ids_b

    def test_duplicate_docs_deduped(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Documents whose stable_id collides (same content, same derived title) are deduped."""
        self._patch_available(monkeypatch)
        # Two docs with no source metadata → title falls back to "dup-source chunk 0"
        # for index=0.  Feed the same doc twice in its own loader so both items
        # hit the seen-set guard with an identical ID.
        same_doc = _FakeDocument("Identical content here.", {})
        loader = _FakeLoader([same_doc, same_doc])
        memories = parse_with_loader(loader, source_ref="dup-source")
        # Both docs produce the same stable_id → deduplicated to 1 entry.
        assert len(memories) == 1

    def test_custom_splitter_applied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        canned_docs: list[_FakeDocument],
    ) -> None:
        """A custom splitter is honoured — each doc is split into 2 halves."""
        self._patch_available(monkeypatch)
        loader = _FakeLoader(canned_docs)
        splitter = _FakeSplitter()
        memories = parse_with_loader(loader, splitter=splitter, source_ref="split-source")
        # 2 docs × 2 halves = 4 chunks
        assert len(memories) == 4  # noqa: PLR2004

    def test_empty_content_skipped(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Documents with only whitespace content are silently skipped."""
        self._patch_available(monkeypatch)
        loader = _FakeLoader([
            _FakeDocument("   \n", {"source": "empty.pdf"}),
            _FakeDocument("Real content.", {"source": "real.pdf"}),
        ])
        memories = parse_with_loader(loader, source_ref="whitespace-test")
        assert len(memories) == 1
        assert "Real content." in memories[0].details

    def test_graceful_on_loader_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A loader that raises is propagated — caller decides how to handle."""
        self._patch_available(monkeypatch)

        class _BrokenLoader:
            def load(self) -> list[Any]:
                msg = "network unavailable"
                raise OSError(msg)

        with pytest.raises(OSError, match="network"):
            parse_with_loader(_BrokenLoader(), source_ref="broken")

    def test_run_import_langchain_writes_memories(
        self,
        brain: SQLiteStorage,
        monkeypatch: pytest.MonkeyPatch,
        fake_loader: _FakeLoader,
    ) -> None:
        """run_import(source='langchain') with fake loader writes memories to storage."""
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers._langchain.available",
            lambda: True,
        )
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers.langchain_loader.available",
            lambda: True,
        )
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers.langchain_loader._default_splitter",
            lambda: None,
        )
        result = run_import(brain, "langchain", loader=fake_loader)
        assert isinstance(result, ImportResult)
        assert result.source == "langchain"
        assert result.as_kind == "memory"
        assert result.imported == 2  # noqa: PLR2004
        assert result.skipped == 0
        assert result.dry_run is False

    def test_run_import_langchain_dedup(
        self,
        brain: SQLiteStorage,
        monkeypatch: pytest.MonkeyPatch,
        fake_loader: _FakeLoader,
    ) -> None:
        """Second import of identical docs skips them (dedup by stable id)."""
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers._langchain.available",
            lambda: True,
        )
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers.langchain_loader.available",
            lambda: True,
        )
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers.langchain_loader._default_splitter",
            lambda: None,
        )
        run_import(brain, "langchain", loader=fake_loader)
        result = run_import(brain, "langchain", loader=fake_loader)
        assert result.imported == 0
        assert result.skipped == 2  # noqa: PLR2004

    def test_run_import_langchain_dry_run(
        self,
        brain: SQLiteStorage,
        monkeypatch: pytest.MonkeyPatch,
        fake_loader: _FakeLoader,
    ) -> None:
        """Dry-run mode parses but writes nothing."""
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers._langchain.available",
            lambda: True,
        )
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers.langchain_loader.available",
            lambda: True,
        )
        monkeypatch.setattr(
            "oh_no_my_claudecode.importers.langchain_loader._default_splitter",
            lambda: None,
        )
        result = run_import(brain, "langchain", loader=fake_loader, dry_run=True)
        assert result.dry_run is True
        assert result.imported == 0
        assert result.skipped == 0
        assert len(result.items) == 2  # noqa: PLR2004


# ── Title derivation helper tests ─────────────────────────────────────────────


class TestDeriveTitleHelper:
    def test_uses_source_metadata_key(self) -> None:
        title = _derive_title({"source": "myfile.pdf"}, "ref", 0)
        assert title == "myfile.pdf"

    def test_uses_title_metadata_key_when_source_absent(self) -> None:
        title = _derive_title({"title": "My Doc"}, "ref", 0)
        assert title == "My Doc"

    def test_appends_index_for_nonzero(self) -> None:
        title = _derive_title({"source": "myfile.pdf"}, "ref", 3)
        assert "[3]" in title

    def test_fallback_to_source_ref_and_index(self) -> None:
        title = _derive_title({}, "my-ref", 5)
        assert "my-ref" in title
        assert "5" in title


# ── Real-library smoke test (skipped when extra absent) ───────────────────────


class TestRealLangchainSmoke:
    """Skipped unless ``langchain_community`` is actually importable."""

    def test_available_true_when_extra_installed(self) -> None:
        pytest.importorskip("langchain_community")
        pytest.importorskip("langchain_text_splitters")
        assert available() is True

    def test_real_text_loader_offline(self, tmp_path: Path) -> None:
        """TextLoader on a local file — pure filesystem, no network."""
        pytest.importorskip("langchain_community")
        from langchain_community.document_loaders import (  # type: ignore[import-not-found]
            TextLoader,
        )

        sample = tmp_path / "sample.txt"
        sample.write_text("Line one.\nLine two.\n", encoding="utf-8")

        loader = TextLoader(str(sample))
        memories = parse_with_loader(loader, source_ref=str(sample))
        assert len(memories) >= 1
        assert any("Line one" in m.details for m in memories)
