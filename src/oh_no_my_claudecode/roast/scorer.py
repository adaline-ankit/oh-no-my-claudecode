"""Deterministic agent-readiness scorer for ``onmc roast``.

The score is a **documented weighted blend** of four signals, each already
computed elsewhere in onmc — this module composes, it does not reimplement.

Scoring model (total = 100 points)
-----------------------------------
====================  ======  ===========================================
Component             Weight  What it measures
====================  ======  ===========================================
Hotspot coverage        45    Fraction of high-churn "hotspot" files that
                              have at least one stored memory.  This is the
                              single biggest driver: uncovered hotspots are
                              exactly where an agent wastes tokens
                              rediscovering context.
Audit grade             25    The agent-config security grade
                              (``run_audit``) mapped A=1.0 … F=0.0.  A repo
                              with a leaky ``.claude`` / ``.mcp`` surface is
                              risky for autonomous agents.
Brain size              20    How much durable memory exists at all, on a
                              saturating curve (``BRAIN_FULL`` memories → full
                              marks).  A repo with an empty brain gives an
                              agent nothing to stand on.
Conventions present     10    Whether ``.onmc/conventions.md`` exists, so
                              spawned agents inherit coding norms.
====================  ======  ===========================================

Each component that loses points emits **one blunt finding** plus an actionable
next step.  The result is fully deterministic: the same repo + brain always
produces the same score, grade, findings, and quips.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.audit.scanner import run_audit
from oh_no_my_claudecode.conventions.detector import conventions_path
from oh_no_my_claudecode.coverage.compiler import compile_coverage
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

# --- Component weights (sum == 100) -----------------------------------------
W_HOTSPOT = 45
W_AUDIT = 25
W_BRAIN = 20
W_CONVENTIONS = 10

# Number of memories at which the "brain size" component saturates to full marks.
BRAIN_FULL = 25

# Audit letter grade → fraction of the audit weight earned.
_AUDIT_GRADE_FACTOR: dict[str, float] = {
    "A": 1.0,
    "B": 0.8,
    "C": 0.6,
    "D": 0.35,
    "F": 0.0,
}

# Final letter grade thresholds (mirrors the audit ladder for familiarity).
_GRADE_THRESHOLDS: list[tuple[int, str]] = [
    (90, "A"),
    (75, "B"),
    (60, "C"),
    (40, "D"),
    (0, "F"),
]


@dataclass(slots=True)
class RoastReport:
    """The full agent-readiness roast for one repo.

    Attributes
    ----------
    score:
        Integer 0-100 agent-readiness score.
    grade:
        Letter grade (A/B/C/D/F) derived from *score*.
    findings:
        Blunt, one-line findings — each names a problem **and** an actionable
        next step.  Empty when the repo is pristine.
    memory_count:
        Total durable memories in the brain.
    uncovered_hotspots:
        Count of high-churn files with zero memory coverage.
    audit_grade:
        Letter grade from the agent-config security audit.
    quips:
        Punchy, shareable one-liners for the report card (the "viral" voice).
    """

    score: int
    grade: str
    findings: list[str] = field(default_factory=list)
    memory_count: int = 0
    uncovered_hotspots: int = 0
    audit_grade: str = "A"
    quips: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of the report."""
        return {
            "score": self.score,
            "grade": self.grade,
            "findings": list(self.findings),
            "memory_count": self.memory_count,
            "uncovered_hotspots": self.uncovered_hotspots,
            "audit_grade": self.audit_grade,
            "quips": list(self.quips),
        }


