"""SARIF 2.1.0 formatter for onmc audit findings.

Converts a list of :class:`~oh_no_my_claudecode.audit.scanner.AuditFinding`
objects into a valid SARIF 2.1.0 JSON document (the OASIS standard consumed by
GitHub code-scanning, VS Code SARIF viewer, Azure DevOps, etc.).

Design goals
------------
- Pure stdlib — no new pip dependencies; builds the dict with plain Python and
  ``json``.
- Deterministic — identical findings produce identical SARIF output (rules and
  results are sorted by ruleId / severity / file / line).
- Valid per the SARIF 2.1.0 schema: top-level ``$schema``, ``version``, and a
  single run with ``tool.driver.name``, deduplicated ``rules``, and ``results``
  where each result carries ``ruleId``, ``level``, ``message.text``, and
  ``locations[].physicalLocation.artifactLocation.uri`` (+ ``region.startLine``
  when the finding has a line number).

Severity → SARIF level mapping
-------------------------------
SARIF defines four result levels: ``error``, ``warning``, ``note``, and
``none``.  We map onmc severities conservatively:

    critical → error
    high     → error
    medium   → warning
    low      → note
    info     → note

The ``error`` level causes GitHub code-scanning to block PRs by default, which
mirrors the intent of critical/high findings.

Usage
-----
The entry point is :func:`findings_to_sarif`.  Call it with a list of
:class:`~oh_no_my_claudecode.audit.scanner.AuditFinding` objects and a
``tool_version`` string; it returns a ``dict`` ready to be serialised with
``json.dumps``.

    >>> from oh_no_my_claudecode.audit.sarif import findings_to_sarif
    >>> sarif_doc = findings_to_sarif(findings, tool_version="0.65.0")
    >>> import json; print(json.dumps(sarif_doc, indent=2))
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oh_no_my_claudecode.audit.scanner import AuditFinding

# SARIF 2.1.0 schema URI (the canonical OASIS location).
_SARIF_SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Documents/CommitteeSpecifications/2.1.0/sarif-schema-2.1.0.json"

# onmc audit severity → SARIF result level.
_SEVERITY_TO_SARIF_LEVEL: dict[str, str] = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "info": "note",
}


def findings_to_sarif(
    findings: list[AuditFinding],
    *,
    tool_version: str,
) -> dict[object, object]:
    """Convert *findings* to a SARIF 2.1.0 document.

    Parameters
    ----------
    findings:
        List of :class:`~oh_no_my_claudecode.audit.scanner.AuditFinding`
        objects produced by :func:`~oh_no_my_claudecode.audit.scanner.run_audit`.
        May be empty — an empty list produces a valid SARIF document with zero
        results.
    tool_version:
        The version string to embed in ``tool.driver.version`` (e.g.
        ``"0.65.0"``).  Typically the package ``__version__``.

    Returns
    -------
    dict
        A fully populated SARIF 2.1.0 document as a Python dict.  Serialise
        with ``json.dumps(result, indent=2)`` to get the canonical JSON form.
    """
    # Deduplicate rule IDs and collect per-rule metadata.
    # We iterate in deterministic (sorted) order so that rule indices are stable
    # across identical finding sets.
    seen_rule_ids: dict[str, dict[object, object]] = {}
    for finding in sorted(findings, key=lambda f: (f.rule_id, f.severity, f.file, f.line or 0)):
        if finding.rule_id not in seen_rule_ids:
            seen_rule_ids[finding.rule_id] = _make_rule(finding)

    # Build the rules list in sorted order.
    rules: list[dict[object, object]] = [
        seen_rule_ids[rid] for rid in sorted(seen_rule_ids)
    ]

    # Build an index from rule_id → its 0-based index in the rules array.
    # SARIF requires ``ruleIndex`` to point into ``tool.driver.rules``.
    rule_index: dict[str, int] = {rid: idx for idx, rid in enumerate(sorted(seen_rule_ids))}

    # Build results — one per finding, in deterministic order.
    results: list[dict[object, object]] = [
        _make_result(finding, rule_index)
        for finding in sorted(
            findings,
            key=lambda f: (f.rule_id, f.severity, f.file, f.line or 0),
        )
    ]

    return {
        "$schema": _SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "onmc",
                        "version": tool_version,
                        "informationUri": "https://github.com/adaline-ankit/oh-no-my-claudecode",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _make_rule(finding: AuditFinding) -> dict[object, object]:
    """Build a SARIF ``reportingDescriptor`` from a representative finding."""
    level = _SEVERITY_TO_SARIF_LEVEL.get(finding.severity, "warning")
    return {
        "id": finding.rule_id,
        "name": _rule_id_to_name(finding.rule_id),
        "shortDescription": {"text": finding.title},
        "fullDescription": {"text": finding.detail},
        "defaultConfiguration": {"level": level},
        "help": {"text": finding.fix, "markdown": finding.fix},
    }


def _make_result(finding: AuditFinding, rule_index: dict[str, int]) -> dict[object, object]:
    """Build a SARIF ``result`` object from an :class:`AuditFinding`."""
    level = _SEVERITY_TO_SARIF_LEVEL.get(finding.severity, "warning")

    physical_location: dict[object, object] = {
        "artifactLocation": {
            "uri": finding.file if finding.file else "",
            "uriBaseId": "%SRCROOT%",
        }
    }
    if finding.line is not None:
        physical_location["region"] = {"startLine": finding.line}

    result: dict[object, object] = {
        "ruleId": finding.rule_id,
        "ruleIndex": rule_index.get(finding.rule_id, 0),
        "level": level,
        "message": {"text": finding.detail},
        "locations": [
            {
                "physicalLocation": physical_location,
            }
        ],
    }
    return result


def _rule_id_to_name(rule_id: str) -> str:
    """Convert a rule_id like ``PERM-001`` or ``SEMGREP:foo`` to a camelCase name.

    SARIF ``name`` is a stable camelCase identifier (not a human sentence).
    Examples:
        PERM-001         → Perm001
        SEMGREP:foo-bar  → SemgrepFooBar
        GITLEAKS:secret  → GitleaksSecret
    """
    # Replace common separators with spaces, title-case each word, join.
    normalized = rule_id.replace(":", " ").replace("-", " ").replace("_", " ")
    return "".join(word.capitalize() for word in normalized.split())
