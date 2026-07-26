"""Real headless agent adapters for the onmc loop engine.

Three adapters are provided:

- ``ClaudeCliAdapter`` — shells out to ``claude -p <prompt> --output-format json``
  and parses the structured JSON response to extract text, tokens, and cost.
- ``CodexCliAdapter`` — shells out to
  ``codex exec --sandbox workspace-write [--model <model>] <prompt>`` (headless mode) and returns
  the raw stdout as output.  Codex emits no machine-readable usage in headless
  mode, so tokens are recovered *best-effort* from the human-readable
  ``tokens used: N`` line and are ``None`` whenever that line is absent or
  malformed.  Cost is never available and is always ``None``.
- ``OpenCodeCliAdapter`` — shells out to
  ``opencode run --format json [--model <provider/model>] <prompt>``
  and parses the JSON event stream defensively for text and token usage.

All adapters compute ``files_touched`` by diffing ``git status --porcelain``
snapshots taken *before* and *after* the agent call, so the list is always
derived from the real working tree rather than fabricated.

All adapters accept an injectable ``CommandRunner`` so that tests can supply
canned subprocess results without ever spawning a real agent process.

Usage::

    from oh_no_my_claudecode.loop.adapters import make_agent_runner

    runner = make_agent_runner("claude", repo_root=Path("/my/repo"))
    result = runner("Fix the broken import", escalation_level=0)

    runner_oc = make_agent_runner("opencode", repo_root=Path("/my/repo"),
                                  model="anthropic/claude-opus-4-5")
    result_oc = runner_oc("Fix the broken import", escalation_level=0)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from oh_no_my_claudecode.loop.models import AgentRunResult
from oh_no_my_claudecode.trace.models import TraceEvent, TraceEventKind
from oh_no_my_claudecode.trace.recorder import record_trace_event

# ---------------------------------------------------------------------------
# Injectable subprocess boundary
# ---------------------------------------------------------------------------


@dataclass
class CompletedProc:
    """Minimal completed-process representation used by CommandRunner.

    Mirrors the fields of ``subprocess.CompletedProcess`` that the adapters
    actually consume, so tests can inject a lightweight fake without depending
    on ``subprocess`` internals.
    """

    returncode: int
    stdout: str
    stderr: str


#: Callable signature for the injectable subprocess boundary.
#: Arguments: ``(cmd, cwd, timeout) -> CompletedProc``
CommandRunner = Callable[[list[str], str, int], CompletedProc]


def _default_command_runner(cmd: list[str], cwd: str, timeout: int) -> CompletedProc:
    """Default CommandRunner — spawns a real subprocess.

    Tests MUST inject a fake CommandRunner instead of calling this function.
    """
    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CompletedProc(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    except subprocess.TimeoutExpired:
        return CompletedProc(
            returncode=1,
            stdout="",
            stderr=f"[agent timed out after {timeout}s]",
        )
    except FileNotFoundError as exc:
        return CompletedProc(
            returncode=127,
            stdout="",
            stderr=f"[binary not found: {exc}]",
        )
    except Exception as exc:  # noqa: BLE001
        return CompletedProc(
            returncode=1,
            stdout="",
            stderr=f"[subprocess error: {exc}]",
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

#: Hint appended to the prompt when escalation_level > 0.
_ESCALATION_HINT = (
    "\n\n---\nPrevious attempts failed; try a materially different approach."
)

#: Model to upgrade to on escalation for Claude (kept simple and documented).
_ESCALATION_MODEL_UPGRADE: dict[str, str] = {
    "claude-sonnet-4-5": "claude-opus-4-5",
    "claude-3-5-sonnet-20241022": "claude-3-opus-20240229",
    "claude-3-7-sonnet-20250219": "claude-3-opus-20240229",
}


def _maybe_escalate_prompt(prompt: str, escalation_level: int) -> str:
    """Append escalation hint to the prompt when level > 0."""
    if escalation_level > 0:
        return prompt + _ESCALATION_HINT
    return prompt


def _git_status_paths(cmd_runner: CommandRunner, repo_root: str, timeout: int) -> set[str]:
    """Return the set of modified/untracked paths from ``git status --porcelain``."""
    proc = cmd_runner(
        ["git", "-C", repo_root, "status", "--porcelain"],
        repo_root,
        timeout,
    )
    paths: set[str] = set()
    for line in proc.stdout.splitlines():
        # Format: XY path  (first 2 chars = status codes, then space, then path)
        if len(line) > 3:
            paths.add(line[3:].strip())
    return paths


def _compute_files_touched(
    before: set[str],
    after: set[str],
) -> list[str]:
    """Return sorted list of paths that appeared or changed after the agent ran."""
    return sorted(after - before)


def _parse_claude_json(raw: str) -> tuple[str, int | None, float | None]:
    """Parse Claude CLI JSON output into (text, tokens, cost_usd).

    Claude CLI ``--output-format json`` can vary between versions.  We try
    several known key layouts and fall back gracefully to raw stdout when the
    JSON is missing or unparseable.

    Known layouts (non-exhaustive):
    - ``{"result": "...", "usage": {"input_tokens": N, "output_tokens": M}}``
    - ``{"content": [{"type": "text", "text": "..."}], "usage": {...}}``
    - ``{"message": {"content": [...]}, "total_cost_usd": ..., "usage": {...}}``
    """
    if not raw.strip():
        return "", None, None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Not JSON — treat entire stdout as plain text output.
        return raw.strip(), None, None

    if not isinstance(data, dict):
        return raw.strip(), None, None

    # --- Extract text ---
    text: str = ""

    # Layout 1: top-level "result" key
    if isinstance(data.get("result"), str):
        text = data["result"]

    # Layout 2: top-level "content" list
    elif isinstance(data.get("content"), list):
        parts = [
            block.get("text", "")
            for block in data["content"]
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "\n".join(parts)

    # Layout 3: nested under "message"
    elif isinstance(data.get("message"), dict):
        msg = data["message"]
        if isinstance(msg.get("content"), list):
            parts = [
                block.get("text", "")
                for block in msg["content"]
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            text = "\n".join(parts)
        elif isinstance(msg.get("content"), str):
            text = msg["content"]

    if not text:
        # Last resort: dump the raw string.
        text = raw.strip()

    # --- Extract tokens ---
    tokens: int | None = None

    usage = data.get("usage")
    if isinstance(usage, dict):
        input_t = usage.get("input_tokens", 0) or 0
        output_t = usage.get("output_tokens", 0) or 0
        total = input_t + output_t
        if total > 0:
            tokens = total

    # Some versions emit a top-level "total_tokens" key.
    if tokens is None and isinstance(data.get("total_tokens"), int):
        tokens = data["total_tokens"]

    # --- Extract cost ---
    cost_usd: float | None = None
    raw_cost = data.get("total_cost_usd")
    if isinstance(raw_cost, (int, float)) and raw_cost >= 0:
        cost_usd = float(raw_cost)

    return text, tokens, cost_usd


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, int | float | str | bytes | bytearray):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _parse_claude_usage(raw: str) -> dict[str, int]:
    """Return only token fields measured in Claude's structured response."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("usage"), dict):
        return {}
    usage = data["usage"]
    aliases = {
        "input_tokens": ("input_tokens", "input"),
        "output_tokens": ("output_tokens", "output"),
        "cache_read_input_tokens": ("cache_read_input_tokens", "cache_read_tokens"),
        "cache_creation_input_tokens": (
            "cache_creation_input_tokens",
            "cache_creation_tokens",
        ),
        "reasoning_output_tokens": ("reasoning_output_tokens", "reasoning_tokens"),
    }
    measured: dict[str, int] = {}
    for normalized, candidates in aliases.items():
        for candidate in candidates:
            if candidate not in usage:
                continue
            parsed = _nonnegative_int(usage[candidate])
            if parsed is not None:
                measured[normalized] = parsed
            break
    return measured


