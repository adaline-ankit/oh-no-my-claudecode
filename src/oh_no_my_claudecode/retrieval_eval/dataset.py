"""Load and validate the frozen labeled retrieval dataset.

The dataset lives at ``datasets/retrieval_v1.json`` relative to the package
root.  It is committed and frozen — its SHA256 is pinned in the file itself
and verified on load to detect accidental edits.

Dataset schema
--------------
``corpus``: list of memory-like documents (id, kind, title, summary, details, tags).
``cases``: list of evaluation queries (query_id, surface, query, relevant_ids, graded).
``dataset_sha``: SHA256 of the canonical serialisation of corpus+cases.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

# Path to the frozen dataset file.  Resolved relative to this module.
_DATASET_PATH = Path(__file__).resolve().parents[3] / "datasets" / "retrieval_v1.json"


@dataclass(frozen=True)
class CorpusEntry:
    """A single document in the evaluation corpus."""

    id: str
    kind: str
    title: str
    summary: str
    details: str
    tags: list[str]


@dataclass(frozen=True)
class EvalCase:
    """One labeled retrieval query with known relevant document IDs."""

    query_id: str
    surface: str  # "recall" | "guard"
    query: str
    relevant_ids: list[str]
    graded: dict[str, float]  # doc_id -> relevance grade (may be empty)


@dataclass
class RetrievalDataset:
    """The complete frozen labeled dataset."""

    version: str
    dataset_sha: str
    corpus: list[CorpusEntry]
    cases: list[EvalCase]

    def cases_for_surface(self, surface: str) -> list[EvalCase]:
        """Return only the cases targeting a particular retrieval surface."""
        return [c for c in self.cases if c.surface == surface]

    def corpus_by_id(self) -> dict[str, CorpusEntry]:
        return {e.id: e for e in self.corpus}


def _compute_dataset_sha(raw: dict[str, object]) -> str:
    """Compute the canonical SHA256 over corpus+cases (excluding dataset_sha)."""
    content: dict[str, object] = {
        "version": raw["version"],
        "corpus": raw["corpus"],
        "cases": raw["cases"],
    }
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def load_dataset(*, verify_sha: bool = True) -> RetrievalDataset:
    """Load and optionally verify the frozen retrieval dataset.

    Args:
        verify_sha: When True (default), assert that the file's ``dataset_sha``
            field matches the computed SHA256 of corpus+cases.  Set to False
            only for debugging.

    Returns:
        A :class:`RetrievalDataset` with corpus and cases populated.

    Raises:
        FileNotFoundError: If the dataset file is missing.
        ValueError: If ``verify_sha`` is True and the SHA does not match.
    """
    if not _DATASET_PATH.exists():
        msg = (
            f"Retrieval dataset not found at {_DATASET_PATH}.  "
            "Ensure the datasets/ directory is present in the repository root."
        )
        raise FileNotFoundError(msg)

    raw = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))

    if verify_sha:
        expected = str(raw.get("dataset_sha", ""))
        computed = _compute_dataset_sha(raw)
        if expected != computed:
            msg = (
                f"Dataset integrity check failed!\n"
                f"  Stored SHA : {expected}\n"
                f"  Computed SHA: {computed}\n"
                "The dataset file has been modified.  Frozen datasets must not be edited.\n"
                "To update the dataset, create a new version file and update the SHA."
            )
            raise ValueError(msg)

    corpus = [
        CorpusEntry(
            id=entry["id"],
            kind=entry["kind"],
            title=entry["title"],
            summary=entry["summary"],
            details=entry["details"],
            tags=list(entry.get("tags", [])),
        )
        for entry in raw["corpus"]
    ]

    cases = [
        EvalCase(
            query_id=case["query_id"],
            surface=case["surface"],
            query=case["query"],
            relevant_ids=list(case["relevant_ids"]),
            graded={k: float(v) for k, v in case.get("graded", {}).items()},
        )
        for case in raw["cases"]
    ]

    return RetrievalDataset(
        version=str(raw["version"]),
        dataset_sha=str(raw.get("dataset_sha", "")),
        corpus=corpus,
        cases=cases,
    )


# Expose the expected SHA so tests can pin it without loading the file.
EXPECTED_DATASET_SHA = "eeff58b47d051e58351fa048f778d12cd16d974c3014da62dac586277ae6c42d"
