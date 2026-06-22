"""Compile a guided onboarding tour from ONMC memory.

The tour is deterministic and offline — no LLM calls, no network.  It reads
what is already stored (memories, file stats, playbooks) and assembles an
ordered sequence of human-readable stops:

1. **Overview** — repo identity + memory brain at a glance.
2. **Danger zones** — top hotspot files by churn with their governing
   invariants/decisions.
3. **Key decisions & invariants** — the load-bearing architectural choices.
4. **Top playbooks** — step-by-step guides derived from memory (if any).
5. **Start here** — the top files to open first when joining the project.

Each stop is token-bounded so the tour is safe to embed in an agent context
window without blowing the budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.models import FileStat, MemoryEntry, MemoryKind, Playbook
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

# Memory kinds that describe load-bearing architectural choices.
_DECISION_KINDS = {MemoryKind.DECISION, MemoryKind.INVARIANT}

# Memory kinds that describe danger / caution.
_RISK_KINDS = {MemoryKind.HOTSPOT, MemoryKind.FAILED_APPROACH, MemoryKind.GIT_PATTERN}

# Maximum hotspot files to show in the danger-zone stop.
_MAX_HOTSPOTS = 5

# Maximum memories to surface per stop (keeps tokens bounded).
_MAX_MEMORIES_PER_STOP = 8

# Maximum playbooks to show.
_MAX_PLAYBOOKS = 4

# Maximum "start here" files to surface.
_MAX_START_HERE = 8

# Summary length cap for display (characters).
_MAX_SUMMARY_CHARS = 140


def _truncate(text: str, max_chars: int = _MAX_SUMMARY_CHARS) -> str:
    """Truncate *text* at a word boundary and append ellipsis if needed."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(" ", 1)[0]
    return truncated.rstrip(".,;:") + "…"


@dataclass
class TourStop:
    """One stop in the onboarding tour."""

    title: str
    """Short heading, e.g. 'Danger zones'."""

    body: str
    """Markdown-formatted content for this stop."""

    is_empty: bool = False
    """True when this stop has no data (honest empty state)."""


@dataclass
class OnboardingTour:
    """An ordered sequence of tour stops compiled from ONMC memory."""

    repo_root: str
    """Absolute path to the repository root."""

    stops: list[TourStop] = field(default_factory=list)
    """Ordered tour stops (always non-empty — at least the overview stop)."""

    memory_count: int = 0
    file_stat_count: int = 0
    playbook_count: int = 0

    def to_markdown(self) -> str:
        """Render the full tour as a single markdown document."""
        lines: list[str] = [
            f"# ONMC Onboarding Tour — `{Path(self.repo_root).name}`",
            "",
            f"_{self.memory_count} memories · "
            f"{self.file_stat_count} files indexed · "
            f"{self.playbook_count} playbooks_",
            "",
        ]
        for i, stop in enumerate(self.stops, 1):
            lines.append(f"## {i}. {stop.title}")
            lines.append("")
            lines.append(stop.body)
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


def compile_onboarding(
    storage: SQLiteStorage,
    repo_root: Path,
) -> OnboardingTour:
    """Assemble an :class:`OnboardingTour` from *storage* + *repo_root*.

    Fully offline and deterministic.  Always returns a valid tour — even when
    the store is empty, the tour is honest about that fact.
    """
    memories = storage.list_memories()
    file_stats = storage.list_file_stats()
    playbooks = storage.list_playbooks()

    tour = OnboardingTour(
        repo_root=str(repo_root),
        memory_count=len(memories),
        file_stat_count=len(file_stats),
        playbook_count=len(playbooks),
    )

    tour.stops.append(_overview_stop(repo_root, memories, file_stats, playbooks))
    tour.stops.append(_danger_zones_stop(memories, file_stats))
    tour.stops.append(_decisions_stop(memories))
    playbook_stop = _playbooks_stop(playbooks)
    if playbook_stop is not None:
        tour.stops.append(playbook_stop)
    tour.stops.append(_start_here_stop(file_stats, memories))

    return tour


# ---------------------------------------------------------------------------
# Stop builders
# ---------------------------------------------------------------------------


def _overview_stop(
    repo_root: Path,
    memories: list[MemoryEntry],
    file_stats: list[FileStat],
    playbooks: list[Playbook],
) -> TourStop:
    """Stop 1 — Repo overview + brain health at a glance."""
    repo_name = repo_root.name

    by_kind: dict[str, int] = {}
    for mem in memories:
        by_kind[mem.kind.value] = by_kind.get(mem.kind.value, 0) + 1

    if not memories and not file_stats:
        body = (
            f"Repo `{repo_name}` has no ONMC memory yet.\n\n"
            "Run `onmc ingest` to index the codebase, then re-run `onmc onboard`."
        )
        return TourStop(title="Repo overview", body=body, is_empty=True)

    lines: list[str] = [
        f"**Repo:** `{repo_name}`",
        f"**Memories:** {len(memories)}  |  "
        f"**Files indexed:** {len(file_stats)}  |  "
        f"**Playbooks:** {len(playbooks)}",
        "",
    ]

    if by_kind:
        lines.append("**Memory breakdown by kind:**")
        lines.append("")
        for kind_name, count in sorted(by_kind.items(), key=lambda t: -t[1]):
            lines.append(f"- `{kind_name}`: {count}")
        lines.append("")

    if not memories:
        lines.append(
            "_No memories stored yet. Run `onmc ingest` to extract knowledge._"
        )

    return TourStop(title="Repo overview", body="\n".join(lines))