def _record_model_call(
    repo_root: str,
    *,
    provider: str,
    model: str | None,
    started_at: float,
    ended_at: float,
    usage: dict[str, int],
    total_tokens: int | None,
    cost_usd: float | None,
    failed: bool,
) -> None:
    """Record observed adapter metadata without prompts, outputs, or estimates."""
    payload: dict[str, object] = {
        "provider": provider,
        "end_ts": ended_at,
        "duration_seconds": max(0.0, ended_at - started_at),
        "status": "error" if failed else "ok",
    }
    if model is not None:
        payload["model"] = model
    payload.update(usage)
    if total_tokens is not None:
        payload["total"] = total_tokens
    if cost_usd is not None:
        payload["cost_usd"] = cost_usd
    record_trace_event(
        Path(repo_root),
        TraceEvent(
            kind=TraceEventKind.MODEL_CALL,
            ts=started_at,
            payload=payload,
        ),
    )


#: Claude `-p` result subtypes that set is_error=true but are *soft* — the run
#: may have applied useful edits (ran out of turns, or a non-edit tool blocked).
#: These are not fatal agent errors; ONMC's own verifier grades the outcome.
_CLAUDE_SOFT_SUBTYPES = frozenset({"error_max_turns", "error_during_execution"})


def _detect_claude_error(raw: str) -> str | None:
    """Return an error message when the Claude CLI JSON signals an API failure.

    The Claude CLI reports API/auth failures *inside* a structurally-successful
    JSON envelope, e.g.::

        {"type": "result", "subtype": "success", "is_error": true,
         "api_error_status": 401,
         "result": "Failed to authenticate. API Error: 401 ..."}

    Without this check the error text would be parsed as ordinary agent output
    and a lenient verifier could let the loop "converge" on a run where the
    agent never actually authenticated.  Returns ``None`` for healthy output or
    when stdout is not the structured JSON envelope.
    """
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    api_status = data.get("api_error_status")
    api_failure = api_status not in (None, 0, False)
    # Claude also sets is_error=true for *soft* terminal subtypes (ran out of
    # turns, or a non-edit tool was blocked under acceptEdits). Those runs often
    # still applied useful edits, so treating them as a fatal agent error hides
    # real work from ONMC's own verifier and trips the loop's repeated-error
    # breaker. Grade the repository outcome, not the agent's completion state:
    # only genuine API/auth failures are fatal here; soft subtypes flow through
    # so the independent verifier decides.
    hard_is_error = (
        data.get("is_error") is True and data.get("subtype") not in _CLAUDE_SOFT_SUBTYPES
    )
    if api_failure or hard_is_error:
        # Prefer the human-readable result/error text; fall back to the status.
        for key in ("result", "error", "message"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        if api_failure:
            return f"Claude API error (status {api_status})"
        return "Claude reported is_error=true with no message"
    return None


# ---------------------------------------------------------------------------
# ClaudeCliAdapter
# ---------------------------------------------------------------------------


class ClaudeCliAdapter:
    """Agent adapter that drives the Claude CLI in headless print mode.

    Calls ``claude -p <prompt> --output-format json [--model <model>]``.
    Falls back gracefully to raw stdout when JSON is missing or unparseable.

    Parameters
    ----------
    repo_root:
        Working directory for the subprocess (and for git status diffing).
    model:
        Optional model override (e.g. ``"claude-opus-4-5"``).  When
        ``None``, the CLI uses its own default.
    command_runner:
        Injectable subprocess boundary.  Defaults to the real
        ``subprocess.run`` wrapper.  Tests inject a fake here.
    timeout:
        Seconds before the agent subprocess is killed.
    """

    def __init__(
        self,
        repo_root: Path,
        *,
        model: str | None = None,
        command_runner: CommandRunner | None = None,
        timeout: int = 600,
    ) -> None:
        self._repo_root = str(repo_root)
        self._model = model
        self._cmd_runner = command_runner or _default_command_runner
        self._timeout = timeout

    def __call__(self, prompt: str, *, escalation_level: int) -> AgentRunResult:
        """Run Claude CLI and return a structured AgentRunResult."""
        effective_prompt = _maybe_escalate_prompt(prompt, escalation_level)

        # Optionally bump model on escalation.
        effective_model = self._model
        if escalation_level > 0 and effective_model is not None:
            effective_model = _ESCALATION_MODEL_UPGRADE.get(effective_model, effective_model)

        # Snapshot git status before running.
        before = _git_status_paths(self._cmd_runner, self._repo_root, 30)

        # Headless runs must be able to apply file edits, or the loop spins on
        # blocked writes (observed in smoke: unapplied edits -> duplicate-action).
        # `acceptEdits` auto-accepts edit/write tools only; it is NOT the blanket
        # `bypassPermissions` skip — bash/network stay gated by Claude Code.
        cmd = [
            "claude",
            "-p",
            effective_prompt,
            "--output-format",
            "json",
            "--permission-mode",
            "acceptEdits",
        ]
        if effective_model:
            cmd.extend(["--model", effective_model])

        call_started_at = time.time()
        proc = self._cmd_runner(cmd, self._repo_root, self._timeout)
        call_ended_at = time.time()

        # Snapshot git status after running.
        after = _git_status_paths(self._cmd_runner, self._repo_root, 30)
        files_touched = _compute_files_touched(before, after)

        output, tokens, cost_usd = _parse_claude_json(proc.stdout)
        measured_usage = _parse_claude_usage(proc.stdout)

        # Detect an API/auth error reported inside the JSON envelope (e.g. 401).
        error: str | None = _detect_claude_error(proc.stdout)

        # If the agent call failed at the OS level, surface the error clearly.
        if proc.returncode == 127 or (not output and proc.stderr):
            output = proc.stderr.strip() or "[claude: no output]"
            tokens = None
            cost_usd = None
            if error is None:
                error = output
        elif error is not None:
            # Make the error visible in the output too, but keep tokens/cost
            # off a failed call so accounting never credits work that did not
            # happen.
            output = error
            tokens = None
            cost_usd = None

        # Derive a short prediction from the first non-empty line of output.
        prediction = _first_line(output)
        _record_model_call(
            self._repo_root,
            provider="anthropic",
            model=effective_model,
            started_at=call_started_at,
            ended_at=call_ended_at,
            usage=measured_usage if error is None else {},
            total_tokens=tokens,
            cost_usd=cost_usd,
            failed=error is not None,
        )

        return AgentRunResult(
            output=output,
            prediction=prediction,
            files_touched=files_touched,
            tokens=tokens,
            cost_usd=cost_usd,
            error=error,
        )


# ---------------------------------------------------------------------------
# Codex: best-effort token capture
# ---------------------------------------------------------------------------

#: Codex CLI prints a human-readable usage total on a successful headless run,
#: e.g. ``tokens used: 14,678``.  Some versions omit the colon or put the number
#: on the next line, so ``\s`` (which matches newlines) separates the words.
#: The capture group deliberately cannot end on a comma.
_CODEX_TOKENS_RE = re.compile(r"tokens\s+used\s*:?\s*(\d[\d,]*\d|\d)", re.IGNORECASE)

#: A count is only accepted when it is a plain integer or correctly comma-grouped.
#: Anything else (``14,67``, ``1,2,3``) is malformed and yields ``None``.
_CODEX_COUNT_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)$")


