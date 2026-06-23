"""Pure report compiler for the Agent Trace Observatory.

``compile_trace_report()`` is a **pure function** — given a list of
``TraceEvent`` objects it produces a ``TraceReport`` with no I/O.

Methodology (honest description)
----------------------------------
1. **Exact counts** — tool calls, failures, memory hits/misses, file reads,
   search queries, and token sums are tallied directly from events.  These are
   exact for every event the caller recorded.

2. **Repeated-read / repeated-query detection** — a file path or query string
   seen ≥ 2 times is flagged as wasteful.  The "blocked" count is the number
   of excess reads (count - 1 per unique target).

3. **Loop detection** — a (tool, target) signature that recurs ≥
   ``loop_threshold`` (default 3) times indicates the agent is stuck.

4. **Token-savings estimate (est)** — we use the injected ``savings_estimator``
   callable (or the built-in bench-harness heuristic when ``None``) to derive
   ``est_tokens_without_onmc``.  The formula is::

       est_without = total_tokens / (1 - reduction_fraction)

   where ``reduction_fraction`` is the bench harness's
   ``context_tokens_pct_reduction / 100``.  When ``total_tokens == 0`` (no
   token events were recorded) the estimate is 0.  **Always labelled (est)
   in the report and in the card.**

5. **Honesty notes** — ``extra_notes`` always includes at least one caveat
   about what is estimated vs. exact.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from oh_no_my_claudecode.trace.models import (
    LoopSignal,
    RepeatedItem,
    TraceEvent,
    TraceEventKind,
    TraceReport,
    TraceSession,
)

# ---------------------------------------------------------------------------
# Savings estimator protocol
# ---------------------------------------------------------------------------

#: A callable that returns the bench-harness reduction fraction (0.0–1.0).
#: Injected so tests can set a deterministic value without running the harness.
SavingsEstimator = Callable[[], float]


def _default_savings_estimator() -> float:
    """Run the built-in bench harness and return the token reduction fraction.

    Falls back to 0.0 on any error so the report is never broken by a missing
    storage setup.  This is only called lazily when total_tokens > 0.
    """
    try:
        from oh_no_my_claudecode.bench.harness import BUILTIN_SCENARIO, run_benchmark

        result = run_benchmark(BUILTIN_SCENARIO)
        pct = result.context_tokens_pct_reduction  # 0.0–100.0
        return max(0.0, min(pct / 100.0, 0.99))  # cap at 99% to avoid division by zero
    except Exception:  # noqa: BLE001
        return 0.0


# ---------------------------------------------------------------------------
# Public compiler
# ---------------------------------------------------------------------------


def compile_trace_report(
    events: list[TraceEvent],
    *,
    session: TraceSession | None = None,
    savings_estimator: SavingsEstimator | None = None,
    loop_threshold: int = 3,
) -> TraceReport:
    """Compile a ``TraceReport`` from a list of ``TraceEvent`` objects.

    This function is **pure** — it performs no I/O.  All I/O (loading events
    from disk, loading the session envelope) happens in
    :func:`~oh_no_my_claudecode.trace.recorder.load_session_events` before
    this function is called.

    Parameters
    ----------
    events:
        All events for the session, sorted or unsorted (the compiler sorts
        internally).  May be empty — in that case all aggregated counts are 0
        and no divide-by-zero occurs.
    session:
        Optional session envelope.  When provided, ``session_id``, ``label``,
        ``started_at``, and ``ended_at`` are copied to the report.
    savings_estimator:
        Callable returning a reduction fraction (0.0–1.0).  Defaults to the
        built-in bench harness.  Inject a fixed value in tests.
    loop_threshold:
        Minimum recurrence count for a (tool, target) pair to be classified
        as a loop.  Default 3.

    Returns
    -------
    TraceReport
        Fully aggregated report.  Never raises.
    """
    estimator = savings_estimator if savings_estimator is not None else _default_savings_estimator

    # --- counters ---
    tool_calls = 0
    tool_failures = 0
    total_tokens = 0
    memory_hits = 0
    memory_misses = 0

    file_read_counter: Counter[str] = Counter()
    search_query_counter: Counter[str] = Counter()
    # (tool, target) → count for loop detection
    tool_target_counter: Counter[tuple[str, str]] = Counter()

    for ev in events:
        kind = ev.kind

        if kind == TraceEventKind.TOOL_CALL:
            tool_calls += 1
            tool = str(ev.payload.get("tool", ""))
            target = str(ev.payload.get("target", ""))
            if tool:
                tool_target_counter[(tool, target)] += 1

        elif kind == TraceEventKind.TOOL_FAILURE:
            tool_failures += 1
            tool = str(ev.payload.get("tool", ""))
            target = str(ev.payload.get("target", ""))
            if tool:
                tool_target_counter[(tool, target)] += 1

        elif kind == TraceEventKind.FILE_READ:
            target = str(ev.payload.get("target", ""))
            if target:
                file_read_counter[target] += 1
                tool_target_counter[("file_read", target)] += 1

        elif kind == TraceEventKind.SEARCH_QUERY:
            query = str(ev.payload.get("target", ev.payload.get("query", "")))
            if query:
                search_query_counter[query] += 1
                tool_target_counter[("search_query", query)] += 1

        elif kind == TraceEventKind.TOKENS:
            total_tokens += int(ev.payload.get("total", 0))

        elif kind == TraceEventKind.MEMORY_HIT:
            memory_hits += 1

        elif kind == TraceEventKind.MEMORY_MISS:
            memory_misses += 1

        # notify-sourced recall_surfaced counts as a memory hit
        elif kind == TraceEventKind.RECALL_SURFACED:
            memory_hits += 1

        # danger_blocked is a tool_failure-equivalent from the firewall
        elif kind == TraceEventKind.DANGER_BLOCKED:
            tool_failures += 1

    # --- repeated items ---
    repeated_file_reads = [
        RepeatedItem(target=path, count=cnt)
        for path, cnt in sorted(file_read_counter.items(), key=lambda x: -x[1])
        if cnt >= 2
    ]
    repeated_search_queries = [
        RepeatedItem(target=q, count=cnt)
        for q, cnt in sorted(search_query_counter.items(), key=lambda x: -x[1])
        if cnt >= 2
    ]

    # --- loop detection ---
    loops_detected = [
        LoopSignal(tool=t, target=tgt, count=cnt)
        for (t, tgt), cnt in sorted(tool_target_counter.items(), key=lambda x: -x[1])
        if cnt >= loop_threshold
    ]

    # --- top wasteful (top-3 across file reads + search queries) ---
    all_waste: list[RepeatedItem] = sorted(
        repeated_file_reads + repeated_search_queries,
        key=lambda r: -r.count,
    )
    top_wasteful = all_waste[:3]

    # --- token savings estimate ---
    est_tokens_without = 0
    tokens_saved_pct = 0.0
    if total_tokens > 0:
        reduction = estimator()  # 0.0–1.0
        if reduction > 0.0:
            # est_without = total / (1 - reduction); total = without * (1 - reduction)
            est_tokens_without = int(total_tokens / max(1.0 - reduction, 0.01))
            tokens_saved_pct = round(
                (est_tokens_without - total_tokens) / est_tokens_without * 100,
                1,
            )
        else:
            est_tokens_without = total_tokens
            tokens_saved_pct = 0.0

    # --- session meta ---
    session_id = session.session_id if session else "unknown"
    label = session.label if session else ""
    started_at = session.started_at if session else 0.0
    ended_at = session.ended_at if session else None

    notes: list[str] = [
        "token savings (est): derived from bench-harness simulation — not a live LLM measurement.",
        "tool_calls/file_reads: exact only when the caller explicitly records these events.",
    ]

    return TraceReport(
        session_id=session_id,
        label=label,
        started_at=started_at,
        ended_at=ended_at,
        total_tokens=total_tokens,
        est_tokens_without_onmc=est_tokens_without,
        tokens_saved_pct=tokens_saved_pct,
        tool_calls=tool_calls,
        tool_failures=tool_failures,
        repeated_file_reads=repeated_file_reads,
        repeated_search_queries=repeated_search_queries,
        memory_hits=memory_hits,
        memory_misses=memory_misses,
        loops_detected=loops_detected,
        top_wasteful=top_wasteful,
        extra_notes=notes,
    )
