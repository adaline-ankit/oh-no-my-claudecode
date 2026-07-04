"""Memory-integrity scanner — pure, deterministic, zero dependencies.

Provides:
  ``scan_entry(text) -> list[Finding]``   scan a single text blob
  ``scan_memories(memories) -> Report``   aggregate over MemoryEntry objects

Threat classes covered
----------------------
MG-INJ-001  Prompt-injection phrases
MG-INJ-002  System-prompt override / jailbreak directives
MG-EXF-001  Credential exfiltration (curl/wget/POST with secret-like data)
MG-EXF-002  Embedded raw secrets (key assignments, PEM blocks, AWS key IDs)
MG-EXF-003  Base64 blobs that decode to suspicious binary / key material
MG-SSH-001  SSH authorized_keys write attempts
MG-SSH-002  Reverse-shell one-liners
MG-UNI-001  Zero-width characters (U+200B–U+200D, U+FEFF)
MG-UNI-002  Bidi override / isolate characters (U+202A–U+202E, U+2066–U+2069)
MG-UNI-003  Unicode tag characters (U+E0000–U+E007F)
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from oh_no_my_claudecode.models import MemoryEntry

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

MemguardSeverity = Literal["critical", "high", "medium", "low", "info"]

_SEVERITY_ORDER: list[MemguardSeverity] = ["critical", "high", "medium", "low", "info"]


@dataclass(frozen=True)
class Finding:
    """A single security finding from a memory scan.

    Attributes
    ----------
    rule_id:
        Short identifier for the rule that fired (e.g. ``MG-INJ-001``).
    severity:
        One of ``"critical"``, ``"high"``, ``"medium"``, ``"low"``, ``"info"``.
    title:
        One-line human-readable title for the finding.
    detail:
        A sentence or two expanding on what was found.
    match:
        The offending text snippet (truncated to 120 chars).
    """

    rule_id: str
    severity: MemguardSeverity
    title: str
    detail: str
    match: str


@dataclass
class EntryReport:
    """Findings for a single memory entry.

    Attributes
    ----------
    entry_id:
        The memory entry ID (or an ad-hoc label for raw-text callers).
    entry_title:
        Short human-readable label for display.
    findings:
        All findings for this entry (may be empty — entry is clean).
    passed:
        ``True`` when ``findings`` is empty.
    """

    entry_id: str
    entry_title: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings


@dataclass
class Report:
    """Aggregated result of scanning the entire memory store.

    Attributes
    ----------
    entries:
        Per-entry results (includes clean entries when ``include_clean=True``).
    total_scanned:
        Total number of memory entries scanned.
    total_flagged:
        Number of entries with at least one finding.
    passed:
        ``True`` when ``total_flagged == 0``.
    counts_by_severity:
        Mapping from severity name to total finding count across all entries.
    """

    entries: list[EntryReport] = field(default_factory=list)
    total_scanned: int = 0
    total_flagged: int = 0

    @property
    def passed(self) -> bool:
        return self.total_flagged == 0

    @property
    def counts_by_severity(self) -> dict[str, int]:
        counts: dict[str, int] = dict.fromkeys(_SEVERITY_ORDER, 0)
        for entry in self.entries:
            for f in entry.findings:
                counts[f.severity] = counts.get(f.severity, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Rule helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _find_pattern(
    text: str,
    pattern: re.Pattern[str],
    rule_id: str,
    severity: MemguardSeverity,
    title: str,
    detail: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for m in pattern.finditer(text):
        findings.append(
            Finding(
                rule_id=rule_id,
                severity=severity,
                title=title,
                detail=detail,
                match=_truncate(m.group(0)),
            )
        )
    return findings


# ---------------------------------------------------------------------------
# MG-INJ-001: Prompt-injection phrases
# ---------------------------------------------------------------------------

_INJ_PHRASES = re.compile(
    r"""
    (?:ignore|disregard|forget|override|bypass|discard)   # verb
    \s+
    (?:all\s+|the\s+|your\s+)?                            # optional quantifier
    (?:previous|prior|above|any\s+previous|any\s+prior|your\s+previous)?
    \s*
    (?:instructions?|directives?|constraints?|guidelines?|rules?|prompts?|context)
    |
    (?:you\s+are\s+now\s+(?:a|an)\s+\w+\s*(?:mode|version|assistant)?)  # persona-swap
    |
    (?:act\s+as\s+(?:if\s+you\s+(?:are|were)\s+)?(?:a|an)\s+(?:unrestricted|uncensored|jailbroken))
    |
    (?:do\s+not\s+follow\s+(?:any\s+)?(?:safety\s+)?(?:guidelines?|instructions?|rules?))
    |
    (?:reveal\s+(?:your\s+)?(?:system\s+prompt|hidden\s+instructions?))
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ---------------------------------------------------------------------------
# MG-INJ-002: System-prompt override / tool-hijack directives
# ---------------------------------------------------------------------------

