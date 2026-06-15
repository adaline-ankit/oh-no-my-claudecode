"""Memory health computation for ONMC's HUD and statusline.

Pure, typed functions — no side effects beyond filesystem reads.

Decision: we aggregate cost/tokens from the EXISTING llm-calls.jsonl log
file.  No migration v7 is needed because:
  - The file is written by every LLM call already.
  - We only need the last N entries / last 24 h, so a tail-read is sufficient.
  - A new ``task_costs`` table would replicate what the log already has and
    would require coordinating with schema v7, adding migration coupling.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from oh_no_my_claudecode.memory.staleness import classify_staleness
from oh_no_my_claudecode.models import FileStat
from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

# How many recent log lines to cap the scan at to keep statusline fast.
_LOG_TAIL_LINES = 2_000
# How many hours back to count as "recent" for cost aggregation.
_RECENT_HOURS = 24
# Top-N highest-churn files used for coverage proxy.
_TOP_CHURN_FILES = 20


@dataclass(slots=True)
class RecentCost:
    """Aggregated LLM cost/token stats from the last :data:`_RECENT_HOURS` hours."""

    total_prompt_tokens: int
    total_response_tokens: int
    total_tokens: int
    total_latency_ms: float
    call_count: int
    window_hours: int = _RECENT_HOURS


@dataclass(slots=True)
class MemoryHealth:
    """Snapshot of the brain's observable state."""

    # Totals
    total_memories: int
    counts_by_kind: dict[str, int]

    # Freshness — among anchored memories (non-"unanchored") only
    fresh_count: int
    stale_count: int
    orphaned_count: int
    unanchored_count: int
    freshness_pct: float  # fresh / (anchored total) * 100, or 100.0 when 0 anchored

    # Coverage proxy: share of top-churn files that have ≥1 related memory
    coverage_pct: float
    covered_files: int
    top_churn_files: int

    # Recent LLM activity
    recent_cost: RecentCost

    # Stale memory titles (up to 10) for the HUD display
    stale_titles: list[str] = field(default_factory=list)