def _parse_codex_tokens(raw: str) -> int | None:
    """Best-effort extraction of Codex's human-readable token total.

    The Codex CLI exposes **no** machine-readable usage or cost in headless
    ``exec`` mode.  It does, however, print a human-readable total such as
    ``tokens used: 14,678``, which is real data worth keeping when present.

    This parse is strictly best-effort and fails closed: an absent line, a
    non-numeric value, a badly grouped number, or a non-positive count all
    return ``None``.  A metric is never fabricated — absence is ``None``, never
    ``0``.  When Codex prints the line more than once the last occurrence wins,
    since Codex reports a cumulative total.
    """
    if not raw:
        return None
    matches = _CODEX_TOKENS_RE.findall(raw)
    if not matches:
        return None
    candidate = matches[-1]
    if not _CODEX_COUNT_RE.match(candidate):
        return None
    try:
        value = int(candidate.replace(",", ""))
    except ValueError:  # pragma: no cover - guarded by _CODEX_COUNT_RE
        return None
    return value if value > 0 else None


# ---------------------------------------------------------------------------
# Codex: provider-failure classification
# ---------------------------------------------------------------------------

# The loop already has exactly one channel for "the agent invocation itself
# failed rather than doing work": ``AgentRunResult.error``.  ``run_loop`` turns a
# non-None ``error`` into a forced loss, stops with ``stop_reason='agent-error'``
# and writes ``[agent-error] <error>`` into that iteration's *verify_output* —
# the harness-controlled field that ``engine._classify_failure_cause`` reads.
# ``[agent-error]`` is itself one of the engine's ``_ENV_PATTERNS``, so every
# adapter error is already classified ``'environment'`` and is never stored as a
# FAILED_APPROACH dead-end.
#
# What that contract does *not* yet express is *why* the invocation failed.  A
# provider 503/throttle is transient infrastructure and a 401 is a missing
# credential; neither is the agent deciding it cannot do the work, and a
# benchmark must not score them as agent losses.  Rather than add a competing
# field or a second error concept, these markers are prefixed onto the existing
# ``error`` string so they land inside ``verify_output`` — following the same
# bracketed-marker convention the loop already uses there (``[agent-error]``,
# ``[verify error:``, ``[no-op]``, ``[scope-unverifiable]``).

