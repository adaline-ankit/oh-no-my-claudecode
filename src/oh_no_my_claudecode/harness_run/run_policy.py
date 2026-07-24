"""Declarative run-policy: the guardrails a harness run must satisfy.

A :class:`RunPolicy` is loaded from a repo-local policy file (``.onmc/policy.toml``)
and evaluated against the *observed* effect of a run — the files it touched, the
size of its diff, the verifiers that passed, and the raw diff text. Evaluation is
a pure function (:func:`evaluate_run_policy`); all I/O (reading the file, running
``git diff``) happens at the controller boundary.

The policy is deliberately independent of the capability broker in
``tool_broker`` (which authorizes *declared* actions up-front). This module judges
*what actually happened* after execution, which is where path traversal, oversized
diffs, protected-file edits, and leaked secrets are caught.

Secret and prompt-injection detection reuse ``memguard.scan_entry`` — the shipped
memory-integrity scanner — rather than re-implementing pattern matching.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import ClassVar

from oh_no_my_claudecode.memguard.scanner import Finding, scan_entry

_SCHEMA_VERSION = "1"

# memguard rule-id prefixes that indicate leaked credentials / backdoors, as
# opposed to prompt-injection or unicode-steganography findings.
_SECRET_RULE_PREFIXES: tuple[str, ...] = ("MG-EXF", "MG-SSH")
# Prefixes that indicate adversarial instructions embedded in retrieved context.
_INJECTION_RULE_PREFIXES: tuple[str, ...] = ("MG-INJ", "MG-UNI")


class ViolationCode(StrEnum):
    """Canonical, stable reason codes for a policy violation."""

    PATH_TRAVERSAL = "path-traversal"
    PATH_DENIED = "path-denied"
    PATH_NOT_ALLOWED = "path-not-allowed"
    PROTECTED_FILE = "protected-file"
    TOO_MANY_FILES = "too-many-files"
    DIFF_TOO_LARGE = "diff-too-large"
    MISSING_VERIFIER = "missing-required-verifier"
    SECRET_LEAK = "secret-leak"  # noqa: S105 — a reason code, not a credential
    APPROVAL_REQUIRED = "human-approval-required"


@dataclass(frozen=True, slots=True)
class PolicyViolation:
    """One reason a run failed policy, addressed to a specific subject."""

    code: ViolationCode
    message: str
    subject: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code.value, "message": self.message, "subject": self.subject}


@dataclass(frozen=True, slots=True)
class VerifierSignal:
    """Observed outcome of one verifier the run actually executed."""

    name: str
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed}


@dataclass(frozen=True, slots=True)
class RunPolicyDecision:
    """The verdict of evaluating a :class:`RunPolicy` against a run's effect."""

    allowed: bool
    approvals_required: bool
    violations: tuple[PolicyViolation, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "approvals_required": self.approvals_required,
            "violations": [violation.to_dict() for violation in self.violations],
        }

    @property
    def blocking_violations(self) -> tuple[PolicyViolation, ...]:
        """Violations that hard-block completion (everything but approval gating)."""
        return tuple(
            violation
            for violation in self.violations
            if violation.code is not ViolationCode.APPROVAL_REQUIRED
        )


