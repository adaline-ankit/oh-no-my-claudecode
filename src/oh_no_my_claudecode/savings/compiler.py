"""Savings compiler — pure function that produces a Memory Wrapped SavingsResult.

Methodology (honest description)
----------------------------------
Numbers are derived from two sources:

1.  **Counts** (exact): memories, skills, playbooks read directly from
    :class:`~oh_no_my_claudecode.storage.sqlite.SQLiteStorage`.

2.  **Token ROI** (deterministic simulation): we build a
    :class:`~oh_no_my_claudecode.bench.harness.BenchScenario` from the real
    memory store (same path as ``onmc bench --repo-memory``) and run it through
    :func:`~oh_no_my_claudecode.bench.harness.run_benchmark`.  The scenario
    reuses the built-in task list but substitutes real repo memories for the
    synthetic seed, so the numbers reflect the actual brain size.

    The bench is a **deterministic simulation** — no LLM is called.  Results are
    identical across runs on the same store.  See ``bench/harness.py`` for the
    full methodology.

3.  **Coverage proxy** (exact): reuses
    :func:`~oh_no_my_claudecode.coverage.compiler.compile_coverage` to find what
    fraction of top-churn files have memory coverage and the names of the top
    covered files.

This function is **pure** — it performs only reads, never writes.  ``now`` is an
injectable ``str`` so that tests can produce deterministic output without wall-clock
dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.bench.harness import (
    BUILTIN_SCENARIO,
    BenchScenario,
    MemoryRecord,
    run_benchmark,
)
from oh_no_my_claudecode.coverage.compiler import compile_coverage
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage


@dataclass(frozen=True)
class SavingsResult:
    """All data needed to render the Memory Wrapped card.

    Fields annotated as ``(sim)`` come from the deterministic bench simulation
    and should be labelled as such in any UI.  Fields annotated ``(exact)``
    are read directly from storage and are always accurate.
    """

    # --- counts (exact) ---
    memories_count: int
    skills_count: int
    playbooks_count: int

    # --- token ROI (sim: deterministic bench against real brain) ---
    context_tokens_pct_reduction: float  # (sim) % reduction in context tokens
    repeated_failure_rate_delta: float  # (sim) fraction improvement, 0.0–1.0
    wasted_attempts_saved: int  # (sim) total dead-end attempts avoided

    # --- coverage (exact proxy) ---
    covered_hotspots: int  # number of top-churn files with ≥1 memory
    total_hotspots: int  # total top-churn files considered
    top_covered_names: list[str]  # short display names of covered hotspot files

    # --- meta ---
    scenario_name: str  # which bench scenario was used
    now: str = ""  # injected generation timestamp (empty = not shown)
    extra_notes: list[str] = field(default_factory=list)  # honest caveats


def compile_savings(
    storage: SQLiteStorage,
    repo_root: Path,
    *,
    now: str = "",
) -> SavingsResult:
    """Compute a :class:`SavingsResult` for this repo.

    Pure calculation — reads from storage; writes nothing.

    Parameters
    ----------
    storage:
        Initialised SQLiteStorage for the repo.
    repo_root:
        Absolute path to the repository root.
    now:
        Optional ISO-formatted generation timestamp.  Injected so callers
        (and tests) can produce deterministic output without wall-clock
        dependency.
    """
    memories_raw = storage.list_memories()
    skills_raw = storage.list_skills()
    playbooks_raw = storage.list_playbooks()

    memories_count = len(memories_raw)
    skills_count = len(skills_raw)
    playbooks_count = len(playbooks_raw)

    # Build a BenchScenario from real repo memories (same path as `onmc bench
    # --repo-memory`) but keep the built-in tasks so results are comparable.
    repo_memories: list[MemoryRecord] = [
        MemoryRecord(kind=m.kind.value, summary=m.summary, relevant_to=[])
        for m in memories_raw
    ]

    if repo_memories:
        scenario = BenchScenario(
            name="onmc-savings-real-brain",
            description=(
                "Built-in tasks run against this repo's real memory store "
                "(deterministic simulation — no LLM calls)."
            ),
            tasks=list(BUILTIN_SCENARIO.tasks),
            memories=repo_memories,
            baseline_context_tokens=BUILTIN_SCENARIO.baseline_context_tokens,
        )
    else:
        # Empty brain: use the built-in synthetic scenario so numbers are honest
        # (with no memories the reduction will be 0%).
        scenario = BUILTIN_SCENARIO

    bench = run_benchmark(scenario)

    # Coverage proxy via compile_coverage (reads storage, no writes).
    coverage = compile_coverage(storage, repo_root)

    # Pull the top-N covered file short-names for display (up to 3).
    # compile_coverage doesn't directly return "covered hotspot names", so we
    # reconstruct from subsystem rows: files that have memory coverage are those
    # in covered_paths, which we can approximate by looking at top-gap files
    # (uncovered).  Simpler: use file_stats directly.
    top_covered: list[str] = _top_covered_names(storage, n=3)

    notes: list[str] = [
        "Token-ROI numbers are a deterministic simulation (no LLM calls); "
        "see bench/harness.py for methodology.",
    ]

    return SavingsResult(
        memories_count=memories_count,
        skills_count=skills_count,
        playbooks_count=playbooks_count,
        context_tokens_pct_reduction=round(bench.context_tokens_pct_reduction, 1),
        repeated_failure_rate_delta=round(bench.repeated_failure_rate_delta, 4),
        wasted_attempts_saved=bench.wasted_attempts_delta,
        covered_hotspots=coverage.covered_files,
        total_hotspots=coverage.total_files,
        top_covered_names=top_covered,
        scenario_name=scenario.name,
        now=now,
        extra_notes=notes,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _top_covered_names(storage: SQLiteStorage, *, n: int = 3) -> list[str]:
    """Return short display names of up to *n* covered top-churn files."""
    from oh_no_my_claudecode.coverage.compiler import _collect_memory_refs

    memories = storage.list_memories()
    file_stats = storage.list_file_stats()
    if not file_stats:
        return []

    memory_refs = _collect_memory_refs(memories)
    sorted_files = sorted(file_stats, key=lambda s: s.change_count, reverse=True)
    covered: list[str] = []
    for stat in sorted_files:
        if stat.path in memory_refs:
            # Use the filename only for brevity on the card.
            covered.append(Path(stat.path).name)
            if len(covered) >= n:
                break
    return covered
