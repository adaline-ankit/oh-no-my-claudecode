"""Deterministic eval harness — measures memory recall and dead-end avoidance.

Methodology (honest description)
----------------------------------
This is a **deterministic, offline** evaluation.  No LLM is called.  The
harness calls onmc's own retrieval primitives
(:func:`~oh_no_my_claudecode.recall.compiler.compile_recall` and
:func:`~oh_no_my_claudecode.guard.compiler.compile_guard`) and scores each
case against developer-defined expectations.

Two conditions
--------------
with_memory=True (live brain):
    compile_recall and compile_guard are called normally against the storage.
    Scores reflect what the brain actually retrieves.

with_memory=False (cold baseline):
    Retrieval results are treated as empty — every case fails, injected_chars=0.
    This models the agent operating without any memory surface.

The **delta** (with_memory score minus without_memory score) is the
measurable contribution of the brain.  A positive delta proves the brain
helps; a regression (delta shrinks across runs) signals memory quality
degraded.

Metrics per case
----------------
- ``files_hit``: compile_recall returns an entry whose ``memory_id`` or
  ``title`` contains one of ``EvalCase.expected_files``.  Vacuously True
  when ``expected_files`` is empty (not scored).
- ``deadend_hit``: compile_guard returns an entry whose ``what_was_tried``
  or ``title`` contains one of ``EvalCase.expected_deadend_substrings``.
  Vacuously True when ``expected_deadend_substrings`` is empty.
- ``passed``: files_hit AND deadend_hit.
- ``injected_chars``: total chars of recall entry text (context-cost proxy).

Aggregate report
----------------
- ``pass_rate``: fraction of cases that passed.
- ``score``: pass_rate * 100 (0–100 scale for --fail-under comparison).
- ``mean_injected_chars``: average injected chars across cases.
"""

from __future__ import annotations

from oh_no_my_claudecode.evals.models import (
    EvalCase,
    EvalCaseResult,
    EvalComparison,
    EvalReport,
)
from oh_no_my_claudecode.guard.compiler import compile_guard
from oh_no_my_claudecode.recall.compiler import compile_recall
from oh_no_my_claudecode.storage import SQLiteStorage

# ---------------------------------------------------------------------------
# Case scoring
# ---------------------------------------------------------------------------


def _score_case(
    case: EvalCase,
    storage: SQLiteStorage,
    *,
    with_memory: bool,
    recall_limit: int,
) -> EvalCaseResult:
    """Run one eval case and return its result.

    Args:
        case: The eval case to score.
        storage: Initialised SQLiteStorage instance.
        with_memory: When True, call compile_recall/guard normally.
            When False, simulate empty retrieval (cold baseline).
        recall_limit: Maximum entries to request from compile_recall.
    """
    if not with_memory:
        # Cold baseline: simulate no memory surface.
        return EvalCaseResult(
            case_id=case.id,
            files_hit=not case.expected_files,
            deadend_hit=not case.expected_deadend_substrings,
            recall_entries=0,
            injected_chars=0,
            passed=not case.expected_files and not case.expected_deadend_substrings,
        )

    # --- compile_recall scoring ---
    recall_result = compile_recall(storage, case.query, limit=recall_limit)
    recall_entries = len(recall_result.entries)

    # injected_chars: sum of all text surfaces from recall entries
    injected_chars = sum(
        len(e.title) + len(e.what_happened) + len(e.resolution)
        for e in recall_result.entries
    )

    # files_hit: vacuously True if no expectations; otherwise check for a match
    if not case.expected_files:
        files_hit = True
    else:
        needle_lower = [f.lower() for f in case.expected_files]
        files_hit = False
        for entry in recall_result.entries:
            entry_text = (entry.memory_id + " " + entry.title).lower()
            if any(needle in entry_text for needle in needle_lower):
                files_hit = True
                break

    # --- compile_guard scoring ---
    if not case.expected_deadend_substrings:
        deadend_hit = True
    else:
        guard_result = compile_guard(storage, case.query, limit=recall_limit)
        deadend_hit = False
        needle_lower = [s.lower() for s in case.expected_deadend_substrings]
        for guard_entry in guard_result.entries:
            guard_text = (guard_entry.title + " " + guard_entry.what_was_tried).lower()
            if any(needle in guard_text for needle in needle_lower):
                deadend_hit = True
                break

    return EvalCaseResult(
        case_id=case.id,
        files_hit=files_hit,
        deadend_hit=deadend_hit,
        recall_entries=recall_entries,
        injected_chars=injected_chars,
        passed=files_hit and deadend_hit,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_evals(
    storage: SQLiteStorage,
    cases: list[EvalCase],
    *,
    with_memory: bool = True,
    recall_limit: int = 8,
) -> EvalReport:
    """Run the eval suite and return an :class:`EvalReport`.

    Deterministic and offline — no LLM calls, no network.

    Args:
        storage: Initialised SQLiteStorage instance.
        cases: List of eval cases to run.
        with_memory: When True (default), evaluate against live storage.
            When False, simulate the cold (no-memory) baseline.
        recall_limit: Max entries to request from compile_recall per case.

    Returns:
        An :class:`EvalReport` with per-case results and aggregate metrics.
        Empty suite returns a report with pass_rate=0.0 and score=0.0 (or 100.0
        vacuously for the no-case case — see note below).

    Note on empty suite
    -------------------
    When ``cases`` is empty the suite returns pass_rate=1.0 and score=100.0
    (vacuously passing — there is nothing to fail).  This is intentional: an
    empty suite should not gate CI.  Callers that want a meaningful baseline
    should ensure at least one case exists.
    """
    if not cases:
        return EvalReport(
            results=[],
            pass_rate=1.0,
            with_memory=with_memory,
            mean_injected_chars=0.0,
            score=100.0,
        )

    results = [
        _score_case(case, storage, with_memory=with_memory, recall_limit=recall_limit)
        for case in cases
    ]

    passed = sum(1 for r in results if r.passed)
    pass_rate = passed / len(results)
    score = round(pass_rate * 100, 2)
    total_chars = sum(r.injected_chars for r in results)
    mean_injected_chars = total_chars / len(results)

    return EvalReport(
        results=results,
        pass_rate=pass_rate,
        with_memory=with_memory,
        mean_injected_chars=mean_injected_chars,
        score=score,
    )


def compare_evals(
    storage: SQLiteStorage,
    cases: list[EvalCase],
    *,
    recall_limit: int = 8,
) -> EvalComparison:
    """Run both conditions and return an :class:`EvalComparison`.

    Runs ``run_evals`` twice — once with_memory=True (live brain) and once
    with_memory=False (cold baseline).  Deterministic and offline.

    Args:
        storage: Initialised SQLiteStorage instance.
        cases: List of eval cases to run.
        recall_limit: Max entries to request from compile_recall per case.

    Returns:
        An :class:`EvalComparison` with both reports and computed deltas.
    """
    with_mem = run_evals(storage, cases, with_memory=True, recall_limit=recall_limit)
    without_mem = run_evals(storage, cases, with_memory=False, recall_limit=recall_limit)
    return EvalComparison(with_memory=with_mem, without_memory=without_mem)
