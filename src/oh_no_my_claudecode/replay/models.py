"""Data models for the onmc Replay Lab.

Replay consumes a recorded trace session (a list of :class:`TraceEvent` objects)
and re-derives what onmc WOULD have surfaced at each step given the current brain,
without re-running any agent or LLM.

Model hierarchy
---------------
- :class:`ReplayStep` — one step in the replay (one query-bearing event).
- :class:`ReplayReport` — aggregate over all steps for one memory condition.
- :class:`ReplayComparison` — side-by-side with-memory vs without-memory report.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReplayStep:
    """One step in a replayed trace session.

    Attributes
    ----------
    index:
        Zero-based position of this event in the original event list.
    query:
        Text derived from the event's payload that was used as the recall/guard
        query (e.g. from ``payload["query"]``, ``payload["target"]``, or
        ``payload["title"]``).
    recall_hits:
        Number of :class:`~oh_no_my_claudecode.recall.compiler.RecallEntry`
        objects returned by ``compile_recall`` for this step's query.
        Zero when ``with_memory=False``.
    deadend_hits:
        Number of :class:`~oh_no_my_claudecode.guard.compiler.GuardEntry`
        objects returned by ``compile_guard`` for this step's query.
        Zero when ``with_memory=False``.
    injected_chars:
        Total character length of all recall entry text returned for this step.
        Zero when ``with_memory=False``.
    """

    index: int
    query: str
    recall_hits: int = 0
    deadend_hits: int = 0
    injected_chars: int = 0


@dataclass
class ReplayReport:
    """Aggregate replay metrics for one memory condition (with or without memory).

    Attributes
    ----------
    session_id:
        Identifier of the replayed trace session (may be an empty string when
        replaying from a raw event list with no session envelope).
    steps:
        Per-step results — one entry per query-bearing event.
    total_steps:
        Total number of query-bearing events replayed.
    steps_with_recall:
        Number of steps where ``compile_recall`` returned at least one entry.
    steps_with_deadend:
        Number of steps where ``compile_guard`` returned at least one entry.
    mean_injected_chars:
        Mean ``injected_chars`` across all steps (context-cost proxy).
    with_memory:
        ``True`` when this report was produced against the live brain;
        ``False`` for the cold (no-memory) baseline.
    """

    session_id: str
    steps: list[ReplayStep] = field(default_factory=list)
    total_steps: int = 0
    steps_with_recall: int = 0
    steps_with_deadend: int = 0
    mean_injected_chars: float = 0.0
    with_memory: bool = True


@dataclass
class ReplayComparison:
    """Side-by-side with-memory vs without-memory replay comparison.

    Attributes
    ----------
    with_memory:
        Report produced with the live brain.
    without_memory:
        Report produced with no retrieval (cold baseline — all empty).
    deltas:
        Aggregate delta metrics:

        - ``steps_where_recall_added`` — count of steps where memory surfaced
          recall entries that the baseline did not (i.e. recall_hits > 0 in the
          with-memory report but 0 without).
        - ``steps_where_deadend_added`` — count of steps where memory surfaced
          guard entries that the baseline did not.
        - ``steps_where_context_changed`` — count of steps where the injected
          char count differs between conditions (memory changed the context the
          agent would receive).
        - ``mean_chars_delta`` — difference in ``mean_injected_chars`` between
          with-memory and without-memory (positive = memory adds context).
    """

    with_memory: ReplayReport
    without_memory: ReplayReport
    deltas: dict[str, float] = field(default_factory=dict)
