"""Optional semgrep static-analysis integration for onmc audit.

semgrep is an external binary (not a pip dependency).  This module:

- Exposes :func:`semgrep_available` — a pure ``shutil.which`` check, the sole
  detection point.
- Defines :data:`SemgrepRunner` — the injectable callable type.  The real CLI
  wires :func:`make_semgrep_runner` only when :func:`semgrep_available` returns
  ``True``; tests inject a fake runner so no binary is needed offline.
- Exposes :func:`run_semgrep` — the pure integration layer that invokes a
  runner and converts its JSON output into :class:`AuditFinding` objects.  When
  ``runner`` is ``None`` (binary absent or opt-out) zero findings are returned
  and the surrounding :func:`run_audit` call is completely unchanged.

Design mirrors the difftastic integration in
:mod:`oh_no_my_claudecode.verifydiff.checker` — injectable, offline-testable,
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

_SEMGREP_BINARY = "semgrep"

# semgrep severity → AuditSeverity mapping.  semgrep uses "ERROR", "WARNING",
# "INFO" (and occasionally "INVENTORY", "EXPERIMENT").  We map conservatively.
_SEMGREP_SEVERITY_MAP: dict[str, AuditSeverity] = {
    "ERROR": "high",
    "WARNING": "medium",
    "INFO": "low",
    "INVENTORY": "info",
    "EXPERIMENT": "info",
}

# ---------------------------------------------------------------------------
# Injectable type
# ---------------------------------------------------------------------------

# A SemgrepRunner is any callable that accepts a repo-root Path and returns
# the raw parsed JSON object from ``semgrep --json`` (a dict or None on
# failure).  The real factory (:func:`make_semgrep_runner`) shells the binary;
# tests inject a plain function that returns a hand-crafted dict.
SemgrepRunner = Callable[[Path], "dict[str, Any] | None"]

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def semgrep_available() -> bool:
    """Return ``True`` when the ``semgrep`` binary is discoverable on ``PATH``.

    semgrep is an external tool (not a pip package); this is the sole
    detection point.  When it returns ``False`` the semgrep check is skipped
    and audit falls back to its existing behaviour unchanged — zero regression.
    """
    return shutil.which(_SEMGREP_BINARY) is not None


# ---------------------------------------------------------------------------
# Real runner factory (impure — shells out)
# ---------------------------------------------------------------------------


def make_semgrep_runner(config: str = "auto") -> SemgrepRunner:
    """Build a real :data:`SemgrepRunner` backed by the ``semgrep`` binary.

    This is an *impure* factory: the returned closure shells ``semgrep`` and
    captures its JSON output.  It is only ever wired into :func:`run_semgrep`
    when :func:`semgrep_available` is ``True``; unit tests inject a fake runner
    instead so no real binary is required.

    Parameters
    ----------
    config:
        semgrep config/ruleset to use — e.g. ``"auto"`` (the default, pulls
        the recommended Semgrep registry ruleset) or an explicit registry slug
        like ``"p/python"`` or a local path ``"./semgrep-rules"``.

    Returns
    -------
    SemgrepRunner
        A callable that, given a repo-root ``Path``, runs semgrep and returns
        the parsed JSON response dict (or ``None`` if semgrep fails to run).
    """
    import subprocess

    def _runner(repo_root: Path) -> dict[str, Any] | None:
        try:
            proc = subprocess.run(
                [
                    _SEMGREP_BINARY,
                    "--config",
                    config,
                    "--json",
                    "--quiet",
                    str(repo_root),
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=repo_root,
            )
        except FileNotFoundError:
            # Binary disappeared between the availability check and execution.
            return None

        if proc.returncode not in (0, 1):
            # 0 = clean; 1 = findings found.  Any other code is a semgrep
            # error — we silently skip rather than crashing the audit.
            return None

        try:
            return json.loads(proc.stdout)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            return None

    return _runner


# ---------------------------------------------------------------------------
# Pure integration layer
# ---------------------------------------------------------------------------


def run_semgrep(repo_root: Path, runner: SemgrepRunner | None) -> list[AuditFinding]:
    """Run *runner* against *repo_root* and convert findings to :class:`AuditFinding`.

    This function is pure from the perspective of the surrounding audit: when
    *runner* is ``None`` it returns an empty list and the audit is unchanged.
    When a runner is supplied it is called once, its JSON output is parsed, and
    each semgrep finding is mapped to the shared :class:`AuditFinding` schema.

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root passed to the runner.
    runner:
        An injected :data:`SemgrepRunner` callable, or ``None`` to skip.

    Returns
    -------
    list[AuditFinding]
        Zero or more findings.  An empty list when *runner* is ``None``,
        when semgrep errors, or when semgrep reports no issues.
    """
    if runner is None:
        return []

    raw = runner(repo_root)
    if raw is None:
        return []

    results: object = raw.get("results")
    if not isinstance(results, list):
        return []

    findings: list[AuditFinding] = []
    for item in results:
        if not isinstance(item, dict):
            continue

        check_id: str = str(item.get("check_id", "SEMGREP-UNKNOWN"))
        semgrep_sev: str = str(item.get("extra", {}).get("severity", "WARNING")).upper()
        severity: AuditSeverity = _SEMGREP_SEVERITY_MAP.get(semgrep_sev, "medium")
        message: str = str(item.get("extra", {}).get("message", "Semgrep finding."))

        path_raw: object = item.get("path", "")
        file_rel: str = ""
        if isinstance(path_raw, str) and path_raw:
            try:
                file_rel = Path(path_raw).relative_to(repo_root).as_posix()
            except ValueError:
                file_rel = path_raw

        start_raw: object = item.get("start", {})
        line: int | None = None
        if isinstance(start_raw, dict):
            line_raw = start_raw.get("line")
            if isinstance(line_raw, int):
                line = line_raw

        # The rule ID is the last dotted segment of the check_id (more human-readable).
        short_id = check_id.split(".")[-1] if "." in check_id else check_id

        findings.append(
            AuditFinding(
                rule_id=f"SEMGREP:{short_id}",
                severity=severity,
                title=f"semgrep: {short_id}",
                file=file_rel,
                line=line,
                detail=message,
                fix=(
                    f"Review the semgrep finding `{check_id}`.  "
                    "Consult the semgrep documentation for remediation guidance."
                ),
            )
        )
    return findings
