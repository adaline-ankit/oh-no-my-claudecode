"""Reproducible benchmark suite for onmc effectiveness measurement.

Methodology (honest description)
----------------------------------
This module runs FIVE benchmarks and labels each one clearly:

  MEASURED — live computation against the current repo's brain (no LLM, no
  network).  Numbers will vary across brain sizes and hardware timing, but the
  *computation* is real.  P50/P95 latencies use wall-clock time via an
  injectable timer so tests can feed deterministic values without network/LLM.

  SIM — deterministic simulation (same harness as ``onmc bench``).  A fixed
  scenario is run and the numbers are identical across machines and runs for
  the same brain state.  Clearly labelled as simulation.

Benchmark set
-------------
1. recall_latency  (MEASURED)
   Time ``compile_recall`` over a fixed query set.  Uses the brain's own memory
   titles as queries when the brain has ≥3 memories, otherwise falls back to a
   built-in query set.  Reports p50/p95 wall-clock ms and hits/query.

2. terse_vs_verbose (MEASURED)
   For each query, compare:
     - terse injection: concatenated titles + terse citations (no markdown)
     - verbose injection: RecallResult.to_markdown()
   Reports mean % character reduction (positive = terse is smaller).

3. toon_vs_json (MEASURED)
   Serialize a recall payload (list of dicts from the top recall result) as:
     - compact JSON (json.dumps with separators)
     - TOON (to_toon)
   Reports % character reduction.  Notes that reduction scales with table size.
   When the brain is empty, reports 0 with a note.

4. brain_composition (MEASURED)
   Count memories (total + per-kind) by reading storage directly.
   Returns exact counts — no estimation.

5. harness_sim (SIM)
   Runs ``bench/harness.py`` ``run_benchmark`` against the canonical
   ``BUILTIN_SCENARIO`` (fixed tasks + fixed seeded memories).  Produces
   stable, reproducible numbers regardless of live brain size: −97% token
   reduction, −100% repeated-failure rate, −9 wasted attempts.
   Reports repeated_failure_rate delta (%), wasted_attempts_delta,
   context_tokens_pct_reduction, tasks_resolved_delta.

No LLM calls, no network I/O.  Pure reads + timing.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from oh_no_my_claudecode.bench.harness import (
    BUILTIN_SCENARIO,
    run_benchmark,
)
from oh_no_my_claudecode.recall.compiler import compile_recall
from oh_no_my_claudecode.serialize.toon import to_toon
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

MetricKind = Literal["measured", "sim"]

#: Built-in fallback query set used when the brain has fewer than 3 memories.
#: Chosen to exercise common engineering memory patterns without being trivial.
_FALLBACK_QUERIES: list[str] = [
    "TypeError cannot import name",
    "sqlite3 OperationalError no such table",
    "cache invalidation race condition",
    "hook stdout must be pure JSON",
    "ruff check E501 line too long",
]


@dataclass(frozen=True)
class BenchmarkMetric:
    """One measurement from the benchmark suite.

    Attributes
    ----------
    name:
        Short camelCase identifier (e.g. ``"recall_p50_ms"``).
    value:
        The measured or simulated value.
    unit:
        Human-readable unit string (e.g. ``"ms"``, ``"%"``, ``"count"``).
    kind:
        ``"measured"`` — live computation, wall-clock or exact counts.
        ``"sim"`` — deterministic simulation, no LLM.
    detail:
        Optional free-text note surfaced in the report for context or caveats.
    """

    name: str
    value: float
    unit: str
    kind: MetricKind
    detail: str = ""


@dataclass
class BenchmarkReport:
    """Full benchmark suite output.

    Attributes
    ----------
    metrics:
        Ordered list of all benchmark metrics (MEASURED then SIM).
    brain_memory_count:
        Total memory count in the repo brain at time of run.
    generated_note:
        Free-text note about how to reproduce this run (printed as footer).
    """

    metrics: list[BenchmarkMetric] = field(default_factory=list)
    brain_memory_count: int = 0
    generated_note: str = ""

    def metrics_by_kind(self, kind: MetricKind) -> list[BenchmarkMetric]:
        """Return only metrics with the given kind label."""
        return [m for m in self.metrics if m.kind == kind]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

TimerFn = Callable[[], float]


def _pct_char_reduction(original: str, compressed: str) -> float:
    """Return percentage char reduction; 0 when original is empty."""
    if not original:
        return 0.0
    reduction = (len(original) - len(compressed)) / len(original) * 100.0
    return max(-100.0, min(100.0, reduction))


def _build_queries(storage: SQLiteStorage) -> list[str]:
    """Pick query strings from the brain's own titles, falling back to built-ins."""
    try:
        memories = storage.list_memories()
    except Exception:  # noqa: BLE001
        memories = []

    titles = [m.title for m in memories if m.title.strip()][:10]
    if len(titles) >= 3:  # noqa: PLR2004
        return titles
    return _FALLBACK_QUERIES


