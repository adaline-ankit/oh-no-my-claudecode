"""MCP Trust Gateway — runtime classifier for individual tool calls.

Design
------
- Pure, deterministic, offline.  No network, no LLM.
- Reuses secret-detection regexes and injection phrases from
  :mod:`oh_no_my_claudecode.audit.rules` — no pattern duplication.
- Decision logic (in order of priority):

  1. Secret detected in stringified args   → BLOCK (critical)
  2. Server not in allowed_servers         → default_decision
  3. Tool in approval_required list        → APPROVAL_REQUIRED
  4. Tool scope == "network"               → APPROVAL_REQUIRED
  5. Tool scope == "write"                 → APPROVAL_REQUIRED
  6. Injection phrase detected in args     → APPROVAL_REQUIRED
  7. Tool scope == "read"                  → ALLOW
  8. Fallback                              → default_decision

Audit log
---------
``append_audit_log(repo_root, call, decision)`` appends a JSONL record to
``.onmc/mcp-audit.log`` (same pattern as FileSink in notify/sinks.py).
Never raises.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from oh_no_my_claudecode.audit.rules import _INJECTION_PATTERNS, _SECRET_PATTERNS
from oh_no_my_claudecode.mcp_trust.policy import McpPolicy, Scope, Verdict

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    """A single MCP tool call to be classified.

    Attributes
    ----------
    server:
        MCP server name (e.g. ``"filesystem"``).
    tool:
        Tool name within that server (e.g. ``"read_file"``).
    args:
        Keyword arguments passed to the tool.  Stringified for scanning.
    """

    server: str
    tool: str
    args: dict[str, object] = field(default_factory=dict)

    @property
    def scoped_key(self) -> str:
        """Return the ``{server}__{tool}`` policy key."""
        return f"{self.server}__{self.tool}"


Severity = Literal["critical", "high", "medium", "low", "info"]


@dataclass
class Decision:
    """Classification result for a single :class:`ToolCall`.

    Attributes
    ----------
    verdict:
        One of ``"allow"``, ``"block"``, or ``"approval_required"``.
    reasons:
        Human-readable list of reasons for this verdict.
    severity:
        Highest severity level among the matched reasons.
    """

    verdict: Verdict
    reasons: list[str] = field(default_factory=list)
    severity: Severity = "info"


# ---------------------------------------------------------------------------
# Arg scanning helpers — reuse audit patterns, no duplication
# ---------------------------------------------------------------------------

# Compile injection patterns once (already compiled in rules.py, but we need
# the combined set here independently so we can work offline with no import
# of full audit module state).
# We import directly from rules — they are already compiled re.Pattern objects.
_COMPILED_INJECTION: list[re.Pattern[str]] = list(_INJECTION_PATTERNS)

# Build a list of (rule_id, pattern) for secrets from _SECRET_PATTERNS
_COMPILED_SECRETS: list[tuple[str, re.Pattern[str]]] = [
    (rule_id, re.compile(pattern))
    for rule_id, _title, pattern, _fix in _SECRET_PATTERNS
]

# Markers that indicate a value is intentionally fake (test fixtures, examples).
_FAKE_MARKERS = frozenset({"fake", "example", "placeholder", "test", "dummy", "noqa"})


def _args_to_str(args: dict[str, object]) -> str:
    """Flatten args dict to a single string for pattern scanning."""
    try:
        return json.dumps(args, default=str)
    except Exception:  # noqa: BLE001
        return str(args)


def _scan_args_for_secrets(args_str: str) -> list[str]:
    """Return list of reason strings for any secrets found in *args_str*."""
    reasons: list[str] = []
    for rule_id, pattern in _COMPILED_SECRETS:
        for match in pattern.finditer(args_str):
            surrounding = args_str[max(0, match.start() - 30) : match.end() + 30].lower()
            if any(marker in surrounding for marker in _FAKE_MARKERS):
                continue
            snippet = match.group()[:40]
            reasons.append(f"[{rule_id}] secret pattern matched in args: {snippet!r}")
    return reasons


def _scan_args_for_injection(args_str: str) -> list[str]:
    """Return list of reason strings for any injection phrases found in *args_str*."""
    reasons: list[str] = []
    for pattern in _COMPILED_INJECTION:
        for match in pattern.finditer(args_str):
            snippet = match.group()[:80]
            reasons.append(f"[PROMPT-001] injection phrase detected in args: {snippet!r}")
    return reasons


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def classify_call(policy: McpPolicy, call: ToolCall) -> Decision:
    """Classify a single :class:`ToolCall` against *policy*.

    Parameters
    ----------
    policy:
        Loaded :class:`~oh_no_my_claudecode.mcp_trust.policy.McpPolicy`.
    call:
        The tool call to classify.

    Returns
    -------
    Decision
        Verdict + reasons + severity.  Deterministic and offline.
    """
    args_str = _args_to_str(call.args)

    # ── 1. Secret in args → always BLOCK ─────────────────────────────────
    secret_reasons = _scan_args_for_secrets(args_str)
    if secret_reasons:
        return Decision(
            verdict="block",
            reasons=secret_reasons,
            severity="critical",
        )

    # ── 2. Server not in allowed_servers ─────────────────────────────────
    if policy.allowed_servers and call.server not in policy.allowed_servers:
        return Decision(
            verdict=policy.default_decision,
            reasons=[
                f"server '{call.server}' is not in the allowed_servers list"
            ],
            severity="high",
        )

    # ── 3. Tool in approval_required list ────────────────────────────────
    if call.scoped_key in policy.approval_required:
        return Decision(
            verdict="approval_required",
            reasons=[
                f"tool '{call.scoped_key}' is in the approval_required list"
            ],
            severity="high",
        )

    # ── 4 & 5. Tool scope → network or write ─────────────────────────────
    tool_scope: Scope | None = policy.tool_scopes.get(call.scoped_key)
    if tool_scope in ("network", "write"):
        return Decision(
            verdict="approval_required",
            reasons=[
                f"tool '{call.scoped_key}' has scope '{tool_scope}' "
                "which requires approval"
            ],
            severity="medium",
        )

    # ── 6. Injection phrase in args ───────────────────────────────────────
    injection_reasons = _scan_args_for_injection(args_str)
    if injection_reasons:
        return Decision(
            verdict="approval_required",
            reasons=injection_reasons,
            severity="high",
        )

    # ── 7. Explicit read scope → ALLOW ───────────────────────────────────
    if tool_scope == "read":
        return Decision(
            verdict="allow",
            reasons=[f"tool '{call.scoped_key}' has scope 'read'"],
            severity="info",
        )

    # ── 8. Fallback: default_decision ────────────────────────────────────
    return Decision(
        verdict=policy.default_decision,
        reasons=["no matching policy rule — applying default_decision"],
        severity="info",
    )


def classify_calls(policy: McpPolicy, calls: list[ToolCall]) -> list[Decision]:
    """Classify a list of tool calls.  Returns one :class:`Decision` per call."""
    return [classify_call(policy, call) for call in calls]


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

_AUDIT_LOG_NAME = "mcp-audit.log"


def append_audit_log(repo_root: Path, call: ToolCall, decision: Decision) -> None:
    """Append a JSONL record for *call* / *decision* to ``.onmc/mcp-audit.log``.

    Exception-safe — never raises, mirrors the FileSink pattern from
    :mod:`oh_no_my_claudecode.notify.sinks`.
    """
    try:
        log_path = repo_root / ".onmc" / _AUDIT_LOG_NAME
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.time(),
            "server": call.server,
            "tool": call.tool,
            "args_keys": list(call.args.keys()),
            "verdict": decision.verdict,
            "severity": decision.severity,
            "reasons": decision.reasons,
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:  # noqa: BLE001, S110
        pass  # audit log must never raise


# ---------------------------------------------------------------------------
# JSONL call-log parser
# ---------------------------------------------------------------------------


def parse_calls_jsonl(source: str) -> list[ToolCall]:
    """Parse a JSONL stream of tool-call records into :class:`ToolCall` objects.

    Each line must be a JSON object with at least ``server`` and ``tool`` keys.
    An optional ``args`` key (dict) is used for arg scanning.  Malformed lines
    are skipped.

    Parameters
    ----------
    source:
        Raw JSONL string (one JSON object per line).
    """
    calls: list[ToolCall] = []
    for line in source.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        server = obj.get("server", "")
        tool = obj.get("tool", "")
        if not isinstance(server, str) or not isinstance(tool, str):
            continue
        args = obj.get("args", {})
        if not isinstance(args, dict):
            args = {}
        calls.append(ToolCall(server=server, tool=tool, args=args))
    return calls