def _danger_zones_stop(
    memories: list[MemoryEntry],
    file_stats: list[FileStat],
) -> TourStop:
    """Stop 2 — Top hotspot files with their governing invariants."""
    # Top hotspots by total churn count.
    hotspots = [fs for fs in file_stats if fs.change_count > 0]
    hotspots = sorted(hotspots, key=lambda s: (-s.change_count, -s.recent_change_count))
    hotspots = hotspots[:_MAX_HOTSPOTS]

    # Risk-kind memories (hotspot, failed_approach, git_pattern).
    risk_memories = [m for m in memories if m.kind in _RISK_KINDS]

    if not hotspots and not risk_memories:
        return TourStop(
            title="Danger zones",
            body="No hotspot data recorded yet. Run `onmc ingest` to analyse git history.",
            is_empty=True,
        )

    lines: list[str] = []

    if hotspots:
        lines.append("**High-churn files (touch with care):**")
        lines.append("")
        for fs in hotspots:
            recent_note = (
                f", {fs.recent_change_count} in last 30 days" if fs.recent_change_count else ""
            )
            lines.append(
                f"- `{fs.path}` — {fs.change_count} commits{recent_note}"
            )
            # Surface any memories that reference this file.
            governing = _memories_for_path(memories, fs.path)
            for mem in governing[:2]:
                lines.append(
                    f"  - [{mem.kind.value}] **{mem.title}**: {_truncate(mem.summary)}"
                )
        lines.append("")

    if risk_memories:
        lines.append("**Recorded risks & dead-ends:**")
        lines.append("")
        for mem in risk_memories[:_MAX_MEMORIES_PER_STOP]:
            lines.append(f"- [{mem.kind.value}] **{mem.title}**: {_truncate(mem.summary)}")
        lines.append("")

    return TourStop(title="Danger zones", body="\n".join(lines).rstrip())


def _decisions_stop(memories: list[MemoryEntry]) -> TourStop:
    """Stop 3 — Load-bearing decisions and invariants."""
    decision_mems = [m for m in memories if m.kind in _DECISION_KINDS]
    decision_mems = sorted(
        decision_mems, key=lambda m: (-m.confidence, m.kind.value, m.title)
    )

    if not decision_mems:
        return TourStop(
            title="Key decisions & invariants",
            body=(
                "No decisions or invariants recorded yet.\n\n"
                "Add them with `onmc memory add` or extract them via `onmc ingest`."
            ),
            is_empty=True,
        )

    lines: list[str] = []
    for mem in decision_mems[:_MAX_MEMORIES_PER_STOP]:
        badge = "INVARIANT" if mem.kind == MemoryKind.INVARIANT else "DECISION"
        lines.append(f"### [{badge}] {mem.title}")
        lines.append("")
        lines.append(_truncate(mem.summary, max_chars=200))
        if mem.details and mem.details != mem.summary:
            lines.append("")
            lines.append(f"_{_truncate(mem.details, max_chars=160)}_")
        lines.append("")

    if len(decision_mems) > _MAX_MEMORIES_PER_STOP:
        remaining = len(decision_mems) - _MAX_MEMORIES_PER_STOP
        lines.append(f"_…and {remaining} more. Run `onmc memory list` to see all._")

    return TourStop(title="Key decisions & invariants", body="\n".join(lines).rstrip())


def _playbooks_stop(playbooks: list[Playbook]) -> TourStop | None:
    """Stop 4 — Top playbooks (omitted if none exist)."""
    if not playbooks:
        return None

    top = sorted(playbooks, key=lambda p: -p.confidence)[:_MAX_PLAYBOOKS]

    lines: list[str] = []
    for pb in top:
        lines.append(f"### {pb.title}")
        lines.append(f"_Confidence: {pb.confidence:.0%} · {len(pb.steps)} steps_")
        lines.append("")
        for step in pb.steps[:4]:
            lines.append(f"- {_truncate(step, max_chars=100)}")
        if len(pb.steps) > 4:
            lines.append(f"  _…{len(pb.steps) - 4} more steps_")
        lines.append("")

    if len(playbooks) > _MAX_PLAYBOOKS:
        remaining = len(playbooks) - _MAX_PLAYBOOKS
        lines.append(f"_…and {remaining} more. Run `onmc playbook list` to see all._")

    return TourStop(title="Top playbooks", body="\n".join(lines).rstrip())


def _start_here_stop(
    file_stats: list[FileStat],
    memories: list[MemoryEntry],
) -> TourStop:
    """Stop 5 — 'Start here' files for a new contributor.

    Strategy: non-test files with the highest churn (most-touched = most
    important) up to _MAX_START_HERE, de-duplicated.
    """
    non_test = [fs for fs in file_stats if not fs.is_test and fs.change_count > 0]
    top_files = sorted(non_test, key=lambda s: -s.change_count)[:_MAX_START_HERE]

    if not top_files:
        return TourStop(
            title="Start here",
            body=(
                "No file stats recorded yet. Run `onmc ingest` to analyse git history,\n"
                "then `onmc onboard` again."
            ),
            is_empty=True,
        )

    lines: list[str] = [
        "Open these files first — they are the most-changed (highest-signal) "
        "non-test files in the repo:",
        "",
    ]
    for fs in top_files:
        governing = _memories_for_path(memories, fs.path)
        if governing:
            note = governing[0].title
            lines.append(f"- `{fs.path}` ({fs.change_count} commits) — {_truncate(note, 80)}")
        else:
            lines.append(f"- `{fs.path}` ({fs.change_count} commits)")

    return TourStop(title="Start here", body="\n".join(lines))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _memories_for_path(memories: list[MemoryEntry], path: str) -> list[MemoryEntry]:
    """Return memories that plausibly reference *path* (substring or basename match)."""
    base = Path(path).name
    result = []
    for mem in memories:
        text = " ".join(
            filter(None, [mem.source_ref, mem.title, mem.summary, mem.details])
        )
        if path in text or base in text:
            result.append(mem)
    return result
