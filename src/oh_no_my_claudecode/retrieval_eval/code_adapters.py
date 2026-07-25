"""Retrieval-eval adapters for the frozen code-retrieval split.

Four surfaces exist so the claim-protocol ablation "BM25 versus dense versus
graph versus fused retrieval" is *runnable*:

``CodeLexicalAdapter``
    Surface ``"code-bm25"`` — BM25 only.  Indexes each code chunk as
    ``"{symbol} {path} {first_paragraph_of_content}"``.  Measures pure
    lexical matching on code.

``CodeDenseAdapter``
    Surface ``"code-dense"`` — dense embeddings only, no lexical index at all.
    Uses :class:`~oh_no_my_claudecode.retrieval.dense.DenseRetriever` with the
    *same* embedder resolution as the hybrid surface, so the dense-vs-hybrid
    delta is attributable to fusion alone.  Skips (never falls back to BM25)
    when embeddings are disabled.

``CodeHybridAdapter``
    Surface ``"code-hybrid"`` — BM25 + dense + RRF.  Same corpus text as
    the lexical adapter, but also uses the dense embedder (FastEmbed when
    available, HashNgramEmbedder otherwise).

``CodeGraphAdapter``
    Surface ``"code-graph"`` — graph-only retrieval.  Reports SKIPPED with the
    machine-readable code ``no_graph_query_ranker``: no graph primitive in this
    repo ranks chunks from a natural-language query (see
    :data:`SKIP_CODE_GRAPH` for the full reasoning).  A skipped surface is a
    correct result; a fabricated one would corrupt the ablation.

All adapters:
- Are offline, deterministic, and produce no network calls.
- Accept a :class:`~oh_no_my_claudecode.retrieval_eval.code_dataset.CodeRetrievalDataset`
  via a ``setup()`` that accepts a duck-typed dataset (the runner passes a
  ``RetrievalDataset`` but these adapters only need ``.corpus``).
- Reuse the shipped retrieval primitives in
  :mod:`oh_no_my_claudecode.retrieval` — no new retriever is written here.

Label sets
----------
The frozen dataset carries cases for ``code-bm25`` and ``code-hybrid`` only,
with *identical* query text and ``relevant_ids`` in both (asserted by
``tests/test_retrieval_eval_code.py::test_parallel_cases_share_query_text``) —
labels are a property of the dataset, not of the retriever.  ``code-dense``
therefore declares ``case_surface = "code-bm25"`` and the runner scores it on
that same frozen label set without editing the dataset.

Usage in the runner
-------------------
The runner calls ``setup(dataset)`` then ``retrieve(query, k)``.  All adapters
expect the dataset to expose a ``.corpus`` iterable of
:class:`~oh_no_my_claudecode.retrieval_eval.code_dataset.CodeCorpusEntry`.
The ``--split code`` CLI path passes a :class:`CodeRetrievalDataset`;
for integration tests a minimal duck-type also works.
"""

from __future__ import annotations

from oh_no_my_claudecode.embeddings.core import embeddings_enabled
from oh_no_my_claudecode.retrieval.core import HybridRetriever
from oh_no_my_claudecode.retrieval.dense import DenseRetriever
from oh_no_my_claudecode.retrieval_eval.code_dataset import (
    CodeCorpusEntry,
    CodeRetrievalDataset,
)
from oh_no_my_claudecode.retrieval_eval.runner import BaselineAdapter, SurfaceSkip

# ---------------------------------------------------------------------------
# Typed skip reasons
# ---------------------------------------------------------------------------

SKIP_EMBEDDINGS_DISABLED = SurfaceSkip(
    code="embeddings_disabled",
    reason=(
        "ONMC_EMBEDDINGS=0 — embeddings are disabled, so no dense ranking can be "
        "computed.  This surface refuses to fall back to a lexical retriever: a "
        "'dense' surface that was secretly BM25 would make the ablation lie."
    ),
)

SKIP_CODE_GRAPH = SurfaceSkip(
    code="no_graph_query_ranker",
    reason=(
        "no graph retrieval primitive can rank the frozen code corpus from a query. "
        "(1) Every graph primitive needs a seed, not a query: "
        "codeindex.query.neighbors/callers/callees take a chunk_id or symbol, and "
        "codegraph.builder.neighbors takes a file or symbol — seeding them from BM25 "
        "would make 'graph-only' secretly BM25+graph. "
        "(2) The one query-taking function, codegraph.builder.context_files, ranks "
        "files (18 here) not chunks (149) and scores path/symbol token overlap "
        "without consulting a single graph edge — a lexical ranker, not graph "
        "retrieval, and it yields no chunk-level order to score against chunk-id "
        "labels. "
        "(3) The frozen corpus holds only function/method/class chunks, so it "
        "contains no import or call edges to build a graph from; rebuilding from the "
        "working tree is non-deterministic and breaks the id join (chunk ids embed "
        "the git blob SHA, so they drift on every edit to an in-scope file). "
        "Implementing a query-to-node ranker would mean writing a new retriever and "
        "reporting invented numbers, so this surface is honestly skipped instead."
    ),
)


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
        self._dense: DenseRetriever | None = None
        self._tokens: dict[str, int] = {}

    def context_tokens(self, ranked_ids: list[str]) -> int:
        """Sum the real per-chunk token estimates for the retrieved chunks."""
        return sum(self._tokens.get(doc_id, 0) for doc_id in ranked_ids)

    def teardown(self) -> None:
        self._retriever = None
        self._dense = None
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


