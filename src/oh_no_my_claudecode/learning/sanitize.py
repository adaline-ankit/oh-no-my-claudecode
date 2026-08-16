"""Self-contained content sanitizer for the eval-gated learning machine.

A learned candidate is a piece of text (an episode summary, a repo fact, a
distilled strategy, ...) that will eventually be injected back into an agent's
context. Before anything is allowed past the ``sanitized`` state we scan the
content for two classes of hostile payload:

* **Prompt injection** — phrases and markers that try to override the agent's
  instructions, swap its persona, or smuggle role/chat-template tokens, plus the
  invisible Unicode tricks (zero-width, bidi override, tag characters) used to
  hide such instructions.
* **Secrets** — raw credential material (PEM private keys, AWS key ids, API-key
  assignments) that must never be persisted into a shared learning store.

This module is deliberately pure, deterministic, and dependency-free. It mirrors
the *spirit* of :mod:`oh_no_my_claudecode.memguard.scanner` but stays
self-contained so the learning core has no coupling to the memory subsystem.

The single public entry point is :func:`scan`, which returns an immutable,
rule-id-ordered tuple of :class:`Finding`. A candidate with any finding cannot
advance past the ``sanitized`` state (enforced in :mod:`.gate`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Severity = Literal["critical", "high", "medium", "low"]

_MATCH_LIMIT = 120


@dataclass(frozen=True, slots=True)
class Finding:
    """A single sanitizer finding.

    Immutable so it can be embedded in a frozen :class:`~.models.LearningCandidate`
    and compared for equality across deterministic re-scans.
    """

    rule_id: str
    severity: Severity
    title: str
    detail: str
    match: str

    def to_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "match": self.match,
        }


def _truncate(text: str, limit: int = _MATCH_LIMIT) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


# ---------------------------------------------------------------------------
# Prompt-injection patterns
# ---------------------------------------------------------------------------

# LRN-INJ-001: instruction-override phrases.
_INJ_OVERRIDE = re.compile(
    r"""
    (?:ignore|disregard|forget|override|bypass|discard)   # verb
    \s+
    (?:all\s+|the\s+|your\s+)?
    (?:previous|prior|above|earlier|any\s+previous|any\s+prior|your\s+previous)?
    \s*
    (?:instructions?|directives?|constraints?|guidelines?|rules?|prompts?|context)
    |
    (?:do\s+not\s+follow\s+(?:any\s+)?(?:safety\s+)?(?:guidelines?|instructions?|rules?))
    |
    (?:reveal\s+(?:your\s+)?(?:system\s+prompt|hidden\s+instructions?))
    """,
    re.IGNORECASE | re.VERBOSE,
)

# LRN-INJ-002: persona swap / jailbreak framing.
_INJ_PERSONA = re.compile(
    r"""
    (?:you\s+are\s+now\s+(?:a|an)\s+\w+\s*(?:mode|version|assistant)?)
    |
    (?:act\s+as\s+(?:if\s+you\s+(?:are|were)\s+)?(?:a|an)\s+(?:unrestricted|uncensored|jailbroken))
    |
    (?:enable\s+(?:developer|dan|jailbreak)\s+mode)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# LRN-INJ-003: system-prompt / chat-template marker injection.
