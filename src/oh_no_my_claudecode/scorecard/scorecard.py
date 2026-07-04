"""The ``onmc scorecard`` aggregator — one shareable agent-readiness + trust report.

``scorecard`` invents no new analysis.  It is a **defensive aggregator** that ties
four existing onmc signals into a single, shareable artifact a repo can show off:

- **Readiness** — the 0-100 agent-readiness score from
  :func:`oh_no_my_claudecode.roast.scorer.compute_roast` (hotspot coverage, audit
  grade, brain size, conventions).
- **Top agent + trust** — the highest-trust agent from the reputation ledger
  (:func:`oh_no_my_claudecode.registry.registry.build_registry` +
  :func:`~oh_no_my_claudecode.registry.registry.rank`).
- **Best model** — the model that has historically delivered verified results,
  from :func:`oh_no_my_claudecode.flywheel.analyze.summarize`.
- **Institutional-memory coverage** — entity/edge counts from
  :func:`oh_no_my_claudecode.orggraph.graph.build_org_graph`.

Design constraints
------------------
- **Deterministic** where the inputs are: the same repo + brain + ledger yields
  the same scorecard, byte-for-byte.  No LLM call, fully offline.
- **Defensive** — this is an aggregator over four independent subsystems, any of
  which may be *absent* (no storage, no ledger, no receipts, empty brain).  Every
  signal is computed in its own ``try/except``; on any failure the field degrades
  to ``None`` and a human-readable note explains why.  A missing signal must never
  crash the scorecard.
- **Honest** — numbers are only ever read from the real readers.  A ``None`` field
  means "n/a", never a fabricated ``0``.

Testability
-----------
:func:`build_scorecard` accepts optional signal callables (defaulting to the real
readers) so the aggregation logic can be unit-tested purely — inject readers that
return known values, or that raise, and assert the graceful outcome.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

__all__ = [
    "Scorecard",
    "build_scorecard",
    "render_markdown",
    "render_summary",
    "read_readiness",
    "read_top_agent",
    "read_best_model",
    "read_memory_graph",
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Scorecard:
    """The aggregated agent-readiness + trust scorecard for one repo.

    Every field is ``None`` when its underlying signal was unavailable — an honest
    "n/a" rather than a fabricated zero.  ``notes`` records, in stable order, why
    any signal degraded.

    Attributes
    ----------
    readiness:
        0-100 agent-readiness score (from ``roast``), or ``None``.
    top_agent:
        Subject id of the highest-trust agent in the reputation ledger, or
        ``None`` when the ledger is empty / unavailable.
    top_agent_trust:
        That agent's ``trust_score`` in ``[0, 1]``, or ``None``.
    best_model:
        Model with the best verified track record (from ``flywheel``), or
        ``None`` when there is insufficient receipt data.
    memory_entities / memory_edges:
        Entity / edge counts of the institutional-memory graph (from
        ``orggraph``), or ``None`` when the brain is unavailable.
    notes:
        Human-readable "<signal>: n/a — <reason>" lines for any degraded signal.
    """

    readiness: int | None = None
    top_agent: str | None = None
    top_agent_trust: float | None = None
    best_model: str | None = None
    memory_entities: int | None = None
    memory_edges: int | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of the scorecard."""
        return {
            "readiness": self.readiness,
            "top_agent": self.top_agent,
            "top_agent_trust": self.top_agent_trust,
            "best_model": self.best_model,
            "memory_entities": self.memory_entities,
            "memory_edges": self.memory_edges,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Signal readers (impure boundary — each isolated, each fails independently)
# ---------------------------------------------------------------------------

# A signal reader takes the repo root and returns its typed result. Any of them
# may raise (missing storage, empty ledger, corrupt receipts); build_scorecard
# isolates each behind its own try/except.
ReadinessReader = Callable[[Path], int | None]
TopAgentReader = Callable[[Path], tuple[str, float] | None]
BestModelReader = Callable[[Path], str | None]
MemoryGraphReader = Callable[[Path], tuple[int, int] | None]


def read_readiness(repo_root: Path) -> int | None:
    """Read the 0-100 agent-readiness score via ``roast``.

    Opens storage read-only, mirroring ``roast``/``orggraph`` command context.
    Returns ``None`` only if the score genuinely cannot be produced (the caller
    turns a raised exception into an "n/a" note).
    """
    from oh_no_my_claudecode.config import (
        create_state_dirs,
        database_path,
        load_config,
    )
    from oh_no_my_claudecode.roast.scorer import compute_roast
    from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

    config = load_config(repo_root)
    create_state_dirs(config, repo_root)
    storage = SQLiteStorage(database_path(config, repo_root))
    storage.initialize()
    report = compute_roast(storage, repo_root)
    return int(report.score)


def read_top_agent(repo_root: Path) -> tuple[str, float] | None:
    """Read the top-trust agent ``(subject, trust_score)`` from the reputation ledger.

    Mirrors ``registry``'s ledger layout (``.onmc/registry.json`` holding raw
    attestation dicts) and recomputes reputations via the pure ``build_registry``
    — the ledger file is never trusted to hold derived scores. Returns ``None``
    when the ledger is empty or absent.
    """
    import json

    from oh_no_my_claudecode.registry.registry import build_registry, rank

    ledger_path = repo_root / ".onmc" / "registry.json"
    try:
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    stored = raw.get("attestations")
    if not isinstance(stored, list):
        return None
    attestations = [item for item in stored if isinstance(item, dict)]
    if not attestations:
        return None

    # Secret comes from the environment (ONMC_ATTEST_SECRET) when set; None lets
    # verify_attestation fall back to it. Trust is honest either way — an
    # unverifiable ledger simply reports its top agent at trust 0.0.
    registry = build_registry(attestations, None)
    ranked = rank(registry)
    if not ranked:
        return None
    top = ranked[0]
    return top.subject, float(top.trust_score)


def read_best_model(repo_root: Path) -> str | None:
    """Read the best-verified model from the flywheel receipt corpus.

    Returns ``None`` when there are too few receipts to name a winner (the
    flywheel only sets ``best`` once a model clears its sample threshold).
    """
    from oh_no_my_claudecode.flywheel.analyze import load_trajectories, summarize

    trajectories = load_trajectories(repo_root)
    report = summarize(trajectories)
    if report.best is None:
        return None
    return report.best.model


def read_memory_graph(repo_root: Path) -> tuple[int, int] | None:
    """Read ``(entity_count, edge_count)`` of the institutional-memory graph.

    Opens storage read-only, reads all memories, and builds the org graph.
    Returns ``(0, 0)`` for an empty-but-readable brain; ``None`` is reserved for
    the caller when the reader raises (storage unavailable).
    """
    from oh_no_my_claudecode.config import (
        create_state_dirs,
        database_path,
        load_config,
    )
    from oh_no_my_claudecode.orggraph.graph import build_org_graph
    from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

    config = load_config(repo_root)
    create_state_dirs(config, repo_root)
    storage = SQLiteStorage(database_path(config, repo_root))
    storage.initialize()
    memories = storage.list_memories()
    graph = build_org_graph(memories)
    return len(graph.entities), len(graph.edges)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _reason(exc: BaseException) -> str:
    """Compact, single-line reason string for a failed signal."""
    text = str(exc).strip() or exc.__class__.__name__
    # Keep notes single-line and bounded so the card stays compact and shareable.
    text = " ".join(text.split())
    return text[:120]


def build_scorecard(
    repo_root: Path,
    *,
    readiness_reader: ReadinessReader | None = None,
    top_agent_reader: TopAgentReader | None = None,
    best_model_reader: BestModelReader | None = None,
    memory_graph_reader: MemoryGraphReader | None = None,
) -> Scorecard:
    """Aggregate the four onmc signals for *repo_root* into a :class:`Scorecard`.

    Each signal is read in its own ``try/except``: a raised exception (or a
    ``None`` result) leaves that field ``None`` and appends a
    ``"<signal>: n/a — <reason>"`` note.  The function therefore **never raises**
    on account of a missing or broken subsystem — a fresh/empty repo yields an
    all-``None`` scorecard plus explanatory notes.

    Numbers are only ever taken from the readers; nothing is fabricated.

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root.
    readiness_reader / top_agent_reader / best_model_reader / memory_graph_reader:
        Optional signal callables (defaulting to the real readers).  Injecting
        them lets the aggregation be unit-tested purely and offline.
    """
    readiness_reader = readiness_reader or read_readiness
    top_agent_reader = top_agent_reader or read_top_agent
    best_model_reader = best_model_reader or read_best_model
    memory_graph_reader = memory_graph_reader or read_memory_graph

    card = Scorecard()

    # --- readiness --------------------------------------------------------
    try:
        score = readiness_reader(repo_root)
        if score is None:
            card.notes.append("readiness: n/a — no score available")
        else:
            card.readiness = int(score)
    except Exception as exc:  # noqa: BLE001 - defensive aggregation: one signal can't crash the card
        card.notes.append(f"readiness: n/a — {_reason(exc)}")

    # --- top agent + trust ------------------------------------------------
    try:
        top = top_agent_reader(repo_root)
        if top is None:
            card.notes.append("top_agent: n/a — no attestations in the trust ledger")
        else:
            subject, trust = top
            card.top_agent = subject
            card.top_agent_trust = float(trust)
    except Exception as exc:  # noqa: BLE001
        card.notes.append(f"top_agent: n/a — {_reason(exc)}")

    # --- best model -------------------------------------------------------
    try:
        model = best_model_reader(repo_root)
        if model is None:
            card.notes.append("best_model: n/a — insufficient run receipts")
        else:
            card.best_model = model
    except Exception as exc:  # noqa: BLE001
        card.notes.append(f"best_model: n/a — {_reason(exc)}")

    # --- institutional-memory coverage ------------------------------------
    try:
        graph = memory_graph_reader(repo_root)
        if graph is None:
            card.notes.append("memory: n/a — no institutional-memory graph available")
        else:
            entities, edges = graph
            card.memory_entities = int(entities)
            card.memory_edges = int(edges)
    except Exception as exc:  # noqa: BLE001
        card.notes.append(f"memory: n/a — {_reason(exc)}")

    return card


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

# shields.io static-badge URL: /badge/<label>-<message>-<color> — same pattern as
# oh_no_my_claudecode.badge (kept local so no shared hub is imported).
_SHIELDS_STATIC = "https://img.shields.io/badge/{label}-{message}-{color}"


def _shields_segment(text: str) -> str:
    """Escape a string for a shields.io static-badge URL path segment.

    shields.io treats ``-`` as a field separator and ``_`` as a space, so a
    literal ``-`` is doubled to ``--`` and ``_`` to ``__``, then URL-quoted.
    """
    escaped = text.replace("-", "--").replace("_", "__")
    return quote(escaped, safe="")


def _readiness_color(readiness: int) -> str:
    """Map a 0-100 readiness score to a shields.io badge colour."""
    if readiness >= 90:
        return "brightgreen"
    if readiness >= 75:
        return "green"
    if readiness >= 60:
        return "yellow"
    if readiness >= 40:
        return "orange"
    return "red"


def _readiness_badge(readiness: int | None) -> str:
    """A shields.io Markdown badge line for the readiness score (n/a when None)."""
    if readiness is None:
        message, color = "n/a", "lightgrey"
    else:
        message, color = f"{readiness}/100", _readiness_color(readiness)
    url = _SHIELDS_STATIC.format(
        label=_shields_segment("onmc agent-readiness"),
        message=_shields_segment(message),
        color=color,
    )
    return f"![onmc agent-readiness: {message}]({url})"


def _fmt_int(value: int | None) -> str:
    """Render an int field or ``n/a`` — never a fabricated number."""
    return "n/a" if value is None else str(value)


def _fmt_trust(value: float | None) -> str:
    """Render a trust score to 4dp or ``n/a``."""
    return "n/a" if value is None else f"{value:.4f}"


def render_markdown(sc: Scorecard) -> str:
    """Render *sc* as a compact, shareable Markdown block.

    Deterministic: the same scorecard always yields the same Markdown.  Leads with
    a shields.io readiness badge, then one line per signal (each degrading to
    ``n/a``), and finally the honest notes for any missing signal.
    """
    top_agent = sc.top_agent or "n/a"
    best_model = sc.best_model or "n/a"

    lines = [
        "## onmc scorecard",
        "",
        _readiness_badge(sc.readiness),
        "",
        f"- **Agent-readiness:** {_fmt_int(sc.readiness)}"
        + ("" if sc.readiness is None else "/100"),
        f"- **Top agent:** {top_agent} (trust {_fmt_trust(sc.top_agent_trust)})",
        f"- **Best model:** {best_model}",
        f"- **Institutional memory:** {_fmt_int(sc.memory_entities)} entities, "
        f"{_fmt_int(sc.memory_edges)} edges",
    ]
    if sc.notes:
        lines.append("")
        lines.append("> _Unavailable signals:_")
        for note in sc.notes:
            lines.append(f"> - {note}")
    lines.append("")
    lines.append("_Generated by `onmc scorecard` — deterministic, offline._")
    return "\n".join(lines)


def render_summary(sc: Scorecard, console: Any) -> None:
    """Render *sc* as a Rich panel/table onto *console*.

    *console* is any object with a ``print`` method (the shared Rich ``Console``
    or a stub).  Falls back gracefully if Rich is unavailable, printing a plain
    block instead — an absent dependency must never crash the report.
    """
    try:
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        console.print(_render_summary_plain(sc))
        return

    table = Table.grid(padding=(0, 2))
    table.add_column(justify="right", style="bold")
    table.add_column()

    if sc.readiness is None:
        readiness_cell = Text("n/a", style="dim")
    else:
        readiness_cell = Text(
            f"{sc.readiness}/100", style=f"bold {_rich_readiness_style(sc.readiness)}"
        )
    table.add_row("agent-readiness", readiness_cell)

    top_agent = sc.top_agent or "n/a"
    table.add_row(
        "top agent",
        Text(f"{top_agent}  (trust {_fmt_trust(sc.top_agent_trust)})"),
    )
    table.add_row("best model", Text(sc.best_model or "n/a"))
    table.add_row(
        "institutional memory",
        Text(
            f"{_fmt_int(sc.memory_entities)} entities, "
            f"{_fmt_int(sc.memory_edges)} edges"
        ),
    )

    body: Any = table
    if sc.notes:
        notes = Text()
        notes.append("\nunavailable signals:\n", style="dim")
        for note in sc.notes:
            notes.append(f"  • {note}\n", style="dim")
        from rich.console import Group

        body = Group(table, notes)

    console.print(
        Panel(body, title="onmc scorecard", subtitle="agent-readiness + trust")
    )


def _rich_readiness_style(readiness: int) -> str:
    """Rich style for a readiness score (mirrors the badge colour ladder)."""
    if readiness >= 90:
        return "green"
    if readiness >= 75:
        return "green"
    if readiness >= 60:
        return "yellow"
    if readiness >= 40:
        return "orange3"
    return "red"


def _render_summary_plain(sc: Scorecard) -> str:
    """Plain-text summary block (used when Rich is unavailable)."""
    readiness = f"{sc.readiness}/100" if sc.readiness is not None else "n/a"
    lines = [
        "",
        "  onmc scorecard — agent-readiness + trust",
        f"  agent-readiness:      {readiness}",
        f"  top agent:            {sc.top_agent or 'n/a'} "
        f"(trust {_fmt_trust(sc.top_agent_trust)})",
        f"  best model:           {sc.best_model or 'n/a'}",
        f"  institutional memory: {_fmt_int(sc.memory_entities)} entities, "
        f"{_fmt_int(sc.memory_edges)} edges",
    ]
    if sc.notes:
        lines.append("")
        lines.append("  unavailable signals:")
        for note in sc.notes:
            lines.append(f"   • {note}")
    lines.append("")
    return "\n".join(lines)
