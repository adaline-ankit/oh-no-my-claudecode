"""Persistent store for eval cases — JSON files under ``.onmc/evals/``.

File layout
-----------
::

    .onmc/evals/
        <case-id>.json    <- one JSON file per EvalCase

Each file is a plain JSON object that round-trips through
:class:`~oh_no_my_claudecode.evals.models.EvalCase`.  No DB schema migration
needed — adding new optional fields with defaults is backward-compatible.

Helper
------
:func:`create_eval_case_from_task` derives a reasonable :class:`EvalCase`
from an existing memory or task record: the query is taken from the memory's
title/summary, ``expected_files`` from ``source_ref``/``tags``, and
``expected_deadend_substrings`` from any linked ``FAILED_APPROACH`` memory
in the same tag namespace.
"""

from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.evals.models import EvalCase
from oh_no_my_claudecode.models import MemoryKind
from oh_no_my_claudecode.storage import SQLiteStorage

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_EVALS_DIR_NAME = "evals"


def _evals_dir(repo_root: Path) -> Path:
    return repo_root / ".onmc" / _EVALS_DIR_NAME


def _case_path(repo_root: Path, case_id: str) -> Path:
    return _evals_dir(repo_root) / f"{case_id}.json"


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _case_to_dict(case: EvalCase) -> dict[str, object]:
    return {
        "id": case.id,
        "query": case.query,
        "expected_files": case.expected_files,
        "expected_deadend_substrings": case.expected_deadend_substrings,
        "note": case.note,
    }


def _case_from_dict(data: dict[str, object]) -> EvalCase:
    raw_files = data.get("expected_files", [])
    raw_deadends = data.get("expected_deadend_substrings", [])
    expected_files = [str(x) for x in raw_files] if isinstance(raw_files, list) else []
    expected_deadend_substrings = (
        [str(x) for x in raw_deadends] if isinstance(raw_deadends, list) else []
    )
    return EvalCase(
        id=str(data.get("id", "")),
        query=str(data.get("query", "")),
        expected_files=expected_files,
        expected_deadend_substrings=expected_deadend_substrings,
        note=str(data.get("note", "")),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_eval_case(repo_root: Path, case: EvalCase) -> Path:
    """Persist *case* to ``.onmc/evals/<id>.json``.

    Creates the directory if it does not exist.

    Returns
    -------
    Path
        Absolute path of the written file.
    """
    evals_dir = _evals_dir(repo_root)
    evals_dir.mkdir(parents=True, exist_ok=True)
    path = _case_path(repo_root, case.id)
    path.write_text(json.dumps(_case_to_dict(case), indent=2), encoding="utf-8")
    return path


def load_eval_case(repo_root: Path, case_id: str) -> EvalCase | None:
    """Load one eval case by id.  Returns ``None`` when the file is missing."""
    path = _case_path(repo_root, case_id)
    if not path.exists():
        return None
    try:
        data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
        return _case_from_dict(data)
    except Exception:  # noqa: BLE001
        return None


def load_all_eval_cases(repo_root: Path) -> list[EvalCase]:
    """Load all eval cases from ``.onmc/evals/``.

    Returns an empty list when the directory is missing or empty.  Cases are
    sorted by id for deterministic ordering.
    """
    evals_dir = _evals_dir(repo_root)
    if not evals_dir.exists():
        return []
    cases: list[EvalCase] = []
    for path in sorted(evals_dir.glob("*.json")):
        try:
            data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
            cases.append(_case_from_dict(data))
        except Exception:  # noqa: BLE001, S112
            continue  # skip corrupt files silently — same as trace recorder policy
    return cases


def delete_eval_case(repo_root: Path, case_id: str) -> bool:
    """Remove the eval case file.  Returns True if the file existed."""
    path = _case_path(repo_root, case_id)
    if path.exists():
        path.unlink()
        return True
    return False


def create_eval_case_from_task(
    storage: SQLiteStorage,
    memory_id: str,
) -> EvalCase | None:
    """Derive an :class:`EvalCase` from an existing memory entry.

    The query is constructed from the memory's ``title`` and ``summary``.
    ``expected_files`` is populated from the memory's ``source_ref`` (if
    non-empty) and ``tags``.  ``expected_deadend_substrings`` is populated
    from any ``FAILED_APPROACH`` memories that share at least one tag with
    the source memory.

    Returns ``None`` when no memory with *memory_id* exists.
    """
    memory = storage.get_memory(memory_id)
    if memory is None:
        return None

    # Build query from title + summary (drop duplicate words naively)
    query_parts = [memory.title]
    if memory.summary and memory.summary != memory.title:
        query_parts.append(memory.summary)
    query = " ".join(query_parts)

    # expected_files: source_ref + tags that look like file paths
    expected_files: list[str] = []
    if memory.source_ref and memory.source_ref.strip():
        expected_files.append(memory.source_ref.strip())
    for tag in memory.tags:
        if ("/" in tag or tag.endswith(".py") or tag.endswith(".ts")) and tag not in expected_files:
            expected_files.append(tag)
    # Also include the memory's own id and title as a hit target
    if memory.id not in expected_files:
        expected_files.append(memory.id)

    # expected_deadend_substrings: linked FAILED_APPROACH memories sharing tags
    expected_deadend_substrings: list[str] = []
    if memory.tags:
        try:
            failed_approaches = storage.list_memories(kind=MemoryKind.FAILED_APPROACH)
            for fa in failed_approaches:
                if fa.id == memory.id:
                    continue
                # Share at least one tag
                if set(fa.tags) & set(memory.tags):
                    # Use the title as the expected substring
                    snippet = fa.title[:60] if fa.title else fa.summary[:60]
                    if snippet and snippet not in expected_deadend_substrings:
                        expected_deadend_substrings.append(snippet)
        except Exception:  # noqa: BLE001, S110
            pass  # artifact retrieval failure must not break case derivation

    # If the memory itself is a FAILED_APPROACH, use its own title as a deadend hint
    if memory.kind == MemoryKind.FAILED_APPROACH:
        snippet = memory.title[:60] if memory.title else memory.summary[:60]
        if snippet and snippet not in expected_deadend_substrings:
            expected_deadend_substrings.append(snippet)

    # Derive a stable case id from the memory id
    safe_mid = memory_id.replace(":", "-").replace("/", "-")[:40]
    case_id = f"mem-{safe_mid}"

    return EvalCase(
        id=case_id,
        query=query,
        expected_files=expected_files,
        expected_deadend_substrings=expected_deadend_substrings,
        note=f"Derived from memory {memory_id} ({memory.kind.value})",
    )
