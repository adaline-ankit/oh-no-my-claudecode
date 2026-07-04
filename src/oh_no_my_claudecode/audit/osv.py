"""Optional osv-scanner dependency-vulnerability integration for onmc audit.

osv-scanner is an external binary (not a pip dependency).  This module:

- Exposes :func:`osv_available` — a pure ``shutil.which`` check, the sole
  detection point.
- Defines :data:`OsvRunner` — the injectable callable type.  The real CLI
  wires :func:`make_osv_runner` only when :func:`osv_available` returns
  ``True``; tests inject a fake runner so no binary is needed offline.
- Exposes :func:`run_osv` — the pure integration layer that invokes a
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

_OSV_BINARY = "osv-scanner"

# osv-scanner severity → AuditSeverity mapping.  The OSV schema uses CVSS-style
# severity strings ("CRITICAL", "HIGH", "MEDIUM", "LOW") in the vuln.database_specific
# or severity[].score fields, but the JSON output groups findings under packages so
# we extract the highest per-package severity.  We map conservatively.
_OSV_SEVERITY_MAP: dict[str, AuditSeverity] = {
    "CRITICAL": "critical",
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
}

# ---------------------------------------------------------------------------
# Injectable type
# ---------------------------------------------------------------------------

# An OsvRunner is any callable that accepts a repo-root Path and returns
# the raw parsed JSON object from ``osv-scanner --format json`` (a dict or
# None on failure).  The real factory (:func:`make_osv_runner`) shells the
# binary; tests inject a plain function that returns a hand-crafted dict.
OsvRunner = Callable[[Path], "dict[str, Any] | None"]

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def osv_available() -> bool:
    """Return ``True`` when the ``osv-scanner`` binary is discoverable on ``PATH``.

    osv-scanner is an external tool (not a pip package); this is the sole
    detection point.  When it returns ``False`` the osv check is skipped
    and audit falls back to its existing behaviour unchanged — zero regression.
    """
    return shutil.which(_OSV_BINARY) is not None


# ---------------------------------------------------------------------------
# Real runner factory (impure — shells out)
# ---------------------------------------------------------------------------


def make_osv_runner(*, lockfile: str | None = None) -> OsvRunner:
    """Build a real :data:`OsvRunner` backed by the ``osv-scanner`` binary.

    This is an *impure* factory: the returned closure shells ``osv-scanner``
    and captures its JSON output.  It is only ever wired into :func:`run_osv`
    when :func:`osv_available` is ``True``; unit tests inject a fake runner
    instead so no real binary is required.

    Parameters
    ----------
    lockfile:
        Optional explicit lockfile path (relative or absolute) to pass via
        ``--lockfile``.  When ``None`` (the default), the runner passes
        ``-r <repo_root>`` so osv-scanner discovers lockfiles automatically
        (uv.lock, requirements.txt, package-lock.json, etc.).

    Returns
    -------
    OsvRunner
        A callable that, given a repo-root ``Path``, runs osv-scanner and
        returns the parsed JSON response dict (or ``None`` if osv-scanner
        fails to run or produces unreadable output).
    """
    import subprocess

    def _runner(repo_root: Path) -> dict[str, Any] | None:
        if lockfile is not None:
            cmd = [
                _OSV_BINARY,
                "--format",
                "json",
                "--lockfile",
                lockfile,
            ]
        else:
            cmd = [
                _OSV_BINARY,
                "--format",
                "json",
                "-r",
                str(repo_root),
            ]

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

        # osv-scanner exit codes:
        #   0 = no vulnerabilities found
        #   1 = vulnerabilities found  (still valid JSON output)
        # Any other code indicates a scan error — silently skip.
        if proc.returncode not in (0, 1):
            return None

        raw_output = proc.stdout.strip()
        if not raw_output:
            return None

        try:
            return json.loads(raw_output)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            return None

    return _runner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_severity(vuln: dict[str, Any]) -> AuditSeverity:
    """Extract the highest severity from an OSV vulnerability dict.

    Tries, in order:
    1. ``database_specific.severity`` (used by many NVD-backed advisories)
    2. First entry in ``severity[]`` with ``type == "CVSS_V3"``
    3. Falls back to ``"high"`` (conservative for dependency CVEs).
    """
    # Path 1: database_specific.severity (string like "HIGH")
    db_specific: object = vuln.get("database_specific", {})
    if isinstance(db_specific, dict):
        sev_raw = db_specific.get("severity", "")
        if isinstance(sev_raw, str):
            mapped = _OSV_SEVERITY_MAP.get(sev_raw.upper())
            if mapped is not None:
                return mapped

    # Path 2: severity[] array with CVSS score string
    severity_list: object = vuln.get("severity", [])
    if isinstance(severity_list, list):
        for entry in severity_list:
            if not isinstance(entry, dict):
                continue
            score_str: object = entry.get("score", "")
            if not isinstance(score_str, str):
                continue
            # CVSS v3 vectors start with "CVSS:3" and encode severity in the
            # base score, but the JSON often contains a pre-computed rating.
            # Try the "type" field first (some feeds use it as a severity rating).
            sev_type: object = entry.get("type", "")
            if isinstance(sev_type, str):
                mapped2 = _OSV_SEVERITY_MAP.get(sev_type.upper())
                if mapped2 is not None:
                    return mapped2

    # Conservative default for dependency CVEs.
    return "high"


# ---------------------------------------------------------------------------
# Pure integration layer
# ---------------------------------------------------------------------------


def run_osv(repo_root: Path, runner: OsvRunner | None) -> list[AuditFinding]:
    """Run *runner* against *repo_root* and convert findings to :class:`AuditFinding`.

    This function is pure from the perspective of the surrounding audit: when
    *runner* is ``None`` it returns an empty list and the audit is unchanged.
    When a runner is supplied it is called once, its JSON output is parsed, and
    each osv-scanner vulnerability is mapped to the shared :class:`AuditFinding`
    schema.

    The osv-scanner JSON output groups vulnerabilities by package:

    .. code-block:: json

        {
          "results": [
            {
              "source": { "path": "uv.lock", "type": "lockfile" },
              "packages": [
                {
                  "package": { "name": "requests", "version": "2.28.0", "ecosystem": "PyPI" },
                  "vulnerabilities": [
                    { "id": "GHSA-...", "aliases": ["CVE-2023-..."], ... }
                  ]
                }
              ]
            }
          ]
        }

    Each vulnerability in each package becomes one :class:`AuditFinding`.

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root passed to the runner.
    runner:
        An injected :data:`OsvRunner` callable, or ``None`` to skip.

    Returns
    -------
    list[AuditFinding]
        Zero or more findings.  An empty list when *runner* is ``None``,
        when osv-scanner errors, or when no vulnerabilities are detected.
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

    for result_entry in results:
        if not isinstance(result_entry, dict):
            continue

        # Extract the lockfile/source path for file attribution.
        source: object = result_entry.get("source", {})
        source_path: str = ""
        if isinstance(source, dict):
            raw_path: object = source.get("path", "")
            if isinstance(raw_path, str) and raw_path:
                try:
                    source_path = Path(raw_path).relative_to(repo_root).as_posix()
                except ValueError:
                    source_path = raw_path

        packages: object = result_entry.get("packages", [])
        if not isinstance(packages, list):
            continue

        for pkg_entry in packages:
            if not isinstance(pkg_entry, dict):
                continue

            pkg_info: object = pkg_entry.get("package", {})
            pkg_name: str = ""
            pkg_version: str = ""
            pkg_ecosystem: str = ""
            if isinstance(pkg_info, dict):
                pkg_name = str(pkg_info.get("name", "unknown"))
                pkg_version = str(pkg_info.get("version", ""))
                pkg_ecosystem = str(pkg_info.get("ecosystem", ""))

            vulnerabilities: object = pkg_entry.get("vulnerabilities", [])
            if not isinstance(vulnerabilities, list):
                continue

            for vuln in vulnerabilities:
                if not isinstance(vuln, dict):
                    continue

                vuln_id: str = str(vuln.get("id", "OSV-UNKNOWN"))
                # Prefer CVE alias if present, fall back to OSV id.
                aliases: object = vuln.get("aliases", [])
                cve_alias: str = vuln_id
                if isinstance(aliases, list):
                    for alias in aliases:
                        if isinstance(alias, str) and alias.startswith("CVE-"):
                            cve_alias = alias
                            break

                severity: AuditSeverity = _extract_severity(vuln)

                summary: str = str(vuln.get("summary", "Dependency vulnerability detected."))
                detail: str = (
                    f"{summary}  "
                    f"Affected package: {pkg_name}=={pkg_version} ({pkg_ecosystem}).  "
                    f"OSV advisory: {vuln_id}."
                )

                findings.append(
                    AuditFinding(
                        rule_id=f"OSV:{cve_alias}",
                        severity=severity,
                        title=f"osv: {pkg_name} — {cve_alias}",
                        file=source_path,
                        line=None,
                        detail=detail,
                        fix=(
                            f"Upgrade {pkg_name} to a version that is not affected by "
                            f"{cve_alias}.  Consult https://osv.dev/{vuln_id} for patched "
                            "versions and remediation guidance."
                        ),
                    )
                )

    return findings