_SYSPROMPT_OVERRIDE = re.compile(
    r"""
    (?:disregard|ignore|override|replace|suppress)\s+
    (?:the\s+)?(?:system\s+prompt|system\s+instructions?|system\s+context)
    |
    (?:new\s+system\s+prompt|system\s+prompt\s*[:=])
    |
    (?:\[INST\]|</s>|<\|im_start\|>|<\|im_end\|>)             # chat-template injections
    |
    (?:[#]{3}\s*(?:Instruction|System|User|Assistant)\s*:)      # role-header injection
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ---------------------------------------------------------------------------
# MG-EXF-001: Credential exfiltration (curl/wget/POST a secret)
# ---------------------------------------------------------------------------

_EXFIL_TRANSFER = re.compile(
    r"""
    (?:curl|wget|http\.post|requests\.post|fetch)\s*
    (?:\([^)]{0,200}\)|\s+[^\n]{0,200})
    """,
    re.IGNORECASE | re.VERBOSE,
)

# We only flag when the same nearby region also contains a token-like value
# (avoids flagging normal usage docs).
_SECRET_LIKE = re.compile(
    r"""
    (?:
        (?:api[_-]?key|secret|token|password|passwd|credential|auth)
        \s*[:=]\s*
        ['"]?\w{8,}['"]?                      # value must be ≥8 chars
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _check_exfil(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for m in _EXFIL_TRANSFER.finditer(text):
        region = text[max(0, m.start() - 200) : m.end() + 200]
        if _SECRET_LIKE.search(region):
            findings.append(
                Finding(
                    rule_id="MG-EXF-001",
                    severity="critical",
                    title="Credential exfiltration attempt",
                    detail=(
                        "A network-transfer command (curl/wget/POST) appears near"
                        " a secret-like assignment — possible exfiltration."
                    ),
                    match=_truncate(m.group(0)),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# MG-EXF-002: Embedded raw secrets
# ---------------------------------------------------------------------------

_RAW_SECRETS = re.compile(
    r"""
    (?:
        -----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE\s+KEY-----   # PEM
    )
    |
    (?:AKIA[0-9A-Z]{16})                                                 # AWS key ID
    |
    (?:
        (?:api[_-]?key|api[_-]?secret|access[_-]?token|private[_-]?key|secret[_-]?key)
        \s*[:=]\s*
        ['"]?[A-Za-z0-9+/=_\-]{20,}['"]?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ---------------------------------------------------------------------------
# MG-EXF-003: Base64 blobs decoding to suspicious content
# ---------------------------------------------------------------------------

# Minimum length for a base64 blob to warrant decoding
_B64_RE = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")

_SUSPICIOUS_DECODED_PATTERNS = re.compile(
    rb"""
    -----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----|   # PEM private key
    AKIA[0-9A-Z]{16}|                              # AWS key ID
    (?:ssh-rsa|ecdsa-sha2|ssh-ed25519)\s+[A-Za-z0-9+/]+ # SSH pubkey (authorized_keys payload)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _check_base64(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for m in _B64_RE.finditer(text):
        blob = m.group(0)
        # Pad to multiple of 4 for decoding
        padding = (4 - len(blob) % 4) % 4
        try:
            decoded = base64.b64decode(blob + "=" * padding)
        except Exception:  # noqa: BLE001, S112
            continue
        if _SUSPICIOUS_DECODED_PATTERNS.search(decoded):
            findings.append(
                Finding(
                    rule_id="MG-EXF-003",
                    severity="critical",
                    title="Base64 blob decodes to key/credential material",
                    detail=(
                        "A base64-encoded blob in the memory entry decodes to"
                        " what appears to be a private key or credential."
                    ),
                    match=_truncate(blob),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# MG-SSH-001: Authorized_keys write attempts
# ---------------------------------------------------------------------------

_SSH_AUTHKEYS = re.compile(
    r"""
    # Catch any reference to .ssh/authorized_keys combined with a shell redirect/pipe
    (?:
        (?:>>|>|[|])\s*
        [~$]?/?
        (?:root|home/[^/\s]+|\.)?
        /?\.?ssh/authorized_keys            # >> ~/.ssh/authorized_keys or >> .ssh/authorized_keys
    )
    |
    (?:\.ssh/authorized_keys\s*[<>|])       # authorized_keys on left side of redirect
    |
    (?:echo\s+.{1,200}\.ssh/authorized_keys)  # echo ... authorized_keys (any path)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ---------------------------------------------------------------------------
# MG-SSH-002: Reverse-shell one-liners
# ---------------------------------------------------------------------------

_REVERSE_SHELL = re.compile(
    r"""
    (?:
        bash\s+-i\s+>&\s+/dev/tcp/
        |
        /bin/bash\s+-i\s+>&?\s+/dev/tcp/
        |
        nc\s+(?:-e\s+/bin/(?:bash|sh)|.*-e\s+/bin/(?:bash|sh))
        |
        python\s+-c\s+['"]import\s+socket.*subprocess
        |
        perl\s+-e\s+['"].*socket.*STDOUT
        |
        ruby\s+-rsocket\s+-e.*spawn\s*/bin/sh
        |
        0<&\d+;\s*exec\s+\d+<>/dev/tcp/
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ---------------------------------------------------------------------------
# MG-UNI-001: Zero-width characters
# ---------------------------------------------------------------------------

# U+200B ZERO WIDTH SPACE, U+200C ZERO WIDTH NON-JOINER, U+200D ZERO WIDTH JOINER,
# U+FEFF ZERO WIDTH NO-BREAK SPACE (BOM when mid-text)
_ZW_RE = re.compile(r"[​‌‍﻿]")

# ---------------------------------------------------------------------------
# MG-UNI-002: Bidi override / isolate characters
# ---------------------------------------------------------------------------

# U+202A–U+202E (LRE, RLE, PDF, LRO, RLO), U+2066–U+2069 (LRI, RLI, FSI, PDI)
_BIDI_RE = re.compile(r"[‪-‮⁦-⁩]")

# ---------------------------------------------------------------------------
# MG-UNI-003: Unicode tag characters
# ---------------------------------------------------------------------------

# U+E0000–U+E007F (language tag block — invisible, used for steganographic injection)
_TAG_CHARS_RE = re.compile(r"[\U000e0000-\U000e007f]")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_entry(text: str) -> list[Finding]:
    """Scan *text* for adversarial content and return a list of :class:`Finding` objects.

    Returns an empty list when the text is clean.  Deterministic and offline.

    Parameters
    ----------
    text:
        The raw string to inspect (e.g. the concatenation of a memory entry's
        title, summary, and details fields).

    Returns
    -------
    list[Finding]
        All findings, in rule-id order.  Empty → clean.
    """
    findings: list[Finding] = []

    # MG-INJ-001
    findings.extend(
        _find_pattern(
            text,
            _INJ_PHRASES,
            rule_id="MG-INJ-001",
            severity="high",
            title="Prompt-injection phrase detected",
            detail=(
                "The text contains a phrase typically used to override"
                " or nullify an agent's instructions."
            ),
        )
    )

    # MG-INJ-002
    findings.extend(
        _find_pattern(
            text,
            _SYSPROMPT_OVERRIDE,
            rule_id="MG-INJ-002",
            severity="high",
            title="System-prompt override / tool-hijack directive",
            detail=(
                "The text attempts to replace or suppress the system prompt"
                " or inject role/chat-template markers."
            ),
        )
    )

    # MG-EXF-001
    findings.extend(_check_exfil(text))

    # MG-EXF-002
    findings.extend(
        _find_pattern(
            text,
            _RAW_SECRETS,
            rule_id="MG-EXF-002",
            severity="critical",
            title="Raw secret / credential embedded in memory",
            detail=(
                "A private key PEM block, AWS key ID, or API-key assignment"
                " was found in the memory entry."
            ),
        )
    )

    # MG-EXF-003
    findings.extend(_check_base64(text))

    # MG-SSH-001
    findings.extend(
        _find_pattern(
            text,
            _SSH_AUTHKEYS,
            rule_id="MG-SSH-001",
            severity="critical",
            title="SSH authorized_keys write attempt",
            detail="The text contains a shell snippet that would append a key to authorized_keys.",
        )
    )

    # MG-SSH-002
    findings.extend(
        _find_pattern(
            text,
            _REVERSE_SHELL,
            rule_id="MG-SSH-002",
            severity="critical",
            title="Reverse-shell one-liner detected",
            detail=(
                "The text contains a known reverse-shell payload pattern"
                " (netcat, bash /dev/tcp, etc.)."
            ),
        )
    )

    # MG-UNI-001
    findings.extend(
        _find_pattern(
            text,
            _ZW_RE,
            rule_id="MG-UNI-001",
            severity="medium",
            title="Zero-width Unicode character",
            detail=(
                "The text contains invisible zero-width characters"
                " (U+200B/C/D or U+FEFF mid-text) that can be used"
                " for steganographic prompt injection."
            ),
        )
    )

    # MG-UNI-002
    findings.extend(
        _find_pattern(
            text,
            _BIDI_RE,
            rule_id="MG-UNI-002",
            severity="high",
            title="Bidi override / isolate character",
            detail=(
                "The text contains Unicode bidirectional control characters"
                " (U+202A–U+202E, U+2066–U+2069) that can reverse displayed"
                " text direction to disguise instructions."
            ),
        )
    )

    # MG-UNI-003
    findings.extend(
        _find_pattern(
            text,
            _TAG_CHARS_RE,
            rule_id="MG-UNI-003",
            severity="high",
            title="Unicode tag characters (steganographic injection)",
            detail=(
                "The text contains characters from the Unicode tag block"
                " (U+E0000–U+E007F) — invisible glyphs used to hide"
                " injected instructions."
            ),
        )
    )

    return findings


def scan_memories(memories: list[MemoryEntry], *, include_clean: bool = False) -> Report:
    """Scan all *memories* and return an aggregated :class:`Report`.

    Parameters
    ----------
    memories:
        List of :class:`~oh_no_my_claudecode.models.MemoryEntry` objects to scan.
    include_clean:
        When ``True``, clean (no-finding) entries are included in the report's
        ``entries`` list.  Defaults to ``False`` (only flagged entries listed).

    Returns
    -------
    Report
        Aggregated report with per-entry results and summary statistics.
    """
    total_scanned = len(memories)
    total_flagged = 0
    entry_reports: list[EntryReport] = []

    for mem in memories:
        # Concatenate all text fields the scanner should inspect.
        combined = "\n".join(
            [
                mem.title,
                mem.summary,
                mem.details,
                mem.source_ref,
                *mem.tags,
            ]
        )
        findings = scan_entry(combined)
        er = EntryReport(entry_id=mem.id, entry_title=mem.title, findings=findings)
        if findings:
            total_flagged += 1
            entry_reports.append(er)
        elif include_clean:
            entry_reports.append(er)

    return Report(
        entries=entry_reports,
        total_scanned=total_scanned,
        total_flagged=total_flagged,
    )