def _final_grade(score: int) -> str:
    """Map a 0-100 score to an A-F letter grade."""
    for threshold, grade in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def compute_roast(storage: SQLiteStorage, repo_root: Path) -> RoastReport:
    """Compute a deterministic :class:`RoastReport` for *repo_root*.

    Pure composition of existing signals — reads from *storage* and the
    filesystem, writes nothing, makes no LLM call.

    Parameters
    ----------
    storage:
        Initialised :class:`SQLiteStorage` for the repo.
    repo_root:
        Absolute path to the repository root.
    """
    coverage = compile_coverage(storage, repo_root)
    audit = run_audit(repo_root)

    findings: list[str] = []
    quips: list[str] = []

    # --- 1. Hotspot memory coverage (W_HOTSPOT) ------------------------------
    # A hotspot is a high-churn file; coverage.top_gaps holds the uncovered
    # ones.  We score the *fraction* of hotspots that are covered.
    uncovered_hotspots = len(coverage.top_gaps)
    covered_hotspots = max(0, coverage.covered_files)
    # Hotspot universe = covered hotspots we can see + the uncovered gaps.
    # When there are no file stats at all (fresh repo), treat coverage as full
    # so we never divide by zero and never punish a repo we can't measure.
    total_hotspots = uncovered_hotspots + covered_hotspots
    hotspot_fraction = 1.0 if total_hotspots == 0 else covered_hotspots / total_hotspots
    hotspot_points = W_HOTSPOT * hotspot_fraction

    if uncovered_hotspots > 0:
        worst = ", ".join(gap.path for gap in coverage.top_gaps[:5])
        findings.append(
            f"{uncovered_hotspots} high-churn hotspot file(s) have ZERO memory "
            f"({worst}). Claude will burn tokens rediscovering them every session. "
            f"→ Run `onmc coverage --suggest --apply` to stub memories, then flesh them out."
        )

    # --- 2. Audit grade (W_AUDIT) -------------------------------------------
    audit_factor = _AUDIT_GRADE_FACTOR.get(audit.grade, 0.0)
    audit_points = W_AUDIT * audit_factor
    if audit_factor < 1.0:
        crit_high = len(audit.findings_at_or_above("high"))
        findings.append(
            f"Agent-config security grade is {audit.grade} "
            f"({crit_high} high/critical finding(s)). A leaky .claude/.mcp surface "
            f"is a foothold for prompt injection. → Run `onmc audit` and fix the top findings."
        )

    # --- 3. Brain size (W_BRAIN) --------------------------------------------
    memory_count = coverage.memory_count
    brain_fraction = min(1.0, memory_count / BRAIN_FULL) if BRAIN_FULL > 0 else 1.0
    brain_points = W_BRAIN * brain_fraction
    if memory_count == 0:
        findings.append(
            "The repo brain is EMPTY — zero durable memories. An agent starts "
            "from nothing every single time. → Run `onmc ingest` to seed memory from history."
        )
    elif brain_fraction < 1.0:
        findings.append(
            f"Thin brain: only {memory_count} memory/memories "
            f"(a healthy repo carries ~{BRAIN_FULL}+). Agents have little context to lean on. "
            f"→ Keep running `onmc ingest` and record decisions as you make them."
        )

    # --- 4. Conventions present (W_CONVENTIONS) ------------------------------
    has_conventions = conventions_path(repo_root).exists()
    conventions_points = W_CONVENTIONS if has_conventions else 0.0
    if not has_conventions:
        findings.append(
            "No `.onmc/conventions.md` — spawned agents must guess your coding "
            "norms (style, lint, test layout). → Run `onmc conventions` to capture them."
        )

    raw = hotspot_points + audit_points + brain_points + conventions_points
    score = max(0, min(100, round(raw)))
    grade = _final_grade(score)

    # --- Quips: the shareable voice -----------------------------------------
    if score >= 90:
        quips.append(
            f"This repo is {score}/100 agent-ready. Drop the agent in, get out of the way."
        )
    elif score >= 75:
        quips.append(f"{score}/100. Solid. A few hotspots from greatness.")
    elif score >= 60:
        quips.append(f"{score}/100. Claude will get there, but it'll waste tokens doing it.")
    elif score >= 40:
        quips.append(f"{score}/100. Rough. An agent here is flying half-blind.")
    else:
        quips.append(f"{score}/100. Brutal. This repo is a token furnace for any agent.")

    if uncovered_hotspots > 0:
        quips.append(
            f"{uncovered_hotspots} hotspot(s) have zero memory — that's where the tokens go to die."
        )

    return RoastReport(
        score=score,
        grade=grade,
        findings=findings,
        memory_count=memory_count,
        uncovered_hotspots=uncovered_hotspots,
        audit_grade=audit.grade,
        quips=quips,
    )
