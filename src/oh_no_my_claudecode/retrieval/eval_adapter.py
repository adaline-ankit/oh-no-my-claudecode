"""Retrieval-eval harness adapters for the hybrid BM25+dense+RRF retriever.

Two adapters are provided so the hybrid system can be measured against the
same frozen dataset cases as the baseline adapters:

``HybridRecallAdapter``
    Surface ``"recall"`` — the same 15 labeled error-matching cases used to
    score ``compile_recall``.  Indexes the evaluation corpus with BM25 + dense
    + RRF, entirely from the corpus entries (no SQLite dependency).

``HybridGuardAdapter``
    Surface ``"guard"`` — the same 10 task dead-end cases used for the guard
    surface.  Same hybrid pipeline.

Both adapters are offline, deterministic, and produce no network calls.
FastEmbed is used when the ``fastembed`` extra is installed and
``ONMC_EMBEDDER=fastembed`` is set; otherwise the zero-dependency
``HashNgramEmbedder`` is used transparently.
"""

from __future__ import annotations

from oh_no_my_claudecode.retrieval.core import HybridRetriever
from oh_no_my_claudecode.retrieval_eval.dataset import CorpusEntry, RetrievalDataset
from oh_no_my_claudecode.retrieval_eval.runner import BaselineAdapter


def _corpus_text(entry: CorpusEntry) -> str:
    """Concatenate all searchable fields of a corpus entry into one string.

    BM25 and the dense embedder both index this combined text.  Field weighting
    is implicit: title appears first so BM25's positional bias slightly
    up-weights it, consistent with the way compile_recall biases by kind.
    """
    tag_str = " ".join(entry.tags)
    return f"{entry.title} {entry.summary} {entry.details} {tag_str}".strip()


def _corpus_evidence(entry: CorpusEntry) -> str:
    """Short citation text surfaced in RetrievalHit.evidence."""
    return f"[{entry.kind}] {entry.title}"


class HybridRecallAdapter(BaselineAdapter):
    """Hybrid BM25+dense+RRF adapter for the ``"recall"`` evaluation surface.

    Measures the hybrid retriever on the same 15 labeled recall cases as the
    ``RecallAdapter`` baseline, allowing direct Recall@k / MRR / nDCG comparison.

    The corpus is indexed from the dataset's ``CorpusEntry`` objects (title +
    summary + details + tags), bypassing SQLite.  Index construction happens
    once in :meth:`setup` and is reused for all 15 queries.

    FastEmbed is used when available and ``ONMC_EMBEDDER=fastembed`` is set;
    otherwise falls back to ``HashNgramEmbedder`` (zero dependencies).
    """

    surface_name = "recall"

    def __init__(self) -> None:
        self._retriever: HybridRetriever | None = None
        self._corpus_ids: list[str] = []

    def setup(self, dataset: RetrievalDataset) -> None:
        """Build BM25 + dense index over the evaluation corpus."""
        corpus = dataset.corpus
        doc_ids = [e.id for e in corpus]
        texts = [_corpus_text(e) for e in corpus]
        evidence = [_corpus_evidence(e) for e in corpus]
        self._corpus_ids = doc_ids
        self._retriever = HybridRetriever(
            doc_ids=doc_ids,
            texts=texts,
            evidence_texts=evidence,
        )

    def retrieve(self, query: str, k: int) -> list[str]:
        """Return up to *k* corpus IDs ranked by BM25+dense+RRF score."""
        if self._retriever is None:
            return []
        hits = self._retriever.retrieve(query, k, mode="hybrid")
        return [h.doc_id for h in hits]

    def teardown(self) -> None:
        self._retriever = None
        self._corpus_ids = []


class HybridGuardAdapter(BaselineAdapter):
    """Hybrid BM25+dense+RRF adapter for the ``"guard"`` evaluation surface.

    Identical pipeline to :class:`HybridRecallAdapter` but runs on the 10
    labeled guard (task dead-end) cases.
    """

    surface_name = "guard"

    def __init__(self) -> None:
        self._retriever: HybridRetriever | None = None

    def setup(self, dataset: RetrievalDataset) -> None:
        corpus = dataset.corpus
        doc_ids = [e.id for e in corpus]
        texts = [_corpus_text(e) for e in corpus]
        evidence = [_corpus_evidence(e) for e in corpus]
        self._retriever = HybridRetriever(
            doc_ids=doc_ids,
            texts=texts,
            evidence_texts=evidence,
        )

    def retrieve(self, query: str, k: int) -> list[str]:
        if self._retriever is None:
            return []
        hits = self._retriever.retrieve(query, k, mode="hybrid")
        return [h.doc_id for h in hits]

    def teardown(self) -> None:
        self._retriever = None