#: Provider was reachable-but-unwilling (throttled, overloaded, unavailable) or
#: the transport gave up.  Transient infrastructure, not an agent failure.
TRANSIENT_ERROR_MARKER = "[transient-infra]"

#: No usable credentials, so the run never reached a model at all.
CREDENTIALS_ERROR_MARKER = "[credentials-error]"

#: Lowercase substrings that identify a *credentials* failure.  Codex emits
#: ``401 Unauthorized: Missing bearer`` when no auth is configured.
_CODEX_CREDENTIAL_PATTERNS: tuple[str, ...] = (
    "401 unauthorized",
    "status 401",
    "error 401",
    "missing bearer",
    "invalid bearer",
    "unauthorized",
    "authentication failed",
    "invalid api key",
    "incorrect api key",
    "missing api key",
    "invalid_api_key",
    "not logged in",
    "codex login",
)

#: Lowercase substrings that identify a *transient* provider/infrastructure
#: failure.  Codex surfaces throttling as
#: ``ERROR: unexpected status 503 ... "code":"throttled"`` followed by reconnect
#: attempts that eventually give up.
_CODEX_TRANSIENT_PATTERNS: tuple[str, ...] = (
    "status 503",
    "error 503",
    "503 service unavailable",
    "service unavailable",
    "throttled",
    "rate limit",
    "rate-limit",
    "too many requests",
    "status 429",
    "error 429",
    "status 502",
    "status 504",
    "bad gateway",
    "gateway timeout",
    "overloaded",
    "temporarily unavailable",
    "connection reset",
    "connection refused",
    "stream disconnected",
    "reconnect attempts exhausted",
    "retries exhausted",
    "retry limit",
)