def compute_memory_health(
    storage: SQLiteStorage,
    repo_root: Path,
    log_path: Path,
) -> MemoryHealth:
    """Compute a :class:`MemoryHealth` snapshot.

    Pure calculation — reads from storage, disk, and log_path; writes nothing.

    Parameters
    ----------
    storage:
        Initialised SQLiteStorage for the repo.
    repo_root:
        Absolute path to the repository root (used for staleness checks).
    log_path:
        Path to ``.onmc/logs/llm-calls.jsonl`` (may not exist — handled).
    """
    memories = storage.list_memories()
    file_stats = storage.list_file_stats()

    counts_by_kind = _count_by_kind(memories)
    fresh_count, stale_count, orphaned_count, unanchored_count, stale_titles = _classify(
        memories, repo_root
    )
    anchored = fresh_count + stale_count + orphaned_count
    freshness_pct = (fresh_count / anchored * 100.0) if anchored > 0 else 100.0

    coverage_pct, covered, top_n = _coverage(memories, file_stats)
    recent_cost = _aggregate_cost(log_path)

    return MemoryHealth(
        total_memories=len(memories),
        counts_by_kind=counts_by_kind,
        fresh_count=fresh_count,
        stale_count=stale_count,
        orphaned_count=orphaned_count,
        unanchored_count=unanchored_count,
        freshness_pct=round(freshness_pct, 1),
        coverage_pct=round(coverage_pct, 1),
        covered_files=covered,
        top_churn_files=top_n,
        recent_cost=recent_cost,
        stale_titles=stale_titles,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _count_by_kind(memories: list[MemoryEntry]) -> dict[str, int]:
    counts: dict[str, int] = {k.value: 0 for k in MemoryKind}
    for mem in memories:
        counts[mem.kind.value] = counts.get(mem.kind.value, 0) + 1
    return {k: v for k, v in counts.items() if v > 0}


def _classify(
    memories: list[MemoryEntry],
    repo_root: Path,
) -> tuple[int, int, int, int, list[str]]:
    """Return (fresh, stale, orphaned, unanchored, stale_titles).

    Uses the stored ``staleness`` field when populated (fast path); falls back
    to :func:`classify_staleness` for unclassified memories.
    """
    fresh = stale = orphaned = unanchored = 0
    stale_titles: list[str] = []

    for mem in memories:
        label = mem.staleness
        if label is None:
            # Run classification on-the-fly (no stored label yet)
            label = classify_staleness(repo_root, mem)

        if label == "fresh":
            fresh += 1
        elif label == "stale":
            stale += 1
            if len(stale_titles) < 10:
                stale_titles.append(mem.title)
        elif label == "orphaned":
            orphaned += 1
        else:  # "unanchored"
            unanchored += 1

    return fresh, stale, orphaned, unanchored, stale_titles


def _coverage(
    memories: list[MemoryEntry],
    file_stats: Sequence[FileStat],
) -> tuple[float, int, int]:
    """Coverage proxy: fraction of top-churn files with ≥1 related memory.

    Returns (coverage_pct, covered_files, top_n).
    """
    fs_list = list(file_stats)
    if not fs_list:
        return 0.0, 0, 0

    sorted_files = sorted(fs_list, key=lambda s: s.change_count, reverse=True)
    top_files = sorted_files[:_TOP_CHURN_FILES]
    top_paths = {s.path for s in top_files}

    # Collect all source_refs across memories (pipe-separated)
    memory_refs: set[str] = set()
    for mem in memories:
        for token in mem.source_ref.split("|"):
            memory_refs.add(token.strip())

    covered = sum(1 for path in top_paths if path in memory_refs)
    top_n = len(top_files)
    pct = (covered / top_n * 100.0) if top_n > 0 else 0.0
    return pct, covered, top_n


def _aggregate_cost(log_path: Path) -> RecentCost:
    """Parse the last N lines of llm-calls.jsonl and aggregate token stats.

    Defensive: handles missing file, corrupt JSON, missing fields gracefully.
    Only counts entries within the last :data:`_RECENT_HOURS` hours.
    """
    cutoff = datetime.now(tz=UTC) - timedelta(hours=_RECENT_HOURS)

    if not log_path.exists():
        return _empty_cost()

    try:
        raw_lines = _tail_lines(log_path, _LOG_TAIL_LINES)
    except OSError:
        return _empty_cost()

    total_prompt = total_response = call_count = 0
    total_latency = 0.0

    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        ts_raw = entry.get("timestamp")
        if ts_raw:
            try:
                ts = datetime.fromisoformat(ts_raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < cutoff:
                    continue
            except ValueError:
                pass  # malformed timestamp — include the entry anyway

        prompt_tok = entry.get("prompt_token_count")
        resp_tok = entry.get("response_token_count")
        latency = entry.get("latency_ms")

        if isinstance(prompt_tok, int):
            total_prompt += prompt_tok
        if isinstance(resp_tok, int):
            total_response += resp_tok
        if isinstance(latency, (int, float)):
            total_latency += float(latency)
        call_count += 1

    return RecentCost(
        total_prompt_tokens=total_prompt,
        total_response_tokens=total_response,
        total_tokens=total_prompt + total_response,
        total_latency_ms=round(total_latency, 1),
        call_count=call_count,
    )


def _tail_lines(path: Path, n: int) -> list[str]:
    """Read the last *n* lines of *path* efficiently."""
    chunk_size = 8192
    byte_lines: list[bytes] = []
    with path.open("rb") as f:
        f.seek(0, 2)
        remaining = f.tell()
        buf: bytes = b""
        while remaining > 0 and len(byte_lines) < n:
            read_size = min(chunk_size, remaining)
            remaining -= read_size
            f.seek(remaining)
            chunk = f.read(read_size)
            buf = chunk + buf
            all_parts = buf.split(b"\n")
            # Keep the leftmost partial line in buf for the next iteration
            buf = all_parts[0]
            byte_lines = all_parts[1:] + byte_lines
    # Include whatever is left in buf
    if buf:
        byte_lines = [buf] + byte_lines
    return [raw.decode("utf-8", errors="replace") for raw in byte_lines[-n:]]


def _empty_cost() -> RecentCost:
    return RecentCost(
        total_prompt_tokens=0,
        total_response_tokens=0,
        total_tokens=0,
        total_latency_ms=0.0,
        call_count=0,
    )
