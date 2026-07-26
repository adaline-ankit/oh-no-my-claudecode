"""Data models for the Agent Trace Observatory.

Design notes
------------
- ``TraceEvent`` is a normalised view over ``NotifyEvent`` records plus additional
  trace-specific event kinds (tool_call, file_read, search_query, tokens,
  memory_hit, memory_miss).  Stored as JSONL; fields are a superset of
  ``NotifyEvent`` so the recorder can ingest both sources uniformly.
- ``TraceSession`` is the envelope written when ``onmc trace start`` is called.
- ``TraceReport`` is the fully aggregated report produced by
  ``compile_trace_report()`` from a list of ``TraceEvent`` objects.  All
  fields derived from heuristics or simulation are clearly labelled ``(est)``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TraceEventKind(StrEnum):
    """All recognised trace event kinds.

    Values prefixed with the source:

    - Notify-sourced: ``recall_surfaced``, ``danger_blocked``, ``memory_captured``,
      ``skill_promoted``, ``staleness_warning``, ``generic``.
    - Trace-native: ``tool_call``, ``file_read``, ``search_query``, ``tokens``,
      ``memory_hit``, ``memory_miss``.
    """

    # --- notify-sourced (mirrors EventKind) ---
    RECALL_SURFACED = "recall_surfaced"
    DANGER_BLOCKED = "danger_blocked"
    MEMORY_CAPTURED = "memory_captured"
    SKILL_PROMOTED = "skill_promoted"
    STALENESS_WARNING = "staleness_warning"
    GENERIC = "generic"

    # --- trace-native ---
    TOOL_CALL = "tool_call"
    TOOL_FAILURE = "tool_failure"
    RUNTIME_RUN = "runtime_run"
    RUNTIME_NODE = "runtime_node"
    FILE_READ = "file_read"
    SEARCH_QUERY = "search_query"
    TOKENS = "tokens"
    MEMORY_HIT = "memory_hit"
    MEMORY_MISS = "memory_miss"


@dataclass
class TraceEvent:
    """A single event recorded during a traced agent session.

    Parameters
    ----------
    kind:
        Coarse category — use ``TraceEventKind`` values (or a raw string for
        forward compatibility).
    ts:
        Unix timestamp (seconds).
    payload:
        Arbitrary event-specific data.  Common keys:

        - ``tool``      — for ``tool_call`` / ``tool_failure``: tool name.
        - ``target``    — for ``file_read`` / ``search_query``: path or query text.
        - ``total``     — for ``tokens``: total token count in this event.
        - ``query``     — for ``memory_hit`` / ``memory_miss``: lookup text.
        - ``title``     — for notify-sourced events: event title.
        - ``detail``    — for notify-sourced events: detail body.
    """

    kind: str
    ts: float = field(default_factory=time.time)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        """Serialise to a JSONL-friendly dict."""
        return {"kind": self.kind, "ts": self.ts, "payload": self.payload}

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> TraceEvent:
        """Deserialise from a JSONL record dict."""
        return cls(
            kind=str(record.get("kind", TraceEventKind.GENERIC)),
            ts=float(record.get("ts", time.time())),
            payload=dict(record.get("payload", {})),
        )

    @classmethod
    def from_notify_record(cls, record: dict[str, Any]) -> TraceEvent:
        """Convert a ``FileSink`` JSONL record into a ``TraceEvent``.

        FileSink writes: ``{ts, kind, severity, title, detail}``.  We promote
        ``kind`` directly (TraceEventKind values mirror EventKind values) and
        fold title/detail into ``payload``.
        """
        return cls(
            kind=str(record.get("kind", TraceEventKind.GENERIC)),
            ts=float(record.get("ts", time.time())),
            payload={
                "title": record.get("title", ""),
                "detail": record.get("detail", ""),
                "severity": record.get("severity", "routine"),
            },
        )


@dataclass
class TraceSession:
    """Envelope for a single traced agent session.

    Written as the first line of ``.onmc/traces/<session_id>.jsonl`` when
    ``onmc trace start`` is called.  ``ended_at`` is ``None`` until
    ``onmc trace stop`` is called.
    """

    session_id: str
    started_at: float
    ended_at: float | None = None
    label: str = ""  # optional human label set at start

    def to_record(self) -> dict[str, Any]:
        return {
            "_type": "session",
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "label": self.label,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> TraceSession:
        return cls(
            session_id=str(record["session_id"]),
            started_at=float(record["started_at"]),
            ended_at=float(record["ended_at"]) if record.get("ended_at") is not None else None,
            label=str(record.get("label", "")),
        )


@dataclass
class RepeatedItem:
    """A file path or query string seen more than once in a session."""

    target: str
    count: int


@dataclass
class LoopSignal:
    """A (tool, target) pair that recurred — indicates a potential loop."""

    tool: str
    target: str
    count: int


@dataclass
class TraceReport:
    """Aggregated token-ROI report for a single session.

    Fields
    ------
    session_id:
        ID of the traced session.
    label:
        Optional human label from ``onmc trace start --label``.
    started_at / ended_at:
        Session timestamps (Unix seconds).  ``ended_at`` is ``None`` for
        in-progress sessions; the report is still produced on partial data.
    total_tokens:
        Sum of all ``tokens`` events recorded during the session.  Exact when
        the caller explicitly records token events; 0 if none were recorded.
    est_tokens_without_onmc:
        Estimated total tokens the session would have consumed without onmc
        context injection.  Derived from ``total_tokens / (1 - reduction)``
        where ``reduction`` is the bench-harness percentage.  Labelled
        ``(est)`` — never claim precision.  0 when ``total_tokens`` is 0.
    tokens_saved_pct:
        ``(est_tokens_without_onmc - total_tokens) / est_tokens_without_onmc * 100``.
        Labelled ``(est)``.  0.0 when no tokens recorded.
    tool_calls:
        Total number of ``tool_call`` events.
    tool_failures:
        Total number of ``tool_failure`` events.
    repeated_file_reads:
        File paths read more than once, with counts.
    repeated_search_queries:
        Search query strings repeated more than once, with counts.
    memory_hits:
        Number of ``memory_hit`` events (onmc recall succeeded).
    memory_misses:
        Number of ``memory_miss`` events (onmc recall found nothing).
    loops_detected:
        (tool, target) pairs that recurred ≥ ``loop_threshold`` times.
    top_wasteful:
        Top-3 most repeated items (files or queries) across the session,
        sorted by count descending.
    extra_notes:
        Honesty caveats — always present, always honest.
    """

    session_id: str
    label: str = ""
    started_at: float = 0.0
    ended_at: float | None = None

    # --- token counts ---
    total_tokens: int = 0
    est_tokens_without_onmc: int = 0  # (est)
    tokens_saved_pct: float = 0.0  # (est)

    # --- tool call stats ---
    tool_calls: int = 0
    tool_failures: int = 0

    # --- repetition / waste ---
    repeated_file_reads: list[RepeatedItem] = field(default_factory=list)
    repeated_search_queries: list[RepeatedItem] = field(default_factory=list)

    # --- memory stats ---
    memory_hits: int = 0
    memory_misses: int = 0

    # --- loop detection ---
    loops_detected: list[LoopSignal] = field(default_factory=list)

    # --- top wasteful items ---
    top_wasteful: list[RepeatedItem] = field(default_factory=list)

    # --- meta ---
    extra_notes: list[str] = field(default_factory=list)

    @property
    def memory_hit_rate(self) -> float:
        """Fraction of memory lookups that succeeded (0.0–1.0)."""
        total = self.memory_hits + self.memory_misses
        return self.memory_hits / total if total > 0 else 0.0

    @property
    def repeated_reads_blocked(self) -> int:
        """Total redundant reads that onmc helped avoid (sum of excess counts)."""
        return sum(max(0, r.count - 1) for r in self.repeated_file_reads)