def _terse_injection(result_entries: list) -> str:  # type: ignore[type-arg]
    """Compact terse form: one line per entry — title + terse citation."""
    parts: list[str] = []
    for entry in result_entries:
        citation = getattr(entry, "citation", "")
        terse = f"[{citation}]" if citation else ""
        parts.append(f"{entry.title} {terse}".strip())
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_benchmark_suite(
    storage: SQLiteStorage,
    repo_root: Path,
    *,
    queries: list[str] | None = None,
    runs: int = 20,
    now: str | None = None,
    timer: TimerFn | None = None,
) -> BenchmarkReport:
    """Run the full benchmark suite and return a :class:`BenchmarkReport`.

    Parameters
    ----------
    storage:
        Initialised :class:`~oh_no_my_claudecode.storage.sqlite.SQLiteStorage`
        for the current repo.
    repo_root:
        Repo root path (used for context in the report note).
    queries:
        Query strings for the recall benchmarks.  When ``None``, the function
        derives them from the brain's own memory titles (falling back to a
        built-in set when the brain is small).
    runs:
        How many times to run each timed benchmark.  Higher → more stable p95.
        Minimum 1; values below 1 are clamped to 1.
    now:
        ISO-8601 string for the report footer.  Defaults to the current UTC
        time when ``None``.
    timer:
        A zero-argument callable returning a float timestamp in seconds
        (default: :func:`time.perf_counter`).  Injectable for tests to provide
        deterministic timings.

    Returns
    -------
    BenchmarkReport
        Contains all metrics labelled MEASURED or SIM, plus the brain count
        and a reproducibility note.

    Notes
    -----
    This function performs only reads (and timing).  It never writes to storage,
    calls any LLM, or makes network requests.  Results are deterministic except
    for the wall-clock timings when using the real timer.
    """
    _timer: TimerFn = timer if timer is not None else time.perf_counter
    _runs = max(1, runs)

    # Determine the query set once.
    _queries: list[str] = queries if queries is not None else _build_queries(storage)
    if not _queries:
        _queries = _FALLBACK_QUERIES

    metrics: list[BenchmarkMetric] = []

    # -----------------------------------------------------------------------
    # 1. Brain composition (MEASURED — exact counts, no timing)
    # -----------------------------------------------------------------------
    try:
        all_memories = storage.list_memories()
    except Exception:  # noqa: BLE001
        all_memories = []

    brain_count = len(all_memories)
    kind_counts: Counter[str] = Counter(m.kind.value for m in all_memories)

    metrics.append(
        BenchmarkMetric(
            name="brain_memory_count",
            value=float(brain_count),
            unit="count",
            kind="measured",
            detail="Total memory entries in the repo brain (storage.list_memories()).",
        )
    )
    for kind_name, cnt in sorted(kind_counts.items()):
        metrics.append(
            BenchmarkMetric(
                name=f"brain_kind_{kind_name}",
                value=float(cnt),
                unit="count",
                kind="measured",
                detail=f"Memories of kind '{kind_name}'.",
            )
        )

    # -----------------------------------------------------------------------
    # 2. Recall latency (MEASURED — wall-clock timing)
    # -----------------------------------------------------------------------
    latencies_ms: list[float] = []
    total_hits = 0
    total_queries_run = 0

    for _ in range(_runs):
        for q in _queries:
            t0 = _timer()
            try:
                result = compile_recall(storage, q, limit=8)
            except Exception:  # noqa: BLE001
                result = None
            t1 = _timer()
            latencies_ms.append((t1 - t0) * 1000.0)
            total_queries_run += 1
            if result is not None and result.has_matches:
                total_hits += len(result.entries)

    if latencies_ms:
        sorted_lat = sorted(latencies_ms)
        n = len(sorted_lat)
        p50_idx = max(0, int(n * 0.50) - 1)
        p95_idx = max(0, int(n * 0.95) - 1)
        p50_ms = sorted_lat[p50_idx]
        p95_ms = sorted_lat[p95_idx]
        hits_per_query = total_hits / total_queries_run if total_queries_run > 0 else 0.0
    else:
        p50_ms = 0.0
        p95_ms = 0.0
        hits_per_query = 0.0

    metrics.append(
        BenchmarkMetric(
            name="recall_p50_ms",
            value=round(p50_ms, 3),
            unit="ms",
            kind="measured",
            detail=(
                f"Median compile_recall latency over {_runs} runs × {len(_queries)} queries"
                f" = {total_queries_run} total calls."
            ),
        )
    )
    metrics.append(
        BenchmarkMetric(
            name="recall_p95_ms",
            value=round(p95_ms, 3),
            unit="ms",
            kind="measured",
            detail=f"95th-percentile compile_recall latency ({total_queries_run} total calls).",
        )
    )
    metrics.append(
        BenchmarkMetric(
            name="recall_hits_per_query",
            value=round(hits_per_query, 2),
            unit="entries/query",
            kind="measured",
            detail=(
                "Mean recall entries returned per query (limit=8). "
                "0 = brain too small or no overlap with query set."
            ),
        )
    )

    # -----------------------------------------------------------------------
    # 3. Terse-vs-verbose injection (MEASURED — character counts)
    # -----------------------------------------------------------------------
    terse_sizes: list[int] = []
    verbose_sizes: list[int] = []
    reductions: list[float] = []

    for q in _queries:
        rr = None
        with contextlib.suppress(Exception):
            rr = compile_recall(storage, q, limit=8)
        if rr is None or not rr.has_matches:
            continue
        terse = _terse_injection(rr.entries)
        verbose = rr.to_markdown()
        terse_sizes.append(len(terse))
        verbose_sizes.append(len(verbose))
        reductions.append(_pct_char_reduction(verbose, terse))

    mean_reduction = sum(reductions) / len(reductions) if reductions else 0.0
    metrics.append(
        BenchmarkMetric(
            name="terse_vs_verbose_char_reduction_pct",
            value=round(mean_reduction, 1),
            unit="%",
            kind="measured",
            detail=(
                "Mean character reduction: terse injection (title+citation) vs "
                "RecallResult.to_markdown(). Computed over queries that returned ≥1 match. "
                f"Samples: {len(reductions)} of {len(_queries)} queries matched."
            ),
        )
    )

    # -----------------------------------------------------------------------
    # 4. TOON-vs-JSON payload (MEASURED — character counts)
    # -----------------------------------------------------------------------
    # Build a representative payload from the first query that has matches.
    toon_reduction_pct = 0.0
    toon_detail = "No matching recall results — brain too small to measure."

    for q in _queries:
        rr = None
        with contextlib.suppress(Exception):
            rr = compile_recall(storage, q, limit=8)
        if rr is None or not rr.has_matches:
            continue
        # Convert recall entries to a list[dict] for TOON encoding.
        payload: list[dict[str, object]] = [
            {
                "title": e.title,
                "kind": e.kind,
                "confidence": round(e.confidence, 3),
                "relevance": round(e.relevance, 3),
                "citation": e.citation,
            }
            for e in rr.entries
        ]
        json_str = json.dumps(payload, separators=(",", ":"))
        toon_str = to_toon(payload)
        toon_reduction_pct = _pct_char_reduction(json_str, toon_str)
        toon_detail = (
            f"Compact JSON vs TOON encoding of a {len(payload)}-row recall payload. "
            f"JSON: {len(json_str)} chars, TOON: {len(toon_str)} chars. "
            "Reduction scales with row count (tabular TOON drops repeated key names)."
        )
        break

    metrics.append(
        BenchmarkMetric(
            name="toon_vs_json_char_reduction_pct",
            value=round(toon_reduction_pct, 1),
            unit="%",
            kind="measured",
            detail=toon_detail,
        )
    )

    # -----------------------------------------------------------------------
    # 5. Deterministic harness simulation (SIM)
    # -----------------------------------------------------------------------
    # Always run against the canonical BUILTIN_SCENARIO — fixed tasks AND
    # fixed seeded memories.  This gives reproducible numbers (97% token
    # reduction, 100%→0% repeated-failure) regardless of the live brain size.
    # The MEASURED section already captures live-brain characteristics.
    sim_result = run_benchmark(BUILTIN_SCENARIO)

    # repeated_failure_rate_delta is 0.0–1.0 fraction; surface as a percentage
    # reduction (positive value = improvement) so "1.0 fraction" never appears.
    sim_rfr_pct = round(sim_result.repeated_failure_rate_delta * 100.0, 1)
    metrics.append(
        BenchmarkMetric(
            name="sim_repeated_failure_rate_delta",
            value=sim_rfr_pct,
            unit="%",
            kind="sim",
            detail=(
                "Reduction in repeated-failure rate: 100% = memory eliminates all dead-end "
                "re-attempts in the built-in scenario (5 engineering tasks). "
                "Canonical value: −100% (all 5 tasks go from retrying dead-ends to zero)."
            ),
        )
    )
    metrics.append(
        BenchmarkMetric(
            name="sim_wasted_attempts_saved",
            value=float(sim_result.wasted_attempts_delta),
            unit="attempts",
            kind="sim",
            detail="Total dead-end attempts saved across all tasks (without − with).",
        )
    )
    metrics.append(
        BenchmarkMetric(
            name="sim_context_tokens_pct_reduction",
            value=round(sim_result.context_tokens_pct_reduction, 1),
            unit="%",
            kind="sim",
            detail=(
                "Context-token reduction: compact brief (107 tokens) vs large "
                f"baseline ({BUILTIN_SCENARIO.baseline_context_tokens} tokens × "
                f"{len(BUILTIN_SCENARIO.tasks)} tasks). "
                "Canonical value: −97% (4000 → 107 tokens)."
            ),
        )
    )
    metrics.append(
        BenchmarkMetric(
            name="sim_tasks_resolved_delta",
            value=float(sim_result.tasks_resolved_delta),
            unit="tasks",
            kind="sim",
            detail="Additional tasks resolved within attempt budget with memory (with − without).",
        )
    )

    # -----------------------------------------------------------------------
    # Assemble report
    # -----------------------------------------------------------------------
    if now is None:
        from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now

        now = isoformat_utc(utc_now())

    note = (
        f"Generated {now} | repo: {repo_root.name} | brain: {brain_count} memories | "
        f"runs: {_runs} | queries: {len(_queries)} | "
        "Reproduce: onmc benchmark [--runs N] [--json]"
    )

    return BenchmarkReport(
        metrics=metrics,
        brain_memory_count=brain_count,
        generated_note=note,
    )
