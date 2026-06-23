"""Replay Lab — deterministic re-derivation of onmc memory hits over a trace session.

Design
------
``replay_session`` iterates the provided :class:`TraceEvent` list and, for each
*query-bearing* event, calls :func:`compile_recall` and :func:`compile_guard`
against the current storage brain.  No LLM is invoked; all work is offline and
deterministic given a fixed storage state.

Query extraction
----------------
Each event's payload is searched for text to use as a recall/guard query in the
following priority order:

1. ``payload["query"]``   — explicit recall query (memory_hit / memory_miss events).
2. ``payload["target"]``  — file path or search string (file_read / search_query /
   tool_call events).
3. ``payload["title"]``   — notification title (notify-sourced events).
4. ``payload["detail"]``  — notification body (fallback for notify events).

Events with no extractable text (e.g. ``tokens`` events) are skipped.

With-memory vs without-memory
------------------------------
When ``with_memory=False``, all recall/guard calls are skipped and every step
receives ``recall_hits=0``, ``deadend_hits=0``, ``injected_chars=0``.  This
models the cold (no-memory) baseline.

``compare_replay`` runs both conditions and computes deltas.
"""

from __future__ import annotations

from oh_no_my_claudecode.guard.compiler import compile_guard
from oh_no_my_claudecode.recall.compiler import compile_recall
from oh_no_my_claudecode.replay.models import ReplayComparison, ReplayReport, ReplayStep
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.trace.models import TraceEvent

# ---------------------------------------------------------------------------
# Query extraction
# ---------------------------------------------------------------------------

# Event kinds that carry a query in ``payload["query"]``.
_QUERY_KEY_KINDS = frozenset({"memory_hit", "memory_miss"})

# Event kinds that carry a useful search target in ``payload["target"]``.
_TARGET_KEY_KINDS = frozenset({"file_read", "search_query", "tool_call"})

# Notify-sourced event kinds that carry text in ``payload["title"]`` or
# ``payload["detail"]``.
_NOTIFY_KINDS = frozenset(
    {"recall_surfaced", "danger_blocked", "memory_captured", "skill_promoted",
     "staleness_warning", "generic"}
)


def _extract_query(event: TraceEvent) -> str:
    """Extract a query string from *event*'s payload.

    Returns an empty string when no useful text can be derived (e.g. ``tokens``
    events with only numeric data).  Never raises.
    """
    payload = event.payload
    kind = event.kind

    # Priority 1: explicit "query" key (memory_hit / memory_miss).
    if kind in _QUERY_KEY_KINDS:
        text = str(payload.get("query", "")).strip()
        if text:
            return text

    # Priority 2: "target" key (file_read / search_query / tool_call).
    if kind in _TARGET_KEY_KINDS:
        text = str(payload.get("target", "")).strip()
        if text:
            return text

    # Priority 3: notification title or detail.
    if kind in _NOTIFY_KINDS:
        text = str(payload.get("title", "")).strip()
        if text:
            return text
        text = str(payload.get("detail", "")).strip()
        if text:
            return text

    # Generic fallback: check common keys in order.
    for key in ("query", "target", "title", "detail"):
        text = str(payload.get(key, "")).strip()
        if text:
            return text

    return ""


# ---------------------------------------------------------------------------
# Core replay logic
# ---------------------------------------------------------------------------