def _classify_codex_failure(text: str) -> str | None:
    """Return a provider-failure marker for *text*, or ``None``.

    Credentials are checked first: when a run failed to authenticate and then
    retried into a 503, the missing credential is the actionable root cause.

    ``None`` means "no recognised provider signature" — i.e. treat it as a
    genuine agent failure.  That is deliberately the default, so an unfamiliar
    error is never quietly excused as infrastructure.
    """
    lowered = text.lower()
    if any(pat in lowered for pat in _CODEX_CREDENTIAL_PATTERNS):
        return CREDENTIALS_ERROR_MARKER
    if any(pat in lowered for pat in _CODEX_TRANSIENT_PATTERNS):
        return TRANSIENT_ERROR_MARKER
    return None


# ---------------------------------------------------------------------------
# CodexCliAdapter
# ---------------------------------------------------------------------------


class CodexCliAdapter:
    """Agent adapter that drives the Codex CLI in headless exec mode.

    Calls ``codex exec --sandbox workspace-write [--model <model>] <prompt>``.

    Sandbox
    -------
    Codex CLI's non-interactive ``exec`` defaults to a read-only sandbox.  ONMC
    loops are already isolated in git worktrees, so ``workspace-write`` is the
    least-privilege mode that still lets the agent make the requested edits.

    Authentication
    --------------
    This adapter configures **no** authentication of its own: the argv it builds
    carries no credential flag, and it neither sets nor filters environment
    variables (``command_runner`` inherits the ambient process environment).
    Which credential Codex uses — its own stored login or an environment
    variable such as ``OPENAI_API_KEY`` — is therefore entirely the Codex CLI's
    decision and is not observable from here.  The consequence for callers is
    that a missing or rejected credential shows up only as text in Codex's
    output (``401 Unauthorized: Missing bearer``), which
    :func:`_classify_codex_failure` labels with
    :data:`CREDENTIALS_ERROR_MARKER` so it is not mistaken for the agent failing
    the task.

    Usage and cost
    --------------
    Codex reports no machine-readable usage or cost in headless mode.  ``tokens``
    is parsed best-effort from the human-readable ``tokens used: N`` line and is
    ``None`` when that line is absent, malformed, or the invocation failed.
    ``cost_usd`` is always ``None`` — Codex never reports it, and it is never
    fabricated as ``0``.

    Parameters
    ----------
    repo_root:
        Working directory for the subprocess (and for git status diffing).
    model:
        Optional Codex model selector.
    command_runner:
        Injectable subprocess boundary.  Tests inject a fake here.
    timeout:
        Seconds before the agent subprocess is killed.
    """

    def __init__(
        self,
        repo_root: Path,
        *,
        model: str | None = None,
        command_runner: CommandRunner | None = None,
        timeout: int = 600,
    ) -> None:
        self._repo_root = str(repo_root)
        self._model = model
        self._cmd_runner = command_runner or _default_command_runner
        self._timeout = timeout

    def __call__(self, prompt: str, *, escalation_level: int) -> AgentRunResult:
        """Run Codex CLI and return a structured AgentRunResult."""
        effective_prompt = _maybe_escalate_prompt(prompt, escalation_level)

        # Snapshot git status before running.
        before = _git_status_paths(self._cmd_runner, self._repo_root, 30)

        cmd = ["codex", "exec", "--sandbox", "workspace-write"]
        if self._model is not None:
            cmd.extend(["--model", self._model])
        cmd.append(effective_prompt)
        call_started_at = time.time()
        proc = self._cmd_runner(cmd, self._repo_root, self._timeout)
        call_ended_at = time.time()

        # Snapshot git status after running.
        after = _git_status_paths(self._cmd_runner, self._repo_root, 30)
        files_touched = _compute_files_touched(before, after)

        output = proc.stdout.strip()
        stderr_text = proc.stderr.strip()
        tokens = _parse_codex_tokens(proc.stdout)

        if proc.returncode == 127 or (not output and stderr_text):
            output = stderr_text or "[codex: no output]"

        # Classify provider-side failures across *both* streams, since Codex
        # writes throttle/auth errors to stderr while still printing reconnect
        # chatter to stdout.  Only a non-zero exit is eligible: a successful run
        # must never be reclassified just because the agent's own narration
        # mentioned "503" or "unauthorized" (agent output is untrusted input).
        failure_marker: str | None = None
        if proc.returncode != 0:
            failure_marker = _classify_codex_failure(f"{proc.stdout}\n{proc.stderr}")

        error: str | None = None
        if proc.returncode != 0 and (not proc.stdout.strip() or failure_marker is not None):
            # A recognised provider failure is fatal even when Codex managed to
            # print something to stdout first — that chatter is not agent work.
            error = output
            if failure_marker is not None:
                if stderr_text and stderr_text not in error:
                    error = f"{error}\n{stderr_text}"
                error = f"{failure_marker} {error}"
            # Never credit token usage to an invocation that failed.
            tokens = None

        prediction = _first_line(output)
        _record_model_call(
            self._repo_root,
            provider="openai",
            model=self._model,
            started_at=call_started_at,
            ended_at=call_ended_at,
            usage={},
            total_tokens=tokens,
            cost_usd=None,
            failed=error is not None,
        )

        return AgentRunResult(
            output=output,
            prediction=prediction,
            files_touched=files_touched,
            tokens=tokens,
            cost_usd=None,  # Codex reports no cost in headless exec mode
            error=error,
        )