@dataclass(frozen=True, slots=True)
class RunPolicy:
    """Guardrails a run must satisfy before it may be reported as verified.

    Empty ``allowed_paths`` means "no allow-list" (every non-denied path is
    permitted). ``secret_scan`` defaults to ``True`` — secure by default.
    """

    allowed_paths: tuple[str, ...] = ()
    denied_paths: tuple[str, ...] = ()
    max_files_touched: int | None = None
    max_diff_lines: int | None = None
    required_verifiers: tuple[str, ...] = ()
    protected_files: tuple[str, ...] = ()
    secret_scan: bool = True
    human_approval_required: bool = False

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "allowed_paths",
            "denied_paths",
            "max_files_touched",
            "max_diff_lines",
            "required_verifiers",
            "protected_files",
            "secret_scan",
            "human_approval_required",
        }
    )

    def __post_init__(self) -> None:
        for name in ("allowed_paths", "denied_paths", "required_verifiers", "protected_files"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise ValueError(f"{name} must be a tuple of non-empty strings")
        for name in ("max_files_touched", "max_diff_lines"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or None")
        if not isinstance(self.secret_scan, bool):
            raise ValueError("secret_scan must be a boolean")
        if not isinstance(self.human_approval_required, bool):
            raise ValueError("human_approval_required must be a boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed_paths": list(self.allowed_paths),
            "denied_paths": list(self.denied_paths),
            "max_files_touched": self.max_files_touched,
            "max_diff_lines": self.max_diff_lines,
            "required_verifiers": list(self.required_verifiers),
            "protected_files": list(self.protected_files),
            "secret_scan": self.secret_scan,
            "human_approval_required": self.human_approval_required,
        }

    @classmethod
    def permissive(cls) -> RunPolicy:
        """A policy that constrains nothing but still scans for leaked secrets."""
        return cls()

    @classmethod
    def from_mapping(cls, payload: object) -> RunPolicy:
        """Build a policy from a parsed mapping (e.g. decoded TOML/JSON)."""
        if not isinstance(payload, dict):
            raise ValueError("policy payload must be a table/object")
        section = payload.get("policy", payload)
        if not isinstance(section, dict):
            raise ValueError("[policy] section must be a table")
        unknown = sorted(set(section) - cls._FIELDS)
        if unknown:
            raise ValueError(f"unknown policy keys: {', '.join(unknown)}")
        return cls(
            allowed_paths=_str_tuple(section.get("allowed_paths", ()), "allowed_paths"),
            denied_paths=_str_tuple(section.get("denied_paths", ()), "denied_paths"),
            max_files_touched=_opt_int(section.get("max_files_touched"), "max_files_touched"),
            max_diff_lines=_opt_int(section.get("max_diff_lines"), "max_diff_lines"),
            required_verifiers=_str_tuple(
                section.get("required_verifiers", ()), "required_verifiers"
            ),
            protected_files=_str_tuple(section.get("protected_files", ()), "protected_files"),
            secret_scan=_bool(section.get("secret_scan", True), "secret_scan"),
            human_approval_required=_bool(
                section.get("human_approval_required", False), "human_approval_required"
            ),
        )


def secret_findings(text: str) -> tuple[Finding, ...]:
    """Return credential/backdoor findings in *text* (empty when clean)."""
    return tuple(
        finding
        for finding in scan_entry(text)
        if finding.rule_id.startswith(_SECRET_RULE_PREFIXES)
    )


def injection_findings(text: str) -> tuple[Finding, ...]:
    """Return prompt-injection / steganography findings in *text*."""
    return tuple(
        finding
        for finding in scan_entry(text)
        if finding.rule_id.startswith(_INJECTION_RULE_PREFIXES)
    )


def _is_traversal(path: str) -> bool:
    """True when *path* is absolute or escapes the repository root."""
    if not path or path.startswith(("/", "\\")):
        return True
    if ":" in path.split("/", 1)[0]:  # windows drive / scheme-like prefix
        return True
    depth = 0
    for part in PurePosixPath(path.replace("\\", "/")).parts:
        if part == "..":
            depth -= 1
            if depth < 0:
                return True
        elif part != ".":
            depth += 1
    return False


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def evaluate_run_policy(
    policy: RunPolicy,
    *,
    changed_files: tuple[str, ...],
    diff_line_count: int,
    diff_text: str,
    verifier_signals: tuple[VerifierSignal, ...],
) -> RunPolicyDecision:
    """Evaluate *policy* against a run's observed effect. Pure and deterministic.

    A run is ``allowed`` only when there are no blocking violations. Human
    approval, when required, is surfaced as a non-blocking flag *plus* an
    ``APPROVAL_REQUIRED`` violation so the caller can gate ``verified`` on it
    without treating it as an outright failure.
    """
    violations: list[PolicyViolation] = []

    for path in changed_files:
        if _is_traversal(path):
            violations.append(
                PolicyViolation(
                    ViolationCode.PATH_TRAVERSAL,
                    "changed path escapes the repository root",
                    path,
                )
            )
            # A traversing path cannot be meaningfully judged against globs.
            continue
        if _matches_any(path, policy.protected_files):
            violations.append(
                PolicyViolation(
                    ViolationCode.PROTECTED_FILE, "protected file was modified", path
                )
            )
        if _matches_any(path, policy.denied_paths):
            violations.append(
                PolicyViolation(ViolationCode.PATH_DENIED, "path is denied by policy", path)
            )
        elif policy.allowed_paths and not _matches_any(path, policy.allowed_paths):
            violations.append(
                PolicyViolation(
                    ViolationCode.PATH_NOT_ALLOWED,
                    "path is outside the allowed set",
                    path,
                )
            )

    if policy.max_files_touched is not None and len(changed_files) > policy.max_files_touched:
        violations.append(
            PolicyViolation(
                ViolationCode.TOO_MANY_FILES,
                f"{len(changed_files)} files touched exceeds limit {policy.max_files_touched}",
            )
        )

    if policy.max_diff_lines is not None and diff_line_count > policy.max_diff_lines:
        violations.append(
            PolicyViolation(
                ViolationCode.DIFF_TOO_LARGE,
                f"{diff_line_count} diff lines exceeds limit {policy.max_diff_lines}",
            )
        )

    passed = {signal.name for signal in verifier_signals if signal.passed}
    for required in policy.required_verifiers:
        if not any(required in name for name in passed):
            violations.append(
                PolicyViolation(
                    ViolationCode.MISSING_VERIFIER,
                    "required verifier did not pass",
                    required,
                )
            )

    if policy.secret_scan:
        for finding in secret_findings(diff_text):
            violations.append(
                PolicyViolation(
                    ViolationCode.SECRET_LEAK,
                    f"{finding.title} ({finding.rule_id})",
                    finding.match,
                )
            )

    if policy.human_approval_required:
        violations.append(
            PolicyViolation(
                ViolationCode.APPROVAL_REQUIRED,
                "policy requires human approval before this run is verified",
            )
        )

    frozen = tuple(violations)
    blocking = [v for v in frozen if v.code is not ViolationCode.APPROVAL_REQUIRED]
    return RunPolicyDecision(
        allowed=not blocking,
        approvals_required=policy.human_approval_required,
        violations=frozen,
    )


def _str_tuple(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise ValueError(f"{name} must be an array of strings, not a string")
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be an array of strings")
    return tuple(value)


def _opt_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


# Deferred import: keep tomllib optional at module import time for clarity.
def load_run_policy(path: object) -> RunPolicy:
    """Load a :class:`RunPolicy` from a TOML file path.

    Returns a permissive policy when the file does not exist so that runs in
    un-configured repositories behave exactly as before this feature landed.
    """
    import tomllib
    from pathlib import Path

    policy_path = Path(str(path))
    if not policy_path.is_file():
        return RunPolicy.permissive()
    with policy_path.open("rb") as handle:
        payload = tomllib.load(handle)
    return RunPolicy.from_mapping(payload)


__all__ = [
    "PolicyViolation",
    "RunPolicy",
    "RunPolicyDecision",
    "VerifierSignal",
    "ViolationCode",
    "evaluate_run_policy",
    "injection_findings",
    "load_run_policy",
    "secret_findings",
]
