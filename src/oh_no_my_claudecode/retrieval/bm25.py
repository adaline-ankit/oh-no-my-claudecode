"""Okapi BM25 retrieval — pure Python, deterministic, zero dependencies.

BM25 parameters follow Trotman et al. (2014) / Robertson (1994) best-practice
defaults:

  k1 = 1.2  (term-frequency saturation — lower than 1.5 for short-doc corpora)
  b  = 0.75 (document-length normalisation)

Tokenisation: lowercase alphanumeric tokens only.  Identical to the
``HashNgramEmbedder`` base extraction so BM25 and dense indices share
the same vocabulary-level decomposition.
"""

from __future__ import annotations

import math
import re
from collections import Counter

# Alphanumeric token extractor — same as HashNgramEmbedder.
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokenisation, identical to the embedder baseline."""
    return _TOKEN_RE.findall(text.lower())


class BM25Corpus:
    """Inverted-index BM25 over a fixed corpus.

    Builds the IDF table and per-document TF counters on construction so that
    repeated :meth:`retrieve` calls are O(V) where V is query vocabulary size.

    Parameters
    ----------
    doc_ids:
        Ordered list of document identifiers.
    texts:
        Parallel list of raw text strings (one per document).
    k1:
        Term-frequency saturation parameter (default 1.2).
    b:
        Length-normalisation parameter (default 0.75).
    """

    def __init__(
        self,
        doc_ids: list[str],
        texts: list[str],
        *,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> None:
        if len(doc_ids) != len(texts):
            msg = (
                f"doc_ids and texts must be the same length; "
                f"got {len(doc_ids)} vs {len(texts)}"
            )
            raise ValueError(msg)

        self._doc_ids: list[str] = list(doc_ids)
        self._k1 = k1
        self._b = b

        # Tokenise corpus once at construction time.
        self._token_lists: list[list[str]] = [tokenize(t) for t in texts]
        n = len(self._token_lists)

        # Average document length (denominator in length normalisation).
        total_len = sum(len(tl) for tl in self._token_lists)
        self._avgdl: float = total_len / n if n > 0 else 1.0

        # Document frequency per unique term.
        df: Counter[str] = Counter()
        for token_list in self._token_lists:
            for tok in set(token_list):
                df[tok] += 1

        # Robertson IDF with +1 smoothing to avoid negative values when
        # the term appears in more than half the documents.
        self._idf: dict[str, float] = {
            term: math.log((n - freq + 0.5) / (freq + 0.5) + 1.0)
            for term, freq in df.items()
        }

        # Per-document term-frequency maps (Counter for O(1) lookups).
        self._tf: list[Counter[str]] = [Counter(tl) for tl in self._token_lists]

        # Fast reverse-lookup from doc_id to index.
        self._id_to_idx: dict[str, int] = {
            doc_id: i for i, doc_id in enumerate(self._doc_ids)
        }

    def score(self, query: str, doc_idx: int) -> float:
        """Return the BM25 score for *query* against the document at *doc_idx*.

        Returns 0.0 for an empty query or when no query term appears in the
        document.
        """
        query_tokens = tokenize(query)
        if not query_tokens:
            return 0.0

        doc_len = len(self._token_lists[doc_idx])
        tf = self._tf[doc_idx]
        k1 = self._k1
        b = self._b
        avgdl = self._avgdl

        score = 0.0
        for tok in query_tokens:
            idf = self._idf.get(tok, 0.0)
            f = tf.get(tok, 0)
            if f == 0:
                continue
            numerator = f * (k1 + 1.0)
            denominator = f + k1 * (1.0 - b + b * doc_len / avgdl)
            score += idf * (numerator / denominator)

        return score

    def retrieve(self, query: str, k: int) -> list[tuple[str, float]]:
        """Return up to *k* ``(doc_id, score)`` pairs, ranked BM25 score descending.

        Documents with score <= 0 are excluded.  Ties are broken by doc_id
        lexicographic order for determinism.
        """
        scored: list[tuple[str, float]] = [
            (self._doc_ids[i], self.score(query, i))
            for i in range(len(self._doc_ids))
        ]
        # Primary: score descending.  Secondary: doc_id ascending (deterministic).
        scored.sort(key=lambda x: (-x[1], x[0]))
        return [(doc_id, sc) for doc_id, sc in scored[:k] if sc > 0.0]

    @property
    def doc_ids(self) -> list[str]:
        """Ordered list of document identifiers in this corpus."""
        return list(self._doc_ids)

    @property
    def id_to_idx(self) -> dict[str, int]:
        """Map from doc_id to position index in :attr:`doc_ids`."""
        return dict(self._id_to_idx)
