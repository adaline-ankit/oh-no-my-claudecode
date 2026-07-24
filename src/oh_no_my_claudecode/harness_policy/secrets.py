"""Deterministic, offline secret detection for diff text.

No entropy heuristics with false-positive tuning knobs — just a fixed set of
high-signal patterns for the credential shapes that must never land in a diff.
Pure and regex-only so the same input always yields the same findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# (code, human label, compiled pattern). Ordered; the first match per code wins
# per line so one leaked key yields one finding, not one-per-substring.
_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("aws-access-key-id", "AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "private-key-block",
        "PEM private key header",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    ),
    (
        "github-token",
        "GitHub token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    ),
    (
        "slack-token",
        "Slack token",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    ),
    (
        "openai-key",
        "OpenAI-style secret key",
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "google-api-key",
        "Google API key",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ),
    (
        "generic-assignment",
        "hard-coded credential assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|passwd|password|token|access[_-]?key)\b"
            r"\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class SecretFinding:
    """One detected credential-shaped substring."""

    code: str
    label: str
    line: int
    excerpt: str

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "label": self.label, "line": self.line, "excerpt": self.excerpt}


def _redact(match: str) -> str:
    """Show only a short prefix so the receipt names the leak without echoing it."""
    prefix = match[:4]
    return f"{prefix}{'*' * min(8, max(1, len(match) - 4))}"


def scan_secrets(text: str) -> tuple[SecretFinding, ...]:
    """Return every credential-shaped finding in *text*, deterministically ordered.

    Only additions matter for a unified diff, so lines are considered when they
    are not diff *removals* (a leading ``-``). Findings are sorted by line then
    by rule code for byte-stable receipts.
    """
    findings: list[SecretFinding] = []
    for index, raw_line in enumerate(text.splitlines(), start=1):
        if raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        line = raw_line[1:] if raw_line.startswith("+") else raw_line
        for code, label, pattern in _RULES:
            match = pattern.search(line)
            if match is not None:
                findings.append(
                    SecretFinding(
                        code=code,
                        label=label,
                        line=index,
                        excerpt=_redact(match.group()),
                    )
                )
    findings.sort(key=lambda item: (item.line, item.code))
    return tuple(findings)


__all__ = ["SecretFinding", "scan_secrets"]
