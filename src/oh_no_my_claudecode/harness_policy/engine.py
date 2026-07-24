"""Pure evaluation of a :class:`ChangeSet` against a :class:`HarnessPolicy`.

No I/O, no clock, no randomness — the same policy and change set always yield
the same verdict, so the result can be hashed into a receipt. Every failure is
an explicit, typed :class:`PolicyViolation`; a passing evaluation carries an
empty violation tuple.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from .models import (
    ChangeSet,
    HarnessPolicy,
    PolicyEvaluation,
    PolicyOutcome,
    PolicyViolation,
    ViolationSeverity,
)
from .secrets import scan_secrets

# Destructive shell shapes we refuse regardless of policy file. Matched against
# the normalized argv of every declared command. Kept intentionally small and
# high-signal; the tool broker handles fine-grained capability scoping.
_DESTRUCTIVE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("recursive-force-remove", ("rm",)),
    ("disk-write", ("dd",)),
    ("filesystem-format", ("mkfs",)),
    ("secure-erase", ("shred",)),
    ("power-state-change", ("shutdown",)),
    ("power-state-change", ("reboot",)),
    ("power-state-change", ("halt",)),
)


def _looks_like_traversal(path: str) -> bool:
    """True when a repo-relative path is absolute or escapes the repo root."""
    if not path.strip():
        return True
    pure = PurePosixPath(path)
    if pure.is_absolute():
        return True
    if path.startswith("~"):
        return True
    return any(part == ".." for part in pure.parts)


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    candidate = PurePosixPath(path)
    for pattern in patterns:
        if candidate.match(pattern) or path == pattern:
            return True
        # Directory-prefix globs like ``src/**`` and bare ``src/`` prefixes.
        if pattern.endswith("/**") and (
            path == pattern[:-3] or path.startswith(pattern[:-2])
        ):
            return True
        if pattern.endswith("/") and path.startswith(pattern):
            return True
    return False


def _destructive_reason(argv: tuple[str, ...]) -> str | None:
    if not argv:
        return None
    head = PurePosixPath(argv[0]).name
    rest = argv[1:]
    for code, prefix in _DESTRUCTIVE_RULES:
        if head != prefix[0]:
            continue
        if prefix[0] == "rm":
            flags = "".join(token for token in rest if token.startswith("-"))
            recursive = "r" in flags or "R" in flags
            forced = "f" in flags
            if recursive and forced:
                return code
            continue
        return code
    # Fork bomb / pipe-to-shell heuristics on a joined command string.
    joined = " ".join(argv)
    if ":|:&" in joined.replace(" ", "") or ":(){" in joined.replace(" ", ""):
        return "fork-bomb"
    return None


def evaluate_policy(policy: HarnessPolicy, change: ChangeSet) -> PolicyEvaluation:
    """Return the typed verdict for *change* under *policy*."""
    violations: list[PolicyViolation] = []

    for path in change.changed_files:
        if _looks_like_traversal(path):
            violations.append(
                PolicyViolation(
                    "path-traversal",
                    f"path escapes the repository root: {path!r}",
                )
            )

    for path in change.changed_files:
        if _looks_like_traversal(path):
            continue
        if _matches_any(path, policy.denied_paths):
            violations.append(
                PolicyViolation("denied-path", f"path is denied by policy: {path!r}")
            )
        if policy.allowed_paths and not _matches_any(path, policy.allowed_paths):
            violations.append(
                PolicyViolation("path-not-allowed", f"path is outside allowed_paths: {path!r}")
            )
        if _matches_any(path, policy.protected_files):
            violations.append(
                PolicyViolation("protected-file", f"protected file was modified: {path!r}")
            )

    file_count = len(change.changed_files)
    if policy.max_files_touched is not None and file_count > policy.max_files_touched:
        violations.append(
            PolicyViolation(
                "too-many-files",
                f"{file_count} files touched exceeds "
                f"max_files_touched={policy.max_files_touched}",
            )
        )

    if policy.max_diff_lines is not None and change.total_diff_lines > policy.max_diff_lines:
        violations.append(
            PolicyViolation(
                "diff-too-large",
                f"{change.total_diff_lines} diff lines exceeds "
                f"max_diff_lines={policy.max_diff_lines}",
            )
        )

    missing = tuple(v for v in policy.required_verifiers if v not in change.verifiers_run)
    for verifier in missing:
        violations.append(
            PolicyViolation("missing-verifier", f"required verifier did not run: {verifier!r}")
        )

    for argv in change.commands:
        reason = _destructive_reason(argv)
        if reason is not None:
            violations.append(
                PolicyViolation(
                    "destructive-command",
                    f"{reason}: {' '.join(argv)!r}",
                )
            )

    if policy.secret_scan:
        for finding in scan_secrets(change.diff_text):
            violations.append(
                PolicyViolation(
                    "secret-leak",
                    f"{finding.label} on diff line {finding.line} ({finding.excerpt})",
                )
            )

    approval_needed = policy.human_approval_required
    canonical = tuple(
        dict.fromkeys(violations)  # de-dup identical violations, preserve order
    )

    has_deny = any(v.severity is ViolationSeverity.DENY for v in canonical)
    if has_deny:
        outcome = PolicyOutcome.DENY
    elif approval_needed:
        outcome = PolicyOutcome.REQUIRES_APPROVAL
        canonical = (
            *canonical,
            PolicyViolation(
                "human-approval-required",
                "policy requires explicit human approval before this run can complete",
                ViolationSeverity.APPROVAL,
            ),
        )
    else:
        outcome = PolicyOutcome.ALLOW

    return PolicyEvaluation(
        outcome=outcome,
        violations=canonical,
        policy=policy.to_dict(),
        change=change.to_dict(),
    )


__all__ = ["evaluate_policy"]
