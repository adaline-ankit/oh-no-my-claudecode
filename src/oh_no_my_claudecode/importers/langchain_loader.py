"""Optional LangChain document-loader importer.

Uses LangChain's document loaders and text splitters to ingest external
sources (PDFs, web pages, notebooks, directories) into onmc memory
candidates.

This module is a **no-op** when the ``langchain`` optional extra is absent —
:func:`available` returns ``False`` and no import of ``langchain_community``
or ``langchain_text_splitters`` is attempted at module load time.

Usage (extra installed)::

    from oh_no_my_claudecode.importers.langchain_loader import (
        available,
        parse_with_loader,
    )

    if available():
        from langchain_community.document_loaders import TextLoader
        docs = parse_with_loader(TextLoader("/path/to/file.txt"))

The integration is exposed through :func:`~oh_no_my_claudecode.importers.run_import`
via ``source="langchain"`` — callers supply the loader instance via *loader*
and an optional splitter via *splitter*.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now

if TYPE_CHECKING:
    pass

_IMPORT_TAG = "imported:langchain"


def available() -> bool:
    """Return ``True`` when the ``langchain`` optional extra is importable.

    Pure import check — does not instantiate any loader or model.
    """
    try:
        import langchain_community  # noqa: F401, PLC0415
        import langchain_text_splitters  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


def _default_splitter() -> Any:
    """Return a ``RecursiveCharacterTextSplitter`` with sensible defaults.

    Returns ``None`` when the extra is unavailable (callers must guard).
    Chunk size 1000, overlap 100, producing chunks ≤ 1000 characters.
    """
    try:
        from langchain_text_splitters import (  # noqa: PLC0415
            RecursiveCharacterTextSplitter,
        )
    except ImportError:
        return None
    return RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)


def parse_with_loader(
    loader: Any,
    *,
    splitter: Any = None,
    source_ref: str = "langchain",
) -> list[MemoryEntry]:
    """Load documents via *loader*, split via *splitter*, return :class:`MemoryEntry` objects.

    Parameters
    ----------
    loader:
        Any LangChain-compatible document loader (must implement ``.load()``
        returning a list of ``Document`` objects with ``.page_content`` and
        ``.metadata``).
    splitter:
        A LangChain text splitter that accepts a list of ``Document`` objects
        and returns split ``Document`` objects (must implement
        ``.split_documents(docs)``).  When ``None`` the
        :func:`_default_splitter` is used if the extra is available; if the
        extra is unavailable the documents are used as-is.
    source_ref:
        Human-readable label for the source (used in ``MemoryEntry.source_ref``
        and dedup hashing).  Defaults to ``"langchain"``.

    Returns
    -------
    list[MemoryEntry]
        One entry per document chunk.  Duplicates (by stable id) are silently
        dropped.

    Raises
    ------
    RuntimeError
        When the ``langchain`` extra is absent and this function is called.
    """
    if not available():
        msg = (
            "The 'langchain' extra is required for parse_with_loader(). "
            "Install it with: pip install 'oh-no-my-claudecode[langchain]'"
        )
        raise RuntimeError(msg)

    docs = loader.load()

    # Apply splitter when provided; fall back to default splitter.
    effective_splitter = splitter if splitter is not None else _default_splitter()
    if effective_splitter is not None:
        docs = effective_splitter.split_documents(docs)

    memories: list[MemoryEntry] = []
    seen: set[str] = set()
    now = utc_now()

    for i, doc in enumerate(docs):
        content: str = doc.page_content if hasattr(doc, "page_content") else str(doc)
        if not content.strip():
            continue

        metadata: dict[str, Any] = doc.metadata if hasattr(doc, "metadata") else {}
        title = _derive_title(metadata, source_ref, i)
        summary = content[:200].strip()

        entry_id = stable_id("langchain", source_ref, content[:256], prefix="mem")
        if entry_id in seen:
            continue
        seen.add(entry_id)

        memories.append(
            MemoryEntry(
                id=entry_id,
                kind=MemoryKind.DOC_FACT,
                title=title,
                summary=summary,
                details=content,
                source_type=SourceType.MANUAL_SEED,
                source_ref=source_ref,
                tags=[_IMPORT_TAG],
                confidence=0.6,
                feedback_score=0.0,
                created_at=now,
                updated_at=now,
            )
        )

    return memories


def _derive_title(metadata: dict[str, Any], source_ref: str, index: int) -> str:
    """Derive a human-readable title from LangChain document metadata.

    Tries ``metadata["source"]`` (file path), then ``metadata["title"]``,
    then falls back to ``"{source_ref} chunk {index}"``.
    """
    src = metadata.get("source") or metadata.get("title")
    if src:
        return f"{src}" if index == 0 else f"{src} [{index}]"
    return f"{source_ref} chunk {index}"