# ---------------------------------------------------------------------------
# OpenCodeCliAdapter
# ---------------------------------------------------------------------------


def _parse_opencode_json(raw: str) -> tuple[str, int | None]:
    """Parse OpenCode ``--format json`` output into ``(text, tokens)``.

    OpenCode emits a stream of JSON events, one per line.  We scan every line
    defensively:

    - Look for an ``assistant`` event or a ``result`` event that carries the
      final response text.  Known layouts (non-exhaustive):

      * ``{"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}``
      * ``{"type": "result", "text": "..."}``
      * A top-level ``{"text": "..."}`` or ``{"result": "..."}``

    - Token usage, when present, may appear as:

      * ``{"type": "result", "usage": {"input": N, "output": M}}``
      * ``{"usage": {"input_tokens": N, "output_tokens": M}}``

    All parsing is done defensively; any malformed line is silently skipped.
    When no structured text is found, the entire raw stdout is returned as-is.
    Tokens are ``None`` when not present.
    """
    if not raw.strip():
        return "", None

    collected_texts: list[str] = []
    total_tokens: int | None = None

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        # Extract text from various event shapes.
        event_type = event.get("type", "")

        # Shape: {"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}
        if event_type == "assistant":
            msg = event.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            t = block.get("text", "")
                            if t:
                                collected_texts.append(t)
                elif isinstance(content, str) and content:
                    collected_texts.append(content)

        # Shape: {"type": "result", "text": "...", "usage": {...}}
        elif event_type == "result":
            t = event.get("text")
            if isinstance(t, str) and t:
                collected_texts.append(t)
            # Usage may live here.
            usage = event.get("usage")
            if isinstance(usage, dict) and total_tokens is None:
                inp = usage.get("input", 0) or usage.get("input_tokens", 0) or 0
                out = usage.get("output", 0) or usage.get("output_tokens", 0) or 0
                total = inp + out
                if total > 0:
                    total_tokens = total

        # Generic fallback shapes.
        else:
            for key in ("text", "result"):
                val = event.get(key)
                if isinstance(val, str) and val:
                    collected_texts.append(val)
                    break

        # Generic usage extraction (any event type).
        if total_tokens is None:
            usage = event.get("usage")
            if isinstance(usage, dict):
                inp = usage.get("input", 0) or usage.get("input_tokens", 0) or 0
                out = usage.get("output", 0) or usage.get("output_tokens", 0) or 0
                total = inp + out
                if total > 0:
                    total_tokens = total

    text = "\n".join(collected_texts).strip()
    if not text:
        # Nothing structured found — return raw stdout as a best-effort fallback.
        text = raw.strip()

    return text, total_tokens