class CodeDenseAdapter(_CodeAdapterBase):
    """Dense-only adapter for the ``"code-dense"`` evaluation surface.

    Ranks the frozen code corpus by embedding cosine similarity alone, using the
    shipped :class:`~oh_no_my_claudecode.retrieval.dense.DenseRetriever` — the
    exact same component the hybrid surface fuses.  No BM25 index is ever
    constructed here, so this surface *cannot* silently degrade into the lexical
    baseline.

    Embedder resolution is delegated to
    :func:`~oh_no_my_claudecode.embeddings.core.get_embedder` (by passing
    ``embedder=None``), identical to what ``HybridRetriever`` does.  The
    dense-vs-hybrid delta is therefore attributable to fusion, not to a
    different embedding backend.  The resolved ``embedder_id`` is reported as
    provenance so a hash-ngram run is never mistaken for a neural one.

    Skipped (never scored as 0.0) when ``ONMC_EMBEDDINGS=0``.

    Scored on the frozen ``code-bm25`` label set — see the module docstring.
    Offline, deterministic, no network calls: the default embedder is SHA-256
    based and :meth:`DenseRetriever.retrieve` breaks score ties on doc_id, so
    reruns reproduce exactly with no seed to set.
    """

    surface_name = "code-dense"
    case_surface = "code-bm25"

    def precheck(self) -> SurfaceSkip | None:
        """Skip rather than fall back to lexical when embeddings are disabled."""
        if not embeddings_enabled():
            return SKIP_EMBEDDINGS_DISABLED
        return None

    def setup(self, dataset: CodeRetrievalDataset) -> None:  # type: ignore[override]
        """Build the dense (embedding-only) index over all code corpus chunks."""
        corpus = list(dataset.corpus)
        self._dense = DenseRetriever(
            doc_ids=[e.id for e in corpus],
            texts=[_chunk_text(e) for e in corpus],
            embedder=None,  # same resolution as HybridRetriever
        )
        self._tokens = _token_map(corpus)

    def retrieve(self, query: str, k: int) -> list[str]:
        """Return up to *k* chunk IDs ranked by embedding cosine similarity."""
        if self._dense is None:
            return []
        return [doc_id for doc_id, _score in self._dense.retrieve(query, k)]

    def provenance(self) -> str:
        """Report the embedder actually used, so 'dense' cannot be over-read."""
        if self._dense is None:
            return "dense-only (embedding cosine similarity)"
        return f"dense-only (embedding cosine similarity), embedder={self._dense.embedder_id}"


class CodeGraphAdapter(_CodeAdapterBase):
    """Graph-only surface ``"code-graph"`` — always SKIPPED, never fabricated.

    ONMC has graph *structure* (``codegraph`` import/blast-radius edges,
    ``codeindex`` call edges) but no primitive that ranks corpus chunks from a
    natural-language query, which is what this evaluation surface requires.  See
    :data:`SKIP_CODE_GRAPH` for the three independent reasons.

    Rather than inventing a ranker (and thereby inventing metrics), this adapter
    declares the surface unmeasurable via :meth:`precheck`.  :meth:`retrieve`
    raises so that no code path can ever turn this absence into a row of zeros.
    """

    surface_name = "code-graph"

    def precheck(self) -> SurfaceSkip | None:
        """Always skip: no query-to-chunk graph ranking primitive exists."""
        return SKIP_CODE_GRAPH

    def retrieve(self, query: str, k: int) -> list[str]:
        """Always raises — an unmeasurable surface must not return empty results.

        Returning ``[]`` here would be scored as recall 0.0 and would read as
        "graph retrieval is bad" instead of "graph retrieval is unimplemented".
        """
        raise NotImplementedError(SKIP_CODE_GRAPH.reason)


def code_adapters() -> list[BaselineAdapter]:
    """Return the pair of frozen baseline code-split adapters (lexical + hybrid).

    This is the *baseline* set whose numbers are pinned; it deliberately stays
    two-element so the frozen baseline can be reproduced in isolation.  For the
    full four-way ablation use :func:`code_ablation_adapters`.
    """
    return [CodeLexicalAdapter(), CodeHybridAdapter()]


def code_ablation_adapters() -> list[BaselineAdapter]:
    """Return all four code-split surfaces: BM25, hybrid, dense, graph.

    Ordered so the two pinned baseline surfaces come first and the additive
    ablation surfaces follow.  ``code-graph`` is always reported as SKIPPED with
    a machine-readable reason (see :data:`SKIP_CODE_GRAPH`), and ``code-dense``
    is skipped when ``ONMC_EMBEDDINGS=0``.
    """
    return [
        CodeLexicalAdapter(),
        CodeHybridAdapter(),
        CodeDenseAdapter(),
        CodeGraphAdapter(),
    ]