def replay_session(
    storage: SQLiteStorage,
    events: list[TraceEvent],
    *,
    session_id: str = "",
    with_memory: bool = True,
    recall_limit: int = 8,
) -> ReplayReport:
    """Re-derive what onmc WOULD have surfaced at each step in *events*.

    Iterates every :class:`TraceEvent` and, for each event whose payload
    contains a usable query string, runs :func:`compile_recall` and
    :func:`compile_guard` against *storage*.

    When ``with_memory=False``, all retrieval calls are skipped and every step
    receives empty results — this is the cold (no-memory) baseline.

    Deterministic and offline — no LLM calls, no network.

    Parameters
    ----------
    storage:
        Initialised :class:`SQLiteStorage` instance.
    events:
        Ordered list of :class:`TraceEvent` objects from a recorded session.
        Typically loaded via
        :func:`~oh_no_my_claudecode.trace.recorder.load_session_events`.
    session_id:
        Identifier for the source session (used for reporting only).
    with_memory:
        When ``True`` (default), run recall/guard against live storage.
        When ``False``, simulate the cold baseline (empty results everywhere).
    recall_limit:
        Maximum entries to request from :func:`compile_recall` per step.

    Returns
    -------
    ReplayReport
        Aggregate metrics over all query-bearing steps.  Steps with no
        extractable query text are silently skipped (not counted in
        ``total_steps``).
    """
    steps: list[ReplayStep] = []

    for idx, event in enumerate(events):
        query = _extract_query(event)
        if not query:
            # Skip events with no useful query text.
            continue

        if not with_memory:
            steps.append(
                ReplayStep(
                    index=idx,
                    query=query,
                    recall_hits=0,
                    deadend_hits=0,
                    injected_chars=0,
                )
            )
            continue

        # --- with_memory=True: run actual recall/guard ---
        recall_result = compile_recall(storage, query, limit=recall_limit)
        guard_result = compile_guard(storage, query, limit=recall_limit)

        injected_chars = sum(
            len(e.title) + len(e.what_happened) + len(e.resolution)
            for e in recall_result.entries
        )

        steps.append(
            ReplayStep(
                index=idx,
                query=query,
                recall_hits=len(recall_result.entries),
                deadend_hits=len(guard_result.entries),
                injected_chars=injected_chars,
            )
        )

    total = len(steps)
    steps_with_recall = sum(1 for s in steps if s.recall_hits > 0)
    steps_with_deadend = sum(1 for s in steps if s.deadend_hits > 0)
    total_chars = sum(s.injected_chars for s in steps)
    mean_chars = total_chars / total if total > 0 else 0.0

    return ReplayReport(
        session_id=session_id,
        steps=steps,
        total_steps=total,
        steps_with_recall=steps_with_recall,
        steps_with_deadend=steps_with_deadend,
        mean_injected_chars=mean_chars,
        with_memory=with_memory,
    )


def compare_replay(
    storage: SQLiteStorage,
    events: list[TraceEvent],
    *,
    session_id: str = "",
    recall_limit: int = 8,
) -> ReplayComparison:
    """Run both memory conditions and return a :class:`ReplayComparison`.

    Runs :func:`replay_session` twice — once with ``with_memory=True`` (live
    brain) and once with ``with_memory=False`` (cold baseline) — then computes
    delta metrics that show what memory changed.

    Deterministic and offline — no LLM calls, no network.

    Parameters
    ----------
    storage:
        Initialised :class:`SQLiteStorage` instance.
    events:
        Ordered list of :class:`TraceEvent` objects.
    session_id:
        Identifier for the source session (reporting only).
    recall_limit:
        Max entries per :func:`compile_recall` call.

    Returns
    -------
    ReplayComparison
        Both reports plus delta metrics:

        - ``steps_where_recall_added`` — steps where memory added recall that
          the baseline lacked.
        - ``steps_where_deadend_added`` — steps where memory added a guard
          dead-end that the baseline lacked.
        - ``steps_where_context_changed`` — steps where injected_chars differs.
        - ``mean_chars_delta`` — difference in mean injected chars
          (positive = memory adds context).
    """
    with_mem = replay_session(
        storage,
        events,
        session_id=session_id,
        with_memory=True,
        recall_limit=recall_limit,
    )
    without_mem = replay_session(
        storage,
        events,
        session_id=session_id,
        with_memory=False,
        recall_limit=recall_limit,
    )

    # Build an index of without-memory steps by event index for delta comparison.
    without_by_index: dict[int, ReplayStep] = {s.index: s for s in without_mem.steps}

    steps_where_recall_added = 0
    steps_where_deadend_added = 0
    steps_where_context_changed = 0

    for step in with_mem.steps:
        baseline = without_by_index.get(step.index)
        baseline_recall = baseline.recall_hits if baseline is not None else 0
        baseline_deadend = baseline.deadend_hits if baseline is not None else 0
        baseline_chars = baseline.injected_chars if baseline is not None else 0

        if step.recall_hits > baseline_recall:
            steps_where_recall_added += 1
        if step.deadend_hits > baseline_deadend:
            steps_where_deadend_added += 1
        if step.injected_chars != baseline_chars:
            steps_where_context_changed += 1

    mean_chars_delta = with_mem.mean_injected_chars - without_mem.mean_injected_chars

    deltas: dict[str, float] = {
        "steps_where_recall_added": float(steps_where_recall_added),
        "steps_where_deadend_added": float(steps_where_deadend_added),
        "steps_where_context_changed": float(steps_where_context_changed),
        "mean_chars_delta": mean_chars_delta,
    }

    return ReplayComparison(
        with_memory=with_mem,
        without_memory=without_mem,
        deltas=deltas,
    )