def _parse_opencode_usage(raw: str) -> dict[str, int]:
    """Return the last provider-reported OpenCode usage components."""
    measured: dict[str, int] = {}
    aliases = {
        "input_tokens": ("input_tokens", "input"),
        "output_tokens": ("output_tokens", "output"),
        "cache_read_input_tokens": ("cache_read_input_tokens", "cache_read_tokens"),
        "cache_creation_input_tokens": (
            "cache_creation_input_tokens",
            "cache_creation_tokens",
        ),
        "reasoning_output_tokens": ("reasoning_output_tokens", "reasoning_tokens"),
    }
    for raw_line in raw.splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or not isinstance(event.get("usage"), dict):
            continue
        usage = event["usage"]
        for normalized, candidates in aliases.items():
            for candidate in candidates:
                if candidate not in usage:
                    continue
                parsed = _nonnegative_int(usage[candidate])
                if parsed is not None:
                    measured[normalized] = parsed
                break
    return measured


class OpenCodeCliAdapter:
    """Agent adapter that drives the OpenCode CLI in non-interactive run mode.

    Calls ``opencode run --format json [--model <provider/model>] <prompt>``
    (with ``--dir <repo_root>`` to set the working directory) and parses the
    JSON event stream to extract the assistant's final response text.  Token
    usage is extracted when present in the event stream; otherwise ``tokens``
    is ``None``.

    ``opencode`` reads project context from ``AGENTS.md`` and ``.opencode/``
    automatically when ``--dir`` is set.

    Parameters
    ----------
    repo_root:
        Working directory for the subprocess (and for git status diffing).
        Passed as ``--dir`` to ``opencode run``.
    model:
        Optional model in ``provider/model`` form
        (e.g. ``"anthropic/claude-opus-4-5"``).  When ``None``, opencode's
        configured default is used.
    command_runner:
        Injectable subprocess boundary.  Tests inject a fake here.
    timeout:
        Seconds before the agent subprocess is killed.
    """

    def __init__(
        self,
        repo_root: Path,
        *,
        model: str | None = None,
        command_runner: CommandRunner | None = None,
        timeout: int = 600,
    ) -> None:
        self._repo_root = str(repo_root)
        self._model = model
        self._cmd_runner = command_runner or _default_command_runner
        self._timeout = timeout

    def __call__(self, prompt: str, *, escalation_level: int) -> AgentRunResult:
        """Run OpenCode CLI and return a structured AgentRunResult."""
        effective_prompt = _maybe_escalate_prompt(prompt, escalation_level)

        # Snapshot git status before running.
        before = _git_status_paths(self._cmd_runner, self._repo_root, 30)

        cmd = ["opencode", "run", "--format", "json", "--dir", self._repo_root]
        if self._model:
            cmd.extend(["--model", self._model])
        cmd.append(effective_prompt)

        call_started_at = time.time()
        proc = self._cmd_runner(cmd, self._repo_root, self._timeout)
        call_ended_at = time.time()

        # Snapshot git status after running.
        after = _git_status_paths(self._cmd_runner, self._repo_root, 30)
        files_touched = _compute_files_touched(before, after)

        output, tokens = _parse_opencode_json(proc.stdout)
        measured_usage = _parse_opencode_usage(proc.stdout)

        # Surface OS-level errors cleanly.
        error: str | None = None
        if proc.returncode == 127 or (not output and proc.stderr):
            output = proc.stderr.strip() or "[opencode: no output]"
            tokens = None
        if proc.returncode != 0 and not proc.stdout.strip():
            error = output

        prediction = _first_line(output)
        _record_model_call(
            self._repo_root,
            provider="opencode",
            model=self._model,
            started_at=call_started_at,
            ended_at=call_ended_at,
            usage=measured_usage if error is None else {},
            total_tokens=tokens,
            cost_usd=None,
            failed=error is not None,
        )

        return AgentRunResult(
            output=output,
            prediction=prediction,
            files_touched=files_touched,
            tokens=tokens,
            cost_usd=None,  # OpenCode does not emit cost in headless mode
            error=error,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_line(text: str) -> str:
    """Return the first non-empty line of *text*, truncated to 120 chars."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return ""


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_agent_runner(
    agent: Literal["claude", "codex", "opencode"],
    repo_root: Path,
    *,
    model: str | None = None,
    command_runner: CommandRunner | None = None,
    timeout: int = 600,
) -> ClaudeCliAdapter | CodexCliAdapter | OpenCodeCliAdapter:
    """Build and return a real agent runner matching the AgentRunner protocol.

    Parameters
    ----------
    agent:
        Which CLI to use.  ``"claude"`` → ``ClaudeCliAdapter``;
        ``"codex"`` → ``CodexCliAdapter``;
        ``"opencode"`` → ``OpenCodeCliAdapter``.
    repo_root:
        Absolute path to the repository root.  Used as the subprocess CWD
        and for ``git status`` diffing.
    model:
        Optional model override.  For Claude, a model name
        (e.g. ``"claude-opus-4-5"``).  For OpenCode, a ``provider/model``
        string (e.g. ``"anthropic/claude-opus-4-5"``). For Codex, the model
        is passed through ``--model``.
    command_runner:
        Injectable subprocess boundary for testing.  When ``None`` the
        real ``subprocess.run`` wrapper is used.
    timeout:
        Seconds before the agent subprocess is killed (default 600).

    Returns
    -------
    AgentRunner
        A callable matching ``(prompt, *, escalation_level) -> AgentRunResult``.

    Raises
    ------
    ValueError
        When *agent* is not ``"claude"``, ``"codex"``, or ``"opencode"``.
    """
    if agent == "claude":
        return ClaudeCliAdapter(
            repo_root,
            model=model,
            command_runner=command_runner,
            timeout=timeout,
        )
    if agent == "codex":
        return CodexCliAdapter(
            repo_root,
            model=model,
            command_runner=command_runner,
            timeout=timeout,
        )
    if agent == "opencode":
        return OpenCodeCliAdapter(
            repo_root,
            model=model,
            command_runner=command_runner,
            timeout=timeout,
        )
    raise ValueError(
        f"Unknown agent {agent!r}. Choose 'claude', 'codex', or 'opencode'."
    )


def agent_binary_available(agent: Literal["claude", "codex", "opencode"]) -> bool:
    """Return True when the agent CLI binary is on PATH."""
    binary_map = {"claude": "claude", "codex": "codex", "opencode": "opencode"}
    binary = binary_map.get(agent, agent)
    return shutil.which(binary) is not None
