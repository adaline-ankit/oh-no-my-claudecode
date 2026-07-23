"""Baseline retrieval adapters for the current onmc retrieval surfaces.

Each adapter wraps a retrieval function from the live codebase and presents it
as a ``retrieve(query, k) -> list[ranked_ids]`` callable so the runner can
score it against the frozen dataset.

Adapters implemented
---------------------
``RecallAdapter``
    Wraps :func:`~oh_no_my_claudecode.recall.compiler.compile_recall`.
    Seeds an in-memory SQLite database with the eval corpus, then queries it
    with each eval case query.  Surface name: ``"recall"``.

``GuardAdapter``
    Wraps :func:`~oh_no_my_claudecode.guard.compiler.compile_guard`.
    Same corpus seeding strategy.  Surface name: ``"guard"``.

Surfaces that could NOT be adapted cleanly
-------------------------------------------
``search_memory`` (MCP tools path)
    Requires a fully initialised ``OnmcRepo`` object with a real project root
    and config file on disk.  The hybrid FTS+embedding path also calls
    ``rerank_with_embeddings`` which reads from a SQLite vector cache.
    Wiring this correctly requires significant test-harness scaffolding that
    would couple the eval harness to internal service details.
    Marked as SKIPPED with an honest reason.

``ContextEngine / planner``
    Operates on a ``Candidate`` graph built from repo file structure and
    git history.  Requires a real (or synthetic) git repository.  Not
    measurable without a separate fixture-generation step.
    Marked as SKIPPED with an honest reason.
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from pathlib import Path

from oh_no_my_claudecode.retrieval_eval.dataset import CorpusEntry, RetrievalDataset
from oh_no_my_claudecode.retrieval_eval.runner import BaselineAdapter


def _seed_corpus(storage: object, corpus_entries: Sequence[CorpusEntry]) -> dict[str, str]:
    """Insert corpus entries into a SQLiteStorage and return {corpus_id -> memory_id}."""
    from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind, SourceType
    from oh_no_my_claudecode.utils.text import stable_id
    from oh_no_my_claudecode.utils.time import utc_now

    kind_map: dict[str, MemoryKind] = {
        "failed_approach": MemoryKind.FAILED_APPROACH,
        "gotcha": MemoryKind.GOTCHA,
        "decision": MemoryKind.DECISION,
        "invariant": MemoryKind.INVARIANT,
        "hotspot": MemoryKind.HOTSPOT,
        "doc_fact": MemoryKind.DOC_FACT,
        "git_pattern": MemoryKind.GIT_PATTERN,
        "validation_rule": MemoryKind.VALIDATION_RULE,
        "design_conflict": MemoryKind.DESIGN_CONFLICT,
    }

    id_map: dict[str, str] = {}
    entries: list[MemoryEntry] = []
    now = utc_now()

    for corp in corpus_entries:
        kind = kind_map.get(corp.kind, MemoryKind.DOC_FACT)
        mem_id = stable_id(kind.value, corp.title, corp.summary, "eval:corpus", prefix="eval")
        id_map[corp.id] = mem_id
        entries.append(
            MemoryEntry(
                id=mem_id,
                kind=kind,
                title=corp.title,
                summary=corp.summary,
                details=corp.details,
                source_type=SourceType.MANUAL,
                source_ref="eval:corpus",
                tags=list(corp.tags),
                confidence=0.9,
                created_at=now,
                updated_at=now,
            )
        )

    storage.upsert_memories(entries)  # type: ignore[attr-defined]
    return id_map


class RecallAdapter(BaselineAdapter):
    """Adapter for :func:`oh_no_my_claudecode.recall.compiler.compile_recall`.

    Seeds an ephemeral SQLite database with the evaluation corpus and scores
    compile_recall against the labeled recall cases.

    This adapter is offline, deterministic, and produces no network calls.
    """

    surface_name = "recall"

    def __init__(self) -> None:
        self._tmp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._storage: object = None
        self._id_map: dict[str, str] = {}

    def setup(self, dataset: RetrievalDataset) -> None:
        from oh_no_my_claudecode.storage import SQLiteStorage

        self._tmp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp_dir.name) / "eval.sqlite"
        storage = SQLiteStorage(db_path)
        storage.initialize()
        self._storage = storage
        self._id_map = _seed_corpus(storage, dataset.corpus)

    def retrieve(self, query: str, k: int) -> list[str]:
        """Return up to k memory IDs ranked by compile_recall."""
        from oh_no_my_claudecode.recall.compiler import compile_recall
        from oh_no_my_claudecode.storage import SQLiteStorage

        storage: SQLiteStorage = self._storage  # type: ignore[assignment]
        result = compile_recall(storage, query, limit=k)
        # Map internal memory IDs back to corpus IDs.
        reverse_map = {v: k for k, v in self._id_map.items()}
        ranked_corpus_ids: list[str] = []
        for entry in result.entries:
            corpus_id = reverse_map.get(entry.memory_id)
            if corpus_id is not None:
                ranked_corpus_ids.append(corpus_id)
        return ranked_corpus_ids[:k]

    def teardown(self) -> None:
        if self._tmp_dir is not None:
            self._tmp_dir.cleanup()
            self._tmp_dir = None
        self._storage = None
        self._id_map = {}


class GuardAdapter(BaselineAdapter):
    """Adapter for :func:`oh_no_my_claudecode.guard.compiler.compile_guard`.

    Seeds the same ephemeral SQLite database and scores compile_guard against
    the labeled guard cases (task-based dead-end lookup).

    This adapter is offline, deterministic, and produces no network calls.
    """

    surface_name = "guard"

    def __init__(self) -> None:
        self._tmp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._storage: object = None
        self._id_map: dict[str, str] = {}

    def setup(self, dataset: RetrievalDataset) -> None:
        from oh_no_my_claudecode.storage import SQLiteStorage

        self._tmp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp_dir.name) / "eval.sqlite"
        storage = SQLiteStorage(db_path)
        storage.initialize()
        self._storage = storage
        self._id_map = _seed_corpus(storage, dataset.corpus)

    def retrieve(self, query: str, k: int) -> list[str]:
        """Return up to k memory IDs ranked by compile_guard."""
        from oh_no_my_claudecode.guard.compiler import compile_guard
        from oh_no_my_claudecode.storage import SQLiteStorage

        storage: SQLiteStorage = self._storage  # type: ignore[assignment]
        result = compile_guard(storage, query, limit=k)
        reverse_map = {v: k for k, v in self._id_map.items()}
        ranked_corpus_ids: list[str] = []
        for entry in result.entries:
            corpus_id = reverse_map.get(entry.memory_id)
            if corpus_id is not None:
                ranked_corpus_ids.append(corpus_id)
        return ranked_corpus_ids[:k]

    def teardown(self) -> None:
        if self._tmp_dir is not None:
            self._tmp_dir.cleanup()
            self._tmp_dir = None
        self._storage = None
        self._id_map = {}


class SkippedAdapter(BaselineAdapter):
    """Placeholder for a retrieval surface that cannot be adapted cleanly.

    Records an honest SKIPPED entry in the report instead of silently
    omitting the surface.
    """

    def __init__(self, name: str, reason: str) -> None:
        self.surface_name = name
        self._reason = reason

    def setup(self, dataset: RetrievalDataset) -> None:
        msg = self._reason
        raise RuntimeError(msg)

    def retrieve(self, query: str, k: int) -> list[str]:
        return []


# Registry of all adapters available for the CLI command.
# Surfaces that can't be adapted are listed as SkippedAdapter so they appear
# in the report with an honest explanation instead of being silently absent.
def default_adapters() -> list[BaselineAdapter]:
    """Return the default set of adapters for the retrieval-eval CLI command."""
    return [
        RecallAdapter(),
        GuardAdapter(),
        SkippedAdapter(
            name="search_memory",
            reason=(
                "Requires fully initialised OnmcRepo with real project root and config. "
                "The FTS+embedding hybrid path couples to internal service details. "
                "Adapt manually for deeper MCP search evaluation."
            ),
        ),
        SkippedAdapter(
            name="context_engine",
            reason=(
                "Requires a real or synthetic git repository to build the Candidate graph. "
                "No standalone retrieve() shim is possible without a separate fixture generator."
            ),
        ),
    ]
