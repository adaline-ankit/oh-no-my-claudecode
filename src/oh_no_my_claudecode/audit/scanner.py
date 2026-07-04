"""Core scanner: run all audit rules and produce a scored AuditReport.

Design goals
------------
- Pure function ``run_audit(repo_root) -> AuditReport``.
- Deterministic, no network, no LLM calls.
- Score starts at 100 and deductions are applied per finding by severity.
- Grade is mapped from final score (A≥90, B≥75, C≥60, D≥40, F<40).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from oh_no_my_claudecode.audit.gitleaks import GitleaksRunner
    from oh_no_my_claudecode.audit.semgrep import SemgrepRunner

AuditSeverity = Literal["critical", "high", "medium", "low", "info"]

# Deductions per severity — these drive the score/grade.
_SEVERITY_DEDUCTIONS: dict[AuditSeverity, int] = {
    "critical": 25,
    "high": 15,
    "medium": 7,
    "low": 3,
    "info": 0,
}

_GRADE_THRESHOLDS: list[tuple[int, str]] = [
    (90, "A"),
    (75, "B"),
    (60, "C"),
    (40, "D"),
    (0, "F"),
]


@dataclass
class AuditFinding:
    """A single security finding from a scan rule.

    Attributes
    ----------
    rule_id:
        Short identifier for the rule that fired (e.g. ``PERM-001``).
    severity:
        One of ``"critical"``, ``"high"``, ``"medium"``, ``"low"``, ``"info"``.
    title:
        One-line human-readable title for the finding.
    file:
        Repo-relative path to the file that triggered this finding.
    line:
        Optional 1-based line number within *file*.
    detail:
        A sentence or two expanding on what was found.
    fix:
        Concrete remediation instruction the developer can act on immediately.
    """

    rule_id: str
    severity: AuditSeverity
    title: str
    file: str
    line: int | None
    detail: str
    fix: str


@dataclass
class AuditReport:
    """Aggregated result of a full audit run.

    Attributes
    ----------
    findings:
        All findings produced by all rules.
    score:
        Integer 0–100.  Starts at 100; each finding deducts according to its
        severity weight.  Cannot go below 0.
    grade:
        Letter grade derived from *score* (A/B/C/D/F).
    counts_by_severity:
        Mapping from severity name to finding count.
    files_scanned:
        Set of repo-relative file paths that were inspected.
    """

    findings: list[AuditFinding] = field(default_factory=list)
    score: int = 100
    grade: str = "A"
    counts_by_severity: dict[str, int] = field(default_factory=dict)
    files_scanned: set[str] = field(default_factory=set)

    def findings_at_or_above(self, threshold: AuditSeverity) -> list[AuditFinding]:
        """Return findings whose severity is >= *threshold* in the risk ladder."""
        order: list[AuditSeverity] = ["critical", "high", "medium", "low", "info"]
        idx = order.index(threshold)
        return [f for f in self.findings if order.index(f.severity) <= idx]


def _compute_score(findings: list[AuditFinding]) -> int:
    """Compute a 0–100 score by deducting for each finding."""
    total = 100
    for finding in findings:
        total -= _SEVERITY_DEDUCTIONS.get(finding.severity, 0)
    return max(0, total)


def _compute_grade(score: int) -> str:
    """Map an integer score to an A–F letter grade."""
    for threshold, grade in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def run_audit(
    repo_root: Path,
    *,
    semgrep_runner: SemgrepRunner | None = None,
    gitleaks_runner: GitleaksRunner | None = None,
) -> AuditReport:
    """Scan *repo_root* for agent-configuration security risks.

    This is a pure, deterministic function.  It imports and runs every rule
    defined in :mod:`oh_no_my_claudecode.audit.rules`.  When *semgrep_runner*
    is supplied (and the ``semgrep`` binary is on ``PATH``), its findings are
    folded into the report.  When *gitleaks_runner* is supplied (and the
    ``gitleaks`` binary is on ``PATH``), detected secrets are folded in.
    When either runner is ``None`` (the default), audit behaviour is completely
    unchanged — zero regression.

    Parameters
    ----------
    repo_root:
        Absolute path to the root of the repository to scan.
    semgrep_runner:
        Optional injectable :data:`~oh_no_my_claudecode.audit.semgrep.SemgrepRunner`
        callable.  When ``None``, semgrep is not invoked.  The real CLI wires
        :func:`~oh_no_my_claudecode.audit.semgrep.make_semgrep_runner` here
        only when :func:`~oh_no_my_claudecode.audit.semgrep.semgrep_available`
        returns ``True`` and the user opts in via ``--semgrep``.  Tests inject
        a fake runner to stay offline.
    gitleaks_runner:
        Optional injectable :data:`~oh_no_my_claudecode.audit.gitleaks.GitleaksRunner`
        callable.  When ``None``, gitleaks is not invoked.  The real CLI wires
        :func:`~oh_no_my_claudecode.audit.gitleaks.make_gitleaks_runner` here
        only when :func:`~oh_no_my_claudecode.audit.gitleaks.gitleaks_available`
        returns ``True`` and the user opts in via ``--gitleaks``.  Tests inject
        a fake runner to stay offline.

    Returns
    -------
    AuditReport
        Scored, graded, fully populated report.  Suitable for both human
        rendering and JSON serialisation.
    """
    from oh_no_my_claudecode.audit.gitleaks import run_gitleaks
    from oh_no_my_claudecode.audit.rules import ALL_RULES
    from oh_no_my_claudecode.audit.semgrep import run_semgrep

    all_findings: list[AuditFinding] = []
    files_scanned: set[str] = set()

    for rule_fn in ALL_RULES:
        rule_findings = rule_fn(repo_root)
        all_findings.extend(rule_findings)

    # Optional semgrep pass — folded in when caller opts in and runner is wired.
    semgrep_findings = run_semgrep(repo_root, semgrep_runner)
    all_findings.extend(semgrep_findings)

    # Optional gitleaks pass — folded in when caller opts in and runner is wired.
    gitleaks_findings = run_gitleaks(repo_root, gitleaks_runner)
    all_findings.extend(gitleaks_findings)

    # Collect scanned files from the findings themselves (each rule reports
    # findings per file; the scanner aggregates them here).
    for finding in all_findings:
        if finding.file:
            files_scanned.add(finding.file)

    # Also record files we attempted to scan (known config file paths).
    candidate_files = [
        "CLAUDE.md",
        "AGENTS.md",
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".mcp.json",
        "hooks/hooks.json",
    ]
    for rel in candidate_files:
        if (repo_root / rel).exists():
            files_scanned.add(rel)

    counts: dict[str, int] = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "info": 0,
    }
    for finding in all_findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1

    score = _compute_score(all_findings)
    grade = _compute_grade(score)

    return AuditReport(
        findings=all_findings,
        score=score,
        grade=grade,
        counts_by_severity=counts,
        files_scanned=files_scanned,
    )