_INJ_TEMPLATE = re.compile(
    r"""
    (?:disregard|ignore|override|replace|suppress)\s+
    (?:the\s+)?(?:system\s+prompt|system\s+instructions?|system\s+context)
    |
    (?:new\s+system\s+prompt|system\s+prompt\s*[:=])
    |
    (?:\[INST\]|</s>|<\|im_start\|>|<\|im_end\|>)
    |
    (?:[#]{3}\s*(?:Instruction|System|User|Assistant)\s*:)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# LRN-INJ-004: invisible zero-width characters (steganographic injection).
_INJ_ZERO_WIDTH = re.compile("[​‌‍﻿]")

# LRN-INJ-005: bidi override / isolate controls.
_INJ_BIDI = re.compile("[‪-‮⁦-⁩]")

# LRN-INJ-006: Unicode tag block (U+E0000–U+E007F).
_INJ_TAG = re.compile("[\U000e0000-\U000e007f]")


# ---------------------------------------------------------------------------
# Secret patterns
# ---------------------------------------------------------------------------

# LRN-SEC-001: raw private key / AWS id / credential assignment.
_SEC_RAW = re.compile(
    r"""
    (?:-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+|DSA\s+)?PRIVATE\s+KEY-----)   # PEM
    |
    (?:AKIA[0-9A-Z]{16})                                                      # AWS key id
    |
    (?:
        (?:api[_-]?key|api[_-]?secret|access[_-]?token|secret[_-]?key
           |private[_-]?key|password|passwd|credential|auth[_-]?token)
        \s*[:=]\s*
        ['"]?[A-Za-z0-9+/=_\-]{16,}['"]?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# LRN-SEC-002: common provider token prefixes (GitHub, OpenAI, Slack, Google).
_SEC_TOKEN = re.compile(
    r"""
    (?:gh[pousr]_[A-Za-z0-9]{20,})          # GitHub tokens
    |
    (?:sk-[A-Za-z0-9]{20,})                  # OpenAI-style secret key
    |
    (?:sk-(?:proj|ant|live|test)-[A-Za-z0-9_\-]{6,})  # prefixed sk- keys (short forms too)
    |
    (?:xox[baprs]-[A-Za-z0-9-]{10,})         # Slack tokens
    |
    (?:AIza[0-9A-Za-z_\-]{35})               # Google API key
    """,
    re.VERBOSE,
)

# LRN-INJ-007: fetch-piped-to-shell — a memory/skill that tells an agent to
# download and execute remote code is an instruction-injection vector even
# when every word looks like ordinary ops advice.
_INJ_EXEC_FETCH = re.compile(
    r"""
    (?:curl|wget)[^|\n]{0,120}\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b   # curl ... | sh
    |
    (?:ba|z|da)?sh\s+-c\s+["']?\$\((?:curl|wget)\b                # sh -c "$(curl ...)"
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class _Rule:
    pattern: re.Pattern[str]
    rule_id: str
    severity: Severity
    title: str
    detail: str


_RULES: tuple[_Rule, ...] = (
    _Rule(
        _INJ_OVERRIDE,
        "LRN-INJ-001",
        "high",
        "Instruction-override phrase",
        "Content tries to nullify or override an agent's existing instructions.",
    ),
    _Rule(
        _INJ_PERSONA,
        "LRN-INJ-002",
        "high",
        "Persona-swap / jailbreak framing",
        "Content attempts to reassign the agent's persona into an unrestricted mode.",
    ),
    _Rule(
        _INJ_TEMPLATE,
        "LRN-INJ-003",
        "high",
        "System-prompt / chat-template injection",
        "Content injects system-prompt overrides or role/chat-template markers.",
    ),
    _Rule(
        _INJ_ZERO_WIDTH,
        "LRN-INJ-004",
        "medium",
        "Zero-width Unicode character",
        "Invisible zero-width characters can hide a steganographic injection.",
    ),
    _Rule(
        _INJ_BIDI,
        "LRN-INJ-005",
        "high",
        "Bidi override / isolate character",
        "Bidirectional control characters can disguise the true reading order of text.",
    ),
    _Rule(
        _INJ_TAG,
        "LRN-INJ-006",
        "high",
        "Unicode tag character",
        "Characters from the Unicode tag block are invisible carriers for hidden text.",
    ),
    _Rule(
        _INJ_EXEC_FETCH,
        "LRN-INJ-007",
        "high",
        "Fetch-piped-to-shell execution",
        "Content instructs downloading and executing remote code (curl|wget piped to a shell).",
    ),
    _Rule(
        _SEC_RAW,
        "LRN-SEC-001",
        "critical",
        "Embedded secret / credential",
        "Content embeds a private key, AWS key id, or credential assignment.",
    ),
    _Rule(
        _SEC_TOKEN,
        "LRN-SEC-002",
        "critical",
        "Provider access token",
        "Content embeds a recognizable provider access-token prefix.",
    ),
)


def scan(content: str) -> tuple[Finding, ...]:
    """Scan *content* for prompt-injection and secret payloads.

    Pure and deterministic: the same input always yields the same tuple, ordered
    by ``(rule_id, match position)``. An empty tuple means the content is clean.
    """
    findings: list[Finding] = []
    for rule in _RULES:
        for m in rule.pattern.finditer(content):
            findings.append(
                Finding(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    title=rule.title,
                    detail=rule.detail,
                    match=_truncate(m.group(0)),
                )
            )
    findings.sort(key=lambda f: f.rule_id)
    return tuple(findings)


def is_clean(content: str) -> bool:
    """Return ``True`` when *content* produces no findings."""
    return not scan(content)


__all__ = ["Finding", "Severity", "is_clean", "scan"]
