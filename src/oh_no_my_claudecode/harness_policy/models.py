"""Typed contracts for the file-backed harness execution policy.

The harness policy is the repo-scoped guardrail that decides whether a run's
*actual* changes and commands are allowed, require human approval, or must be
denied. It is deliberately separate from the capability-scoped tool broker
(``tool_broker``): the broker authorizes *declared* capabilities before a run,
while this policy judges the *observed* change set after execution.

All models are frozen, validated, and JSON round-trippable so a decision can be
embedded verbatim in a tamper-evident run receipt.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar


class PolicyOutcome(StrEnum):
    """Terminal verdict for one policy evaluation."""

    ALLOW = "allow"
    REQUIRES_APPROVAL = "requires-approval"
    DENY = "deny"


class ViolationSeverity(StrEnum):
    """Severity of a single policy violation."""

    #: A hard stop — the run must not be reported as verified.
    DENY = "deny"
    #: A gate — the run may proceed only with explicit human approval.
    APPROVAL = "approval"


@dataclass(frozen=True, slots=True)
class PolicyViolation:
    """One typed reason a change set failed policy."""

    code: str
    detail: str
    severity: ViolationSeverity = ViolationSeverity.DENY

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("violation code must not be empty")
        if not self.detail.strip():
            raise ValueError("violation detail must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "detail": self.detail, "severity": self.severity.value}


@dataclass(frozen=True, slots=True)
class ChangeSet:
    """The observed effect of a run, judged against the policy.

    ``diff_text`` is scanned for secrets; ``commands`` are argv tuples of every
    command the run wants to execute (verifiers included) and are matched
    against the destructive-command denylist.
    """

    changed_files: tuple[str, ...] = ()
    added_lines: int = 0
    removed_lines: int = 0
    diff_text: str = ""
    commands: tuple[tuple[str, ...], ...] = ()
    verifiers_run: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.added_lines < 0 or self.removed_lines < 0:
            raise ValueError("line counts must be non-negative")

    @property
    def total_diff_lines(self) -> int:
        return self.added_lines + self.removed_lines

    def to_dict(self) -> dict[str, object]:
        return {
            "changed_files": list(self.changed_files),
            "added_lines": self.added_lines,
            "removed_lines": self.removed_lines,
            "commands": [list(argv) for argv in self.commands],
            "verifiers_run": list(self.verifiers_run),
        }


@dataclass(frozen=True, slots=True)
class HarnessPolicy:
    """Repo-scoped guardrail loaded from ``.onmc/policy.json``.

    An empty ``allowed_paths`` means "no allow-list" (every path permitted
    unless denied). ``max_files_touched`` / ``max_diff_lines`` of ``None`` mean
    "unbounded". ``secret_scan`` defaults on because leaking a credential is the
    most common irreversible harm.
    """

    allowed_paths: tuple[str, ...] = ()
    denied_paths: tuple[str, ...] = ()
    protected_files: tuple[str, ...] = ()
    required_verifiers: tuple[str, ...] = ()
    max_files_touched: int | None = None
    max_diff_lines: int | None = None
    secret_scan: bool = True
    human_approval_required: bool = False
    schema_version: str = "1"

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "allowed_paths",
            "denied_paths",
            "protected_files",
            "required_verifiers",
            "max_files_touched",
            "max_diff_lines",
            "secret_scan",
            "human_approval_required",
            "schema_version",
        }
    )

    def __post_init__(self) -> None:
        if self.schema_version != "1":
            raise ValueError(f"unsupported policy schema version: {self.schema_version}")
        for name in ("allowed_paths", "denied_paths", "protected_files", "required_verifiers"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise ValueError(f"{name} must be a tuple of non-empty strings")
        for name in ("max_files_touched", "max_diff_lines"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"{name} must be an integer or null")
            if isinstance(value, int) and not isinstance(value, bool) and value < 0:
                raise ValueError(f"{name} must be non-negative")
        if not isinstance(self.secret_scan, bool):
            raise ValueError("secret_scan must be a boolean")
        if not isinstance(self.human_approval_required, bool):
            raise ValueError("human_approval_required must be a boolean")

    @classmethod
    def permissive(cls) -> HarnessPolicy:
        """Return the safe default: no path limits, secret scanning enabled."""
        return cls()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "allowed_paths": list(self.allowed_paths),
            "denied_paths": list(self.denied_paths),
            "protected_files": list(self.protected_files),
            "required_verifiers": list(self.required_verifiers),
            "max_files_touched": self.max_files_touched,
            "max_diff_lines": self.max_diff_lines,
            "secret_scan": self.secret_scan,
            "human_approval_required": self.human_approval_required,
        }

    @classmethod
    def from_dict(cls, payload: object) -> HarnessPolicy:
        if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
            raise ValueError("policy payload must be an object")
        unknown = sorted(set(payload) - cls._FIELDS)
        if unknown:
            raise ValueError(f"policy has unknown fields: {', '.join(unknown)}")

        def _str_tuple(key: str) -> tuple[str, ...]:
            raw = payload.get(key, [])
            if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
                raise ValueError(f"{key} must be an array of strings")
            return tuple(raw)

        def _opt_int(key: str) -> int | None:
            raw = payload.get(key)
            if raw is None:
                return None
            if not isinstance(raw, int) or isinstance(raw, bool):
                raise ValueError(f"{key} must be an integer or null")
            return raw

        def _bool(key: str, default: bool) -> bool:
            raw = payload.get(key, default)
            if not isinstance(raw, bool):
                raise ValueError(f"{key} must be a boolean")
            return raw

        return cls(
            allowed_paths=_str_tuple("allowed_paths"),
            denied_paths=_str_tuple("denied_paths"),
            protected_files=_str_tuple("protected_files"),
            required_verifiers=_str_tuple("required_verifiers"),
            max_files_touched=_opt_int("max_files_touched"),
            max_diff_lines=_opt_int("max_diff_lines"),
            secret_scan=_bool("secret_scan", True),
            human_approval_required=_bool("human_approval_required", False),
            schema_version=str(payload.get("schema_version", "1")),
        )


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    """The verdict for one ``(policy, change set)`` pair."""

    outcome: PolicyOutcome
    violations: tuple[PolicyViolation, ...]
    policy: dict[str, object]
    change: dict[str, object]

    @property
    def allowed(self) -> bool:
        """True only when the change set fully satisfies the policy."""
        return self.outcome is PolicyOutcome.ALLOW

    @property
    def deny_reasons(self) -> tuple[str, ...]:
        return tuple(
            v.detail for v in self.violations if v.severity is ViolationSeverity.DENY
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "allowed": self.allowed,
            "violations": [v.to_dict() for v in self.violations],
            "policy": self.policy,
            "change": self.change,
        }


__all__ = [
    "ChangeSet",
    "HarnessPolicy",
    "PolicyEvaluation",
    "PolicyOutcome",
    "PolicyViolation",
    "ViolationSeverity",
]
