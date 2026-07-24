"""Load and validate the frozen code-retrieval evaluation dataset.

The dataset lives at ``datasets/retrieval_code_v1.json`` relative to the repo
root.  It is committed and frozen — its SHA256 is pinned in this module and
verified on load to detect accidental edits.

Dataset schema
--------------
``corpus``: list of code chunks (id, kind, path, symbol, start_line, end_line,
    language, content).
``cases``: list of evaluation queries (query_id, surface, query, relevant_ids,
    graded).  Cases appear in pairs: surface ``"code-bm25"`` and
    ``"code-hybrid"`` carry identical queries so both retrieval modes are scored
    against the same queries without modifying the runner.
``dataset_sha``: SHA256 of the canonical serialisation of corpus+cases.

Construction rule (from ``scripts/build_code_retrieval_dataset.py``)
---------------------------------------------------------------------
Scope: the three modules retrieval_eval/, retrieval/, codeindex/.
Sort all eligible chunks by chunk_id, stride-sample TARGET=40 chunks.
Query = first docstring sentence OR snake_case template.
Corpus = all eligible chunks (149 total).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

# Resolved relative to this module so it works from any cwd.
_CODE_DATASET_PATH = (
    Path(__file__).resolve().parents[3] / "datasets" / "retrieval_code_v1.json"
)

# Expected SHA256 of the frozen dataset.  Pinned here so tests can verify it
# without re-computing from disk.  Do NOT edit this value — run the builder
# to regenerate the dataset and update this constant together.
EXPECTED_CODE_DATASET_SHA = "8e8f6d527b9836b3bf1045c1de6b2e852f85d81612e4cdfebbe72aefefda62bc"


@dataclass(frozen=True)
class CodeCorpusEntry:
    """A single code chunk in the evaluation corpus."""

    id: str
    kind: str
    path: str
    symbol: str
    start_line: int
    end_line: int
    language: str
    content: str


@dataclass(frozen=True)
class CodeEvalCase:
    """One labeled retrieval query with known relevant chunk IDs."""

    query_id: str
    surface: str  # "code-bm25" | "code-hybrid"
    query: str
    relevant_ids: list[str]
    graded: dict[str, float]


@dataclass
class CodeRetrievalDataset:
    """The complete frozen code-retrieval evaluation dataset."""

    version: str
    dataset_sha: str
    corpus: list[CodeCorpusEntry]
    cases: list[CodeEvalCase]

    def cases_for_surface(self, surface: str) -> list[CodeEvalCase]:
        """Return only the cases targeting a particular retrieval surface."""
        return [c for c in self.cases if c.surface == surface]

    def corpus_by_id(self) -> dict[str, CodeCorpusEntry]:
        return {e.id: e for e in self.corpus}


def _compute_code_dataset_sha(raw: dict[str, object]) -> str:
    """Compute the canonical SHA256 over corpus+cases (excluding dataset_sha)."""
    content: dict[str, object] = {
        "version": raw["version"],
        "corpus": raw["corpus"],
        "cases": raw["cases"],
    }
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def load_code_dataset(*, verify_sha: bool = True) -> CodeRetrievalDataset:
    """Load and optionally verify the frozen code-retrieval dataset.

    Args:
        verify_sha: When True (default), assert that the file's ``dataset_sha``
            field matches the computed SHA256 of corpus+cases.  Set to False
            only for debugging.

    Returns:
        A :class:`CodeRetrievalDataset` with corpus and cases populated.

    Raises:
        FileNotFoundError: If the dataset file is missing.
        ValueError: If ``verify_sha`` is True and the SHA does not match.
    """
    if not _CODE_DATASET_PATH.exists():
        msg = (
            f"Code retrieval dataset not found at {_CODE_DATASET_PATH}. "
            "Ensure datasets/retrieval_code_v1.json is present in the repository root."
        )
        raise FileNotFoundError(msg)

    raw = json.loads(_CODE_DATASET_PATH.read_text(encoding="utf-8"))

    if verify_sha:
        expected = str(raw.get("dataset_sha", ""))
        computed = _compute_code_dataset_sha(raw)
        if expected != computed:
            msg = (
                f"Code dataset integrity check failed!\n"
                f"  Stored SHA : {expected}\n"
                f"  Computed SHA: {computed}\n"
                "The dataset file has been modified.  Frozen datasets must not be edited.\n"
                "To rebuild, run: uv run python scripts/build_code_retrieval_dataset.py"
            )
            raise ValueError(msg)

    corpus = [
        CodeCorpusEntry(
            id=str(entry["id"]),
            kind=str(entry["kind"]),
            path=str(entry["path"]),
            symbol=str(entry["symbol"]),
            start_line=int(entry["start_line"]),
            end_line=int(entry["end_line"]),
            language=str(entry["language"]),
            content=str(entry["content"]),
        )
        for entry in raw["corpus"]
    ]

    cases = [
        CodeEvalCase(
            query_id=str(case["query_id"]),
            surface=str(case["surface"]),
            query=str(case["query"]),
            relevant_ids=list(case["relevant_ids"]),
            graded={k: float(v) for k, v in case.get("graded", {}).items()},
        )
        for case in raw["cases"]
    ]

    return CodeRetrievalDataset(
        version=str(raw["version"]),
        dataset_sha=str(raw.get("dataset_sha", "")),
        corpus=corpus,
        cases=cases,
    )
