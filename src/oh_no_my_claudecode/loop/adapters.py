"""Real headless agent adapters for the onmc loop engine.

Two adapters are provided:

- ``ClaudeCliAdapter`` — shells out to ``claude -p <prompt> --output-format json``
  and parses the structured JSON response to extract text, tokens, and cost.
- ``CodexCliAdapter`` — shells out to ``codex exec <prompt>`` (headless mode)
  and returns the raw stdout as output; token usage is not available from the
  Codex CLI in headless mode.

Both adapters compute ``files_touched`` by diffing ``git status --porcelain``
snapshots taken *before* and *after* the agent call, so the list is always
derived from the real working tree rather than fabricated.

Both adapters accept an injectable ``CommandRunner`` so that tests can supply
canned subprocess results without ever spawning a real agent process.

Usage::

    from oh_no_my_claudecode.loop.adapters import make_agent_runner

    runner = make_agent_runner("claude", repo_root=Path("/my/repo"))
    result = runner("Fix the broken import", escalation_level=0)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from oh_no_my_claudecode.loop.models import AgentRunResult

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

        cmd = ["claude", "-p", effective_prompt, "--output-format", "json"]
        if effective_model:
            cmd.extend(["--model", effective_model])

        proc = self._cmd_runner(cmd, self._repo_root, self._timeout)

        # Snapshot git status after running.
        after = _git_status_paths(self._cmd_runner, self._repo_root, 30)
        files_touched = _compute_files_touched(before, after)

        output, tokens, cost_usd = _parse_claude_json(proc.stdout)

        # If the agent call failed at the OS level, surface the error clearly.
        if proc.returncode == 127 or (not output and proc.stderr):
            output = proc.stderr.strip() or "[claude: no output]"
            tokens = None
            cost_usd = None

        # Derive a short prediction from the first non-empty line of output.
        prediction = _first_line(output)

        return AgentRunResult(
            output=output,
            prediction=prediction,
            files_touched=files_touched,
            tokens=tokens,
            cost_usd=cost_usd,
        )


# ---------------------------------------------------------------------------
# CodexCliAdapter
# ---------------------------------------------------------------------------


class CodexCliAdapter:
    """Agent adapter that drives the Codex CLI in headless exec mode.

    Calls ``codex exec <prompt>``.  Token usage is not available from the
    Codex CLI in headless mode; ``tokens`` is always ``None``.

    Parameters
    ----------
    repo_root:
        Working directory for the subprocess (and for git status diffing).
    command_runner:
        Injectable subprocess boundary.  Tests inject a fake here.
    timeout:
        Seconds before the agent subprocess is killed.
    """

    def __init__(
        self,
        repo_root: Path,
        *,
        command_runner: CommandRunner | None = None,
        timeout: int = 600,
    ) -> None:
        self._repo_root = str(repo_root)
        self._cmd_runner = command_runner or _default_command_runner
        self._timeout = timeout

    def __call__(self, prompt: str, *, escalation_level: int) -> AgentRunResult:
        """Run Codex CLI and return a structured AgentRunResult."""
        effective_prompt = _maybe_escalate_prompt(prompt, escalation_level)

        # Snapshot git status before running.
        before = _git_status_paths(self._cmd_runner, self._repo_root, 30)

        cmd = ["codex", "exec", effective_prompt]
        proc = self._cmd_runner(cmd, self._repo_root, self._timeout)

        # Snapshot git status after running.
        after = _git_status_paths(self._cmd_runner, self._repo_root, 30)
        files_touched = _compute_files_touched(before, after)

        output = proc.stdout.strip()
        if proc.returncode == 127 or (not output and proc.stderr):
            output = proc.stderr.strip() or "[codex: no output]"

        prediction = _first_line(output)

        return AgentRunResult(
            output=output,
            prediction=prediction,
            files_touched=files_touched,
            tokens=None,  # Codex headless does not emit usage
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
    agent: Literal["claude", "codex"],
    repo_root: Path,
    *,
    model: str | None = None,
    command_runner: CommandRunner | None = None,
    timeout: int = 600,
) -> ClaudeCliAdapter | CodexCliAdapter:
    """Build and return a real agent runner matching the AgentRunner protocol.

    Parameters
    ----------
    agent:
        Which CLI to use.  ``"claude"`` → ``ClaudeCliAdapter``;
        ``"codex"`` → ``CodexCliAdapter``.
    repo_root:
        Absolute path to the repository root.  Used as the subprocess CWD
        and for ``git status`` diffing.
    model:
        Optional model override (Claude only).  Ignored for Codex.
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
        When *agent* is not ``"claude"`` or ``"codex"``.
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
            command_runner=command_runner,
            timeout=timeout,
        )
    raise ValueError(
        f"Unknown agent {agent!r}. Choose 'claude' or 'codex'."
    )


def agent_binary_available(agent: Literal["claude", "codex"]) -> bool:
    """Return True when the agent CLI binary is on PATH."""
    binary = "claude" if agent == "claude" else "codex"
    return shutil.which(binary) is not None
