"""Optional gitleaks secret-scanning integration for onmc audit.

gitleaks is an external binary (not a pip dependency).  This module:

- Exposes :func:`gitleaks_available` — a pure ``shutil.which`` check, the sole
  detection point.
- Defines :data:`GitleaksRunner` — the injectable callable type.  The real CLI
  wires :func:`make_gitleaks_runner` only when :func:`gitleaks_available` returns
  ``True``; tests inject a fake runner so no binary is needed offline.
- Exposes :func:`run_gitleaks` — the pure integration layer that invokes a
  runner and converts its JSON output into :class:`AuditFinding` objects.  When
  ``runner`` is ``None`` (binary absent or opt-out) zero findings are returned
  and the surrounding :func:`run_audit` call is completely unchanged.

Design mirrors the semgrep integration in
:mod:`oh_no_my_claudecode.audit.semgrep` — injectable, offline-testable,
zero hard dependency.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.audit.scanner import AuditFinding, AuditSeverity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GITLEAKS_BINARY = "gitleaks"

# gitleaks does not assign per-finding severity in its JSON output — every
# detected secret is equally critical from a security perspective.
_DEFAULT_SEVERITY: AuditSeverity = "critical"

# ---------------------------------------------------------------------------
# Injectable type
# ---------------------------------------------------------------------------

# A GitleaksRunner is any callable that accepts a repo-root Path and returns
# the raw parsed JSON list from ``gitleaks detect --report-format json``
# (a list of finding dicts, or None on failure).  The real factory
# (:func:`make_gitleaks_runner`) shells the binary; tests inject a plain
# function that returns a hand-crafted list.
GitleaksRunner = Callable[[Path], "list[dict[str, Any]] | None"]

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def gitleaks_available() -> bool:
    """Return ``True`` when the ``gitleaks`` binary is discoverable on ``PATH``.

    gitleaks is an external tool (not a pip package); this is the sole
    detection point.  When it returns ``False`` the gitleaks check is skipped
    and audit falls back to its existing behaviour unchanged — zero regression.
    """
    return shutil.which(_GITLEAKS_BINARY) is not None


# ---------------------------------------------------------------------------
# Real runner factory (impure — shells out)
# ---------------------------------------------------------------------------


def make_gitleaks_runner(*, no_git: bool = True) -> GitleaksRunner:
    """Build a real :data:`GitleaksRunner` backed by the ``gitleaks`` binary.

    This is an *impure* factory: the returned closure shells ``gitleaks`` and
    captures its JSON output.  It is only ever wired into :func:`run_gitleaks`
    when :func:`gitleaks_available` is ``True``; unit tests inject a fake runner
    instead so no real binary is required.

    Parameters
    ----------
    no_git:
        When ``True`` (the default), passes ``--no-git`` to gitleaks so it
        scans the directory tree without requiring a git repository.  Set to
        ``False`` if you want gitleaks to respect git history.

    Returns
    -------
    GitleaksRunner
        A callable that, given a repo-root ``Path``, runs gitleaks and returns
        the parsed JSON list of findings (or ``None`` if gitleaks fails to run).
    """
    import subprocess

    def _runner(repo_root: Path) -> list[dict[str, Any]] | None:
        cmd = [
            _GITLEAKS_BINARY,
            "detect",
            "--report-format",
            "json",
            "--report-path",
            "-",
            "--source",
            str(repo_root),
        ]
        if no_git:
            cmd.append("--no-git")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=repo_root,
            )
        except FileNotFoundError:
            # Binary disappeared between the availability check and execution.
            return None

        # gitleaks exit codes:
        #   0 = no secrets found
        #   1 = secrets found
        #   126 = config parsing error / usage error
        # We accept 0 and 1 as valid scan outcomes; anything else is an error.
        if proc.returncode not in (0, 1):
            return None

        raw_output = proc.stdout.strip()
        if not raw_output:
            return []

        try:
            parsed: object = json.loads(raw_output)
        except json.JSONDecodeError:
            return None

        if not isinstance(parsed, list):
            return None

        return parsed

    return _runner


# ---------------------------------------------------------------------------
# Pure integration layer
# ---------------------------------------------------------------------------


def run_gitleaks(repo_root: Path, runner: GitleaksRunner | None) -> list[AuditFinding]:
    """Run *runner* against *repo_root* and convert findings to :class:`AuditFinding`.

    This function is pure from the perspective of the surrounding audit: when
    *runner* is ``None`` it returns an empty list and the audit is unchanged.
    When a runner is supplied it is called once, its JSON output is parsed, and
    each gitleaks finding is mapped to the shared :class:`AuditFinding` schema.

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root passed to the runner.
    runner:
        An injected :data:`GitleaksRunner` callable, or ``None`` to skip.

    Returns
    -------
    list[AuditFinding]
        Zero or more findings.  An empty list when *runner* is ``None``,
        when gitleaks errors, or when gitleaks reports no secrets.
    """
    if runner is None:
        return []

    raw = runner(repo_root)
    if raw is None:
        return []

    if not isinstance(raw, list):
        return []

    findings: list[AuditFinding] = []
    for item in raw:
        if not isinstance(item, dict):
            continue

        # gitleaks JSON fields: RuleID, Description, File, StartLine, Secret, Match
        rule_id_raw: str = str(item.get("RuleID", item.get("ruleID", "UNKNOWN")))
        description: str = str(item.get("Description", item.get("description", "Secret detected.")))
        file_raw: object = item.get("File", item.get("file", ""))
        start_line_raw: object = item.get("StartLine", item.get("startLine"))

        file_rel: str = ""
        if isinstance(file_raw, str) and file_raw:
            try:
                file_rel = Path(file_raw).relative_to(repo_root).as_posix()
            except ValueError:
                file_rel = file_raw

        line: int | None = None
        if isinstance(start_line_raw, int):
            line = start_line_raw

        findings.append(
            AuditFinding(
                rule_id=f"GITLEAKS:{rule_id_raw}",
                severity=_DEFAULT_SEVERITY,
                title=f"gitleaks: {rule_id_raw}",
                file=file_rel,
                line=line,
                detail=description,
                fix=(
                    f"A secret matching the '{rule_id_raw}' gitleaks rule was detected.  "
                    "Remove or rotate the secret immediately, then use environment variables "
                    "or a secrets manager instead of hardcoding credentials."
                ),
            )
        )
    return findings
