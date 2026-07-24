"""Retrieval-eval adapters for the frozen code-retrieval split.

Two adapters are provided so lexical-only (BM25) and hybrid (BM25+dense+RRF)
retrieval can be compared against the same frozen code dataset:

``CodeLexicalAdapter``
    Surface ``"code-bm25"`` — BM25 only.  Indexes each code chunk as
    ``"{symbol} {path} {first_paragraph_of_content}"``.  Measures pure
    lexical matching on code.

``CodeHybridAdapter``
    Surface ``"code-hybrid"`` — BM25 + dense + RRF.  Same corpus text as
    the lexical adapter, but also uses the dense embedder (FastEmbed when
    available, HashNgramEmbedder otherwise).

Both adapters:
- Are offline and produce no network calls.
- Accept a :class:`~oh_no_my_claudecode.retrieval_eval.code_dataset.CodeRetrievalDataset`
  via a monkey-patched ``setup()`` that accepts a duck-typed dataset (the runner
  passes a ``RetrievalDataset`` but this adapter only needs ``.corpus``).
- Use the shared :class:`~oh_no_my_claudecode.retrieval.core.HybridRetriever`
  with ``mode="bm25"`` or ``mode="hybrid"``.

Usage in the runner
-------------------
The runner calls ``setup(dataset)`` then ``retrieve(query, k)``.  Both adapters
expect the dataset to expose a ``.corpus`` iterable of
:class:`~oh_no_my_claudecode.retrieval_eval.code_dataset.CodeCorpusEntry`.
The ``--split code`` CLI path passes a :class:`CodeRetrievalDataset`;
for integration tests a minimal duck-type also works.
"""

from __future__ import annotations

from oh_no_my_claudecode.retrieval.core import HybridRetriever
from oh_no_my_claudecode.retrieval_eval.code_dataset import (
    CodeCorpusEntry,
    CodeRetrievalDataset,
)
from oh_no_my_claudecode.retrieval_eval.runner import BaselineAdapter


def _chunk_text(entry: CodeCorpusEntry) -> str:
    """Build the searchable text for a code chunk.

    Combines: symbol name, file path (basename), and the first paragraph of
    the chunk content (up to 60 lines).  The symbol name and path are placed
    first so BM25's positional scoring slightly up-weights exact-name matches,
    mirroring how developers search code by symbol or file name.
    """
    import os  # noqa: PLC0415

    basename = os.path.basename(entry.path)
    # Limit content to first 60 lines to keep index compact; docstrings are
    # typically in the first ~10 lines which contain the richest signal.
    content_head = "\n".join(entry.content.splitlines()[:60])
    return f"{entry.symbol} {basename} {content_head}".strip()


def _chunk_evidence(entry: CodeCorpusEntry) -> str:
    """Short citation text for retrieval hit provenance."""
    return f"[{entry.kind}] {entry.symbol} ({entry.path}:{entry.start_line}-{entry.end_line})"


def _build_retriever(corpus: list[CodeCorpusEntry]) -> HybridRetriever:
    """Build a HybridRetriever over the code corpus."""
    doc_ids = [e.id for e in corpus]
    texts = [_chunk_text(e) for e in corpus]
    evidence = [_chunk_evidence(e) for e in corpus]
    return HybridRetriever(doc_ids=doc_ids, texts=texts, evidence_texts=evidence)


def _token_map(corpus: list[CodeCorpusEntry]) -> dict[str, int]:
    """Per-chunk token estimate (~chars/4) for context-token accounting."""
    return {e.id: max(1, len(e.content) // 4) for e in corpus}


class _CodeAdapterBase(BaselineAdapter):
    """Shared corpus + real context-token accounting for code adapters."""

    def __init__(self) -> None:
        self._retriever: HybridRetriever | None = None
        self._tokens: dict[str, int] = {}

    def context_tokens(self, ranked_ids: list[str]) -> int:
        """Sum the real per-chunk token estimates for the retrieved chunks."""
        return sum(self._tokens.get(doc_id, 0) for doc_id in ranked_ids)

    def teardown(self) -> None:
        self._retriever = None
        self._tokens = {}


class CodeLexicalAdapter(_CodeAdapterBase):
    """BM25-only adapter for the ``"code-bm25"`` evaluation surface.

    Indexes all code corpus chunks with BM25 and scores the 40 labeled
    code-bm25 cases.  Dense embeddings are NOT used — this is the lexical
    baseline for code retrieval.

    Offline, deterministic, no network calls.
    """

    surface_name = "code-bm25"

    def setup(self, dataset: CodeRetrievalDataset) -> None:  # type: ignore[override]
        """Build BM25 index over all code corpus chunks."""
        corpus = list(dataset.corpus)
        self._retriever = _build_retriever(corpus)
        self._tokens = _token_map(corpus)

    def retrieve(self, query: str, k: int) -> list[str]:
        """Return up to *k* chunk IDs ranked by BM25 score (lexical only)."""
        if self._retriever is None:
            return []
        hits = self._retriever.retrieve(query, k, mode="bm25")
        return [h.doc_id for h in hits]


class CodeHybridAdapter(_CodeAdapterBase):
    """BM25 + dense + RRF adapter for the ``"code-hybrid"`` evaluation surface.

    Identical corpus to :class:`CodeLexicalAdapter` but uses full hybrid
    retrieval (BM25 + dense embedder + Reciprocal Rank Fusion).  FastEmbed is
    used when available and ``ONMC_EMBEDDER=fastembed`` is set; otherwise
    falls back to ``HashNgramEmbedder`` (zero dependencies).

    Comparing this adapter against :class:`CodeLexicalAdapter` on the same
    underlying queries directly measures the hybrid improvement on code retrieval.
    """

    surface_name = "code-hybrid"

    def setup(self, dataset: CodeRetrievalDataset) -> None:  # type: ignore[override]
        """Build BM25 + dense index over all code corpus chunks."""
        corpus = list(dataset.corpus)
        self._retriever = _build_retriever(corpus)
        self._tokens = _token_map(corpus)

    def retrieve(self, query: str, k: int) -> list[str]:
        """Return up to *k* chunk IDs ranked by BM25+dense+RRF score."""
        if self._retriever is None:
            return []
        hits = self._retriever.retrieve(query, k, mode="hybrid")
        return [h.doc_id for h in hits]


def code_adapters() -> list[BaselineAdapter]:
    """Return the pair of code-split adapters (lexical + hybrid)."""
    return [CodeLexicalAdapter(), CodeHybridAdapter()]
