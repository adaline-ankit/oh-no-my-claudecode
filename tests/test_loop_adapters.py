"""Tests for loop/adapters.py.

All tests use an INJECTED fake CommandRunner — no real subprocess, no real
agent binary is ever invoked.  Deterministic and fast.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oh_no_my_claudecode.loop.adapters import (
    ClaudeCliAdapter,
    CodexCliAdapter,
    CommandRunner,
    CompletedProc,
    OpenCodeCliAdapter,
    _detect_claude_error,
    _parse_claude_json,
    _parse_opencode_json,
    make_agent_runner,
)
from oh_no_my_claudecode.loop.models import AgentRunResult

# ---------------------------------------------------------------------------
# Helpers — fake CommandRunner factories
# ---------------------------------------------------------------------------


def _make_runner(
    responses: dict[str, CompletedProc],
    *,
    git_status_before: str = "",
    git_status_after: str = "",
) -> CommandRunner:
    """Build a fake CommandRunner that returns canned responses.

    - ``git status --porcelain`` before the agent call returns *git_status_before*.
    - ``git status --porcelain`` after the agent call returns *git_status_after*.
    - Any other command is matched against *responses* by its first element.
    """
    git_call_count = [0]

    def _runner(cmd: list[str], cwd: str, timeout: int) -> CompletedProc:  # noqa: ARG001
        # Detect git status calls by their shape.
        if len(cmd) >= 3 and cmd[0] == "git" and "status" in cmd:
            git_call_count[0] += 1
            # Even calls = "before", odd calls = "after".
            status_out = git_status_before if git_call_count[0] % 2 == 1 else git_status_after
            return CompletedProc(returncode=0, stdout=status_out, stderr="")
        # Match agent binary (first element).
        key = cmd[0]
        if key in responses:
            return responses[key]
        return CompletedProc(returncode=0, stdout="", stderr="")

    return _runner


def _simple_claude_runner(
    stdout: str,
    returncode: int = 0,
    git_before: str = "",
    git_after: str = "",
) -> CommandRunner:
    return _make_runner(
        {"claude": CompletedProc(returncode=returncode, stdout=stdout, stderr="")},
        git_status_before=git_before,
        git_status_after=git_after,
    )


def _simple_codex_runner(
    stdout: str,
    returncode: int = 0,
    git_before: str = "",
    git_after: str = "",
) -> CommandRunner:
    return _make_runner(
        {"codex": CompletedProc(returncode=returncode, stdout=stdout, stderr="")},
        git_status_before=git_before,
        git_status_after=git_after,
    )


# ---------------------------------------------------------------------------
# _parse_claude_json unit tests
# ---------------------------------------------------------------------------


def test_parse_claude_json_layout1_result_key() -> None:
    """Layout 1: top-level 'result' key."""
    raw = json.dumps(
        {
            "result": "Here is the fix.",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
    )
    text, tokens, cost_usd = _parse_claude_json(raw)
    assert text == "Here is the fix."
    assert tokens == 150
    assert cost_usd is None


def test_parse_claude_json_layout2_content_list() -> None:
    """Layout 2: top-level 'content' list with type=text blocks."""
    raw = json.dumps(
        {
            "content": [
                {"type": "text", "text": "Part one."},
                {"type": "text", "text": "Part two."},
            ],
            "usage": {"input_tokens": 200, "output_tokens": 80},
        }
    )
    text, tokens, cost_usd = _parse_claude_json(raw)
    assert "Part one." in text
    assert "Part two." in text
    assert tokens == 280
    assert cost_usd is None


def test_parse_claude_json_layout3_message_wrapper() -> None:
    """Layout 3: nested under 'message' key with total_cost_usd."""
    raw = json.dumps(
        {
            "message": {
                "content": [{"type": "text", "text": "Fixed it."}]
            },
            "total_cost_usd": 0.002,
            "usage": {"input_tokens": 50, "output_tokens": 20},
        }
    )
    text, tokens, cost_usd = _parse_claude_json(raw)
    assert text == "Fixed it."
    assert tokens == 70
    assert cost_usd == pytest.approx(0.002, abs=1e-6)


def test_parse_claude_json_bad_json_falls_back_to_raw() -> None:
    """Non-JSON stdout is returned as-is with tokens=None, cost_usd=None."""
    raw = "I applied the changes to main.py."
    text, tokens, cost_usd = _parse_claude_json(raw)
    assert text == raw.strip()
    assert tokens is None
    assert cost_usd is None


def test_parse_claude_json_empty_returns_empty() -> None:
    """Empty string returns ('', None, None)."""
    text, tokens, cost_usd = _parse_claude_json("")
    assert text == ""
    assert tokens is None
    assert cost_usd is None


def test_parse_claude_json_no_usage_tokens_none() -> None:
    """Valid JSON with no usage block returns tokens=None."""
    raw = json.dumps({"result": "done"})
    text, tokens, cost_usd = _parse_claude_json(raw)
    assert text == "done"
    assert tokens is None
    assert cost_usd is None


def test_parse_claude_json_top_level_total_tokens() -> None:
    """Some versions emit top-level 'total_tokens'."""
    raw = json.dumps({"result": "ok", "total_tokens": 300})
    text, tokens, cost_usd = _parse_claude_json(raw)
    assert text == "ok"
    assert tokens == 300


# ---------------------------------------------------------------------------
# ClaudeCliAdapter tests
# ---------------------------------------------------------------------------


def test_claude_adapter_parses_result_text(tmp_path: Path) -> None:
    """ClaudeCliAdapter extracts result text from canned JSON stdout."""
    payload = json.dumps(
        {
            "result": "Fixed the bug in utils.py.",
            "usage": {"input_tokens": 80, "output_tokens": 40},
        }
    )
    runner = _simple_claude_runner(payload)
    adapter = ClaudeCliAdapter(tmp_path, command_runner=runner)
    result = adapter("Fix the bug", escalation_level=0)

    assert result.output == "Fixed the bug in utils.py."
    assert result.tokens == 120
    assert result.prediction == "Fixed the bug in utils.py."


def test_claude_adapter_falls_back_on_bad_json(tmp_path: Path) -> None:
    """ClaudeCliAdapter returns raw stdout + tokens=None when JSON is bad."""
    runner = _simple_claude_runner("I made the change.")
    adapter = ClaudeCliAdapter(tmp_path, command_runner=runner)
    result = adapter("Do something", escalation_level=0)

    assert result.output == "I made the change."
    assert result.tokens is None


def test_claude_adapter_files_touched_computed_from_git_status(tmp_path: Path) -> None:
    """files_touched is derived from the diff of before/after git status."""
    payload = json.dumps({"result": "done"})
    git_before = "M  src/old.py\n"
    git_after = "M  src/old.py\n M  src/new.py\n"
    runner = _simple_claude_runner(payload, git_before=git_before, git_after=git_after)
    adapter = ClaudeCliAdapter(tmp_path, command_runner=runner)
    result = adapter("Add new.py", escalation_level=0)

    # "src/new.py" appeared after the call; "src/old.py" was already there.
    assert "src/new.py" in result.files_touched
    assert "src/old.py" not in result.files_touched


def test_claude_adapter_no_files_touched_when_git_unchanged(tmp_path: Path) -> None:
    """files_touched is empty when git status does not change."""
    payload = json.dumps({"result": "nothing changed"})
    status = "M  src/existing.py\n"
    runner = _simple_claude_runner(payload, git_before=status, git_after=status)
    adapter = ClaudeCliAdapter(tmp_path, command_runner=runner)
    result = adapter("No-op", escalation_level=0)

    assert result.files_touched == []


def test_claude_adapter_escalation_appends_hint(tmp_path: Path) -> None:
    """escalation_level > 0 should append the escalation hint to the prompt."""
    seen_prompts: list[str] = []

    def _tracking_runner(cmd: list[str], cwd: str, timeout: int) -> CompletedProc:
        if cmd[0] == "claude":
            # The -p argument is the prompt.
            seen_prompts.append(cmd[2])
        if cmd[0] == "git":
            return CompletedProc(returncode=0, stdout="", stderr="")
        return CompletedProc(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")

    adapter = ClaudeCliAdapter(tmp_path, command_runner=_tracking_runner)
    adapter("Fix this bug", escalation_level=0)
    adapter("Fix this bug", escalation_level=1)

    assert len(seen_prompts) == 2
    # Level-0 prompt should NOT contain the escalation hint.
    assert "materially different" not in seen_prompts[0]
    # Level-1 prompt SHOULD contain the hint.
    assert "materially different" in seen_prompts[1]


def test_claude_adapter_missing_binary_returns_error_output(tmp_path: Path) -> None:
    """returncode=127 (binary not found) surfaces as a clean error in output."""
    runner = _make_runner(
        {"claude": CompletedProc(returncode=127, stdout="", stderr="[binary not found: ...]")},
    )
    adapter = ClaudeCliAdapter(tmp_path, command_runner=runner)
    result = adapter("anything", escalation_level=0)

    assert "not found" in result.output.lower() or result.output.startswith("[")
    assert result.tokens is None


def test_claude_adapter_escalation_bumps_known_model(tmp_path: Path) -> None:
    """When escalation_level > 0 and model is a known key, it should be upgraded."""
    seen_commands: list[list[str]] = []

    def _tracking_runner(cmd: list[str], cwd: str, timeout: int) -> CompletedProc:
        if cmd[0] == "claude":
            seen_commands.append(list(cmd))
        if cmd[0] == "git":
            return CompletedProc(returncode=0, stdout="", stderr="")
        return CompletedProc(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")

    adapter = ClaudeCliAdapter(
        tmp_path,
        model="claude-sonnet-4-5",
        command_runner=_tracking_runner,
    )
    # Level 0 — should use the original model.
    adapter("task", escalation_level=0)
    # Level 1 — should bump to opus.
    adapter("task", escalation_level=1)

    assert len(seen_commands) == 2
    # First call: --model claude-sonnet-4-5
    assert "claude-sonnet-4-5" in seen_commands[0]
    # Second call: --model claude-opus-4-5 (upgraded)
    assert "claude-opus-4-5" in seen_commands[1]


# ---------------------------------------------------------------------------
# CodexCliAdapter tests
# ---------------------------------------------------------------------------


def test_codex_adapter_returns_stdout(tmp_path: Path) -> None:
    """CodexCliAdapter returns raw stdout as output with tokens=None."""
    runner = _simple_codex_runner("Patched the service layer.\nAll tests pass.")
    adapter = CodexCliAdapter(tmp_path, command_runner=runner)
    result = adapter("Fix the service", escalation_level=0)

    assert "Patched the service layer" in result.output
    assert result.tokens is None


def test_codex_adapter_uses_workspace_write_sandbox(tmp_path: Path) -> None:
    """Codex exec must allow writes; bare exec defaults to read-only."""
    seen_commands: list[list[str]] = []

    def _tracker(cmd: list[str], cwd: str, timeout: int) -> CompletedProc:  # noqa: ARG001
        if cmd[0] == "codex":
            seen_commands.append(cmd)
            return CompletedProc(returncode=0, stdout="ok", stderr="")
        if cmd[0] == "git":
            return CompletedProc(returncode=0, stdout="", stderr="")
        return CompletedProc(returncode=0, stdout="", stderr="")

    adapter = CodexCliAdapter(tmp_path, command_runner=_tracker)
    adapter("Fix this", escalation_level=0)

    assert seen_commands == [["codex", "exec", "--sandbox", "workspace-write", "Fix this"]]


def test_codex_adapter_files_touched(tmp_path: Path) -> None:
    """CodexCliAdapter computes files_touched from git status diff."""
    runner = _simple_codex_runner(
        "applied",
        git_before=" M src/a.py\n",
        git_after=" M src/a.py\n M src/b.py\n",
    )
    adapter = CodexCliAdapter(tmp_path, command_runner=runner)
    result = adapter("do work", escalation_level=0)

    assert "src/b.py" in result.files_touched
    assert "src/a.py" not in result.files_touched


def test_codex_adapter_escalation_hint_appended(tmp_path: Path) -> None:
    """escalation_level > 0 appends the hint to the Codex prompt."""
    seen_prompts: list[str] = []

    def _tracker(cmd: list[str], cwd: str, timeout: int) -> CompletedProc:
        if cmd[0] == "codex":
            seen_prompts.append(cmd[-1])
        if cmd[0] == "git":
            return CompletedProc(returncode=0, stdout="", stderr="")
        return CompletedProc(returncode=0, stdout="ok", stderr="")

    adapter = CodexCliAdapter(tmp_path, command_runner=_tracker)
    adapter("Fix this", escalation_level=0)
    adapter("Fix this", escalation_level=2)

    assert "materially different" not in seen_prompts[0]
    assert "materially different" in seen_prompts[1]


# ---------------------------------------------------------------------------
# make_agent_runner factory tests
# ---------------------------------------------------------------------------


def test_make_agent_runner_returns_claude_adapter(tmp_path: Path) -> None:
    """make_agent_runner('claude', ...) returns a ClaudeCliAdapter."""
    runner = _simple_claude_runner(json.dumps({"result": "ok"}))
    adapter = make_agent_runner("claude", tmp_path, command_runner=runner)
    assert isinstance(adapter, ClaudeCliAdapter)


def test_make_agent_runner_returns_codex_adapter(tmp_path: Path) -> None:
    """make_agent_runner('codex', ...) returns a CodexCliAdapter."""
    runner = _simple_codex_runner("output")
    adapter = make_agent_runner("codex", tmp_path, command_runner=runner)
    assert isinstance(adapter, CodexCliAdapter)


def test_make_agent_runner_unknown_agent_raises_value_error(tmp_path: Path) -> None:
    """make_agent_runner raises ValueError for an unknown agent name."""
    with pytest.raises(ValueError, match="Unknown agent"):
        make_agent_runner("gpt4o", tmp_path)  # type: ignore[arg-type]


def test_make_agent_runner_claude_produces_valid_result(tmp_path: Path) -> None:
    """Full round-trip: factory → call → AgentRunResult for Claude."""
    payload = json.dumps(
        {"result": "Added index.", "usage": {"input_tokens": 50, "output_tokens": 25}}
    )
    runner = _simple_claude_runner(payload)
    adapter = make_agent_runner("claude", tmp_path, command_runner=runner)
    result: AgentRunResult = adapter("Add an index", escalation_level=0)

    assert isinstance(result, AgentRunResult)
    assert result.output == "Added index."
    assert result.tokens == 75
    assert isinstance(result.files_touched, list)


def test_make_agent_runner_codex_produces_valid_result(tmp_path: Path) -> None:
    """Full round-trip: factory → call → AgentRunResult for Codex."""
    runner = _simple_codex_runner("Changes applied.")
    adapter = make_agent_runner("codex", tmp_path, command_runner=runner)
    result: AgentRunResult = adapter("Refactor auth", escalation_level=0)

    assert isinstance(result, AgentRunResult)
    assert result.output == "Changes applied."
    assert result.tokens is None
    assert isinstance(result.files_touched, list)


# ---------------------------------------------------------------------------
# service.loop integration with fake runner
# ---------------------------------------------------------------------------


def test_service_loop_with_fake_runner_converges(tmp_path: Path) -> None:
    """service.loop with a fake agent runner converges when verify passes."""
    from oh_no_my_claudecode.loop.engine import run_loop
    from oh_no_my_claudecode.loop.models import (
        AgentRunResult,
        LoopConfig,
        LoopResult,
        LoopSpec,
        VerifyOutcome,
    )
    from oh_no_my_claudecode.storage import SQLiteStorage

    # Bootstrap a minimal onmc project in tmp_path.
    # We test run_loop directly (the engine) with a fake runner rather than
    # going through the full service to avoid git discovery requirements.
    storage = SQLiteStorage(tmp_path / "onmc.db")
    storage.initialize()

    spec = LoopSpec(goal="Add the missing test")
    config = LoopConfig(max_iterations=5)

    def _fake_agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        return AgentRunResult(
            output="Created tests/test_new.py",
            prediction="tests pass",
            files_touched=["tests/test_new.py"],
            tokens=42,
        )

    def _fake_verify(command: str) -> VerifyOutcome:
        del command
        return VerifyOutcome(passed=True, output="1 passed")

    result: LoopResult = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent,
        verify_runner=_fake_verify,
    )

    assert result.converged is True
    assert result.stop_reason == "converged"
    assert result.total_tokens == 42


# ---------------------------------------------------------------------------
# CLI --agent flag
# ---------------------------------------------------------------------------


def _make_cli_runner():  # type: ignore[return]
    """Create a CliRunner, tolerating versions that don't accept mix_stderr."""
    from typer.testing import CliRunner

    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def test_cli_loop_accepts_agent_flag(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """onmc loop must accept --agent (functional check, render-independent).

    Asserting against --help output is brittle: Rich injects ANSI styling and
    wraps in narrow CI terminals, so substring checks for "--agent" flake. A
    dry-run invocation in an initialized repo proves the option is wired without
    spawning any agent.
    """
    from oh_no_my_claudecode.cli import app

    monkeypatch.chdir(sample_repo)
    cli_runner = _make_cli_runner()
    init = cli_runner.invoke(app, ["init"], prog_name="onmc", color=False)
    assert init.exit_code == 0, init.output
    result = cli_runner.invoke(
        app,
        ["loop", "--goal", "demo task", "--agent", "codex", "--dry-run"],
        prog_name="onmc",
        color=False,
    )
    assert result.exit_code == 0, result.output


def test_cli_loop_unknown_agent_rejected() -> None:
    """onmc loop --agent gpt4o should exit non-zero with an error message."""
    from oh_no_my_claudecode.cli import app

    cli_runner = _make_cli_runner()
    result = cli_runner.invoke(
        app,
        ["loop", "--goal", "fix it", "--agent", "gpt4o"],
        prog_name="onmc",
        color=False,
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# _parse_opencode_json unit tests
# ---------------------------------------------------------------------------


def test_parse_opencode_json_assistant_event() -> None:
    """Parses assistant event with content list."""
    import json as _json

    raw = _json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "Fixed the bug."}]
            },
        }
    )
    text, tokens = _parse_opencode_json(raw)
    assert text == "Fixed the bug."
    assert tokens is None


def test_parse_opencode_json_result_event_with_usage() -> None:
    """Parses result event carrying text + usage."""
    import json as _json

    assistant_event = _json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}}
    )
    result_event = _json.dumps(
        {"type": "result", "text": "Done.", "usage": {"input": 100, "output": 50}}
    )
    raw = "\n".join([assistant_event, result_event])
    text, tokens = _parse_opencode_json(raw)
    assert "Done." in text
    assert tokens == 150


def test_parse_opencode_json_tokens_none_on_missing_usage() -> None:
    """When no usage block is present, tokens is None."""
    import json as _json

    raw = _json.dumps({"type": "result", "text": "ok"})
    text, tokens = _parse_opencode_json(raw)
    assert text == "ok"
    assert tokens is None


def test_parse_opencode_json_bad_lines_skipped() -> None:
    """Malformed JSON lines are skipped; valid lines are parsed."""
    import json as _json

    raw = "not-json\n" + _json.dumps({"type": "result", "text": "success"}) + "\nbad"
    text, tokens = _parse_opencode_json(raw)
    assert text == "success"
    assert tokens is None


def test_parse_opencode_json_empty_returns_empty() -> None:
    """Empty string returns ('', None)."""
    text, tokens = _parse_opencode_json("")
    assert text == ""
    assert tokens is None


def test_parse_opencode_json_fallback_to_raw_on_no_text_event() -> None:
    """When no structured text event is found, raw stdout is returned."""
    raw = "plain text output"
    text, tokens = _parse_opencode_json(raw)
    assert text == "plain text output"
    assert tokens is None


# ---------------------------------------------------------------------------
# OpenCodeCliAdapter tests
# ---------------------------------------------------------------------------


def _simple_opencode_runner(
    stdout: str,
    returncode: int = 0,
    git_before: str = "",
    git_after: str = "",
) -> CommandRunner:
    return _make_runner(
        {"opencode": CompletedProc(returncode=returncode, stdout=stdout, stderr="")},
        git_status_before=git_before,
        git_status_after=git_after,
    )


def test_opencode_adapter_parses_assistant_text(tmp_path: Path) -> None:
    """OpenCodeCliAdapter extracts text from a canned assistant event."""
    import json as _json

    payload = _json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "Applied the patch."}]
            },
        }
    )
    runner = _simple_opencode_runner(payload)
    adapter = OpenCodeCliAdapter(tmp_path, command_runner=runner)
    result = adapter("Fix the bug", escalation_level=0)

    assert result.output == "Applied the patch."
    assert result.prediction == "Applied the patch."
    assert result.tokens is None
    assert result.cost_usd is None


def test_opencode_adapter_parses_tokens_from_result_event(tmp_path: Path) -> None:
    """OpenCodeCliAdapter extracts token usage from a result event."""
    import json as _json

    assistant_event = _json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}
    )
    result_event = _json.dumps(
        {"type": "result", "text": "done", "usage": {"input": 80, "output": 40}}
    )
    raw = "\n".join([assistant_event, result_event])
    runner = _simple_opencode_runner(raw)
    adapter = OpenCodeCliAdapter(tmp_path, command_runner=runner)
    result = adapter("task", escalation_level=0)

    assert result.tokens == 120


def test_opencode_adapter_tokens_none_when_absent(tmp_path: Path) -> None:
    """tokens is None when the event stream has no usage block."""
    import json as _json

    payload = _json.dumps({"type": "result", "text": "ok"})
    runner = _simple_opencode_runner(payload)
    adapter = OpenCodeCliAdapter(tmp_path, command_runner=runner)
    result = adapter("task", escalation_level=0)

    assert result.tokens is None


def test_opencode_adapter_files_touched_from_git_status(tmp_path: Path) -> None:
    """files_touched is derived from the before/after git status diff."""
    import json as _json

    payload = _json.dumps({"type": "result", "text": "done"})
    runner = _simple_opencode_runner(
        payload,
        git_before=" M src/a.py\n",
        git_after=" M src/a.py\n M src/new.py\n",
    )
    adapter = OpenCodeCliAdapter(tmp_path, command_runner=runner)
    result = adapter("add file", escalation_level=0)

    assert "src/new.py" in result.files_touched
    assert "src/a.py" not in result.files_touched


def test_opencode_adapter_escalation_appends_hint(tmp_path: Path) -> None:
    """escalation_level > 0 appends the hint to the prompt passed to opencode."""
    import json as _json

    seen_prompts: list[str] = []

    def _tracker(cmd: list[str], cwd: str, timeout: int) -> CompletedProc:
        if cmd[0] == "opencode":
            # The prompt is the last positional argument.
            seen_prompts.append(cmd[-1])
        if cmd[0] == "git":
            return CompletedProc(returncode=0, stdout="", stderr="")
        return CompletedProc(
            returncode=0,
            stdout=_json.dumps({"type": "result", "text": "ok"}),
            stderr="",
        )

    adapter = OpenCodeCliAdapter(tmp_path, command_runner=_tracker)
    adapter("Fix this", escalation_level=0)
    adapter("Fix this", escalation_level=1)

    assert len(seen_prompts) == 2
    assert "materially different" not in seen_prompts[0]
    assert "materially different" in seen_prompts[1]


def test_opencode_adapter_includes_model_flag_when_given(tmp_path: Path) -> None:
    """When model is set, --model <provider/model> is passed to opencode."""
    import json as _json

    seen_commands: list[list[str]] = []

    def _tracker(cmd: list[str], cwd: str, timeout: int) -> CompletedProc:
        if cmd[0] == "opencode":
            seen_commands.append(list(cmd))
        if cmd[0] == "git":
            return CompletedProc(returncode=0, stdout="", stderr="")
        return CompletedProc(
            returncode=0,
            stdout=_json.dumps({"type": "result", "text": "ok"}),
            stderr="",
        )

    adapter = OpenCodeCliAdapter(
        tmp_path, model="anthropic/claude-opus-4-5", command_runner=_tracker
    )
    adapter("task", escalation_level=0)

    assert seen_commands, "opencode was never called"
    cmd = seen_commands[0]
    assert "--model" in cmd
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "anthropic/claude-opus-4-5"


def test_opencode_adapter_no_model_flag_when_none(tmp_path: Path) -> None:
    """When model is None, --model is NOT passed to opencode."""
    import json as _json

    seen_commands: list[list[str]] = []

    def _tracker(cmd: list[str], cwd: str, timeout: int) -> CompletedProc:
        if cmd[0] == "opencode":
            seen_commands.append(list(cmd))
        if cmd[0] == "git":
            return CompletedProc(returncode=0, stdout="", stderr="")
        return CompletedProc(
            returncode=0,
            stdout=_json.dumps({"type": "result", "text": "ok"}),
            stderr="",
        )

    adapter = OpenCodeCliAdapter(tmp_path, command_runner=_tracker)
    adapter("task", escalation_level=0)

    assert seen_commands, "opencode was never called"
    assert "--model" not in seen_commands[0]


def test_opencode_adapter_missing_binary_returns_error(tmp_path: Path) -> None:
    """returncode=127 surfaces a clean error in output with tokens=None."""
    runner = _make_runner(
        {
            "opencode": CompletedProc(
                returncode=127, stdout="", stderr="[binary not found: opencode]"
            )
        }
    )
    adapter = OpenCodeCliAdapter(tmp_path, command_runner=runner)
    result = adapter("anything", escalation_level=0)

    assert result.tokens is None
    assert result.output  # Some non-empty error text


def test_opencode_adapter_builds_correct_argv(tmp_path: Path) -> None:
    """Verify exact argv: opencode run --format json --dir <root> <prompt>."""
    import json as _json

    seen_commands: list[list[str]] = []

    def _tracker(cmd: list[str], cwd: str, timeout: int) -> CompletedProc:
        if cmd[0] == "opencode":
            seen_commands.append(list(cmd))
        if cmd[0] == "git":
            return CompletedProc(returncode=0, stdout="", stderr="")
        return CompletedProc(
            returncode=0,
            stdout=_json.dumps({"type": "result", "text": "ok"}),
            stderr="",
        )

    adapter = OpenCodeCliAdapter(tmp_path, command_runner=_tracker)
    adapter("Fix the import", escalation_level=0)

    assert seen_commands
    cmd = seen_commands[0]
    assert cmd[0] == "opencode"
    assert cmd[1] == "run"
    assert "--format" in cmd
    assert "json" in cmd
    assert "--dir" in cmd
    assert cmd[-1] == "Fix the import"


# ---------------------------------------------------------------------------
# make_agent_runner factory — opencode
# ---------------------------------------------------------------------------


def test_make_agent_runner_returns_opencode_adapter(tmp_path: Path) -> None:
    """make_agent_runner('opencode', ...) returns an OpenCodeCliAdapter."""
    import json as _json

    runner = _simple_opencode_runner(_json.dumps({"type": "result", "text": "ok"}))
    adapter = make_agent_runner("opencode", tmp_path, command_runner=runner)
    assert isinstance(adapter, OpenCodeCliAdapter)


def test_make_agent_runner_opencode_produces_valid_result(tmp_path: Path) -> None:
    """Full round-trip: make_agent_runner('opencode') → call → AgentRunResult."""
    import json as _json

    payload = _json.dumps(
        {
            "type": "result",
            "text": "Refactored auth module.",
            "usage": {"input": 60, "output": 30},
        }
    )
    runner = _simple_opencode_runner(payload)
    adapter = make_agent_runner("opencode", tmp_path, command_runner=runner)
    result: AgentRunResult = adapter("Refactor auth", escalation_level=0)

    assert isinstance(result, AgentRunResult)
    assert result.output == "Refactored auth module."
    assert result.tokens == 90
    assert isinstance(result.files_touched, list)


def test_make_agent_runner_unknown_still_raises(tmp_path: Path) -> None:
    """Unknown agent still raises ValueError even after opencode is added."""
    with pytest.raises(ValueError, match="Unknown agent"):
        make_agent_runner("gpt4o", tmp_path)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# CLI --agent opencode flag
# ---------------------------------------------------------------------------


def test_cli_loop_accepts_opencode_agent(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """onmc loop --agent opencode --dry-run must exit 0 (no binary needed in dry-run)."""
    from oh_no_my_claudecode.cli import app

    monkeypatch.chdir(sample_repo)
    cli_runner = _make_cli_runner()
    init = cli_runner.invoke(app, ["init"], prog_name="onmc", color=False)
    assert init.exit_code == 0, init.output
    result = cli_runner.invoke(
        app,
        ["loop", "--goal", "demo task", "--agent", "opencode", "--dry-run"],
        prog_name="onmc",
        color=False,
    )
    assert result.exit_code == 0, result.output


def test_cli_autopilot_accepts_opencode_agent(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """onmc autopilot --agent opencode --dry-run must be accepted (not rejected as unknown agent).

    Autopilot --dry-run exits 1 by design (not verified), so we only assert
    that the exit code is not caused by the unknown-agent rejection path.
    Unknown agents produce a distinct error message; dry-run produces the
    KNOW/ACT/PROVE/LEARN output instead.
    """
    from oh_no_my_claudecode.cli import app

    monkeypatch.chdir(sample_repo)
    cli_runner = _make_cli_runner()
    init = cli_runner.invoke(app, ["init"], prog_name="onmc", color=False)
    assert init.exit_code == 0, init.output
    result = cli_runner.invoke(
        app,
        ["autopilot", "demo task", "--agent", "opencode", "--dry-run"],
        prog_name="onmc",
        color=False,
    )
    # autopilot --dry-run exits 1 (not-verified) — that is expected and correct.
    # We only verify the option was not rejected as an unknown agent.
    assert "Unknown agent" not in result.output


# ---------------------------------------------------------------------------
# Agent-error detection (auth/API failures must NOT look like success)
# ---------------------------------------------------------------------------

# The exact envelope a real `claude -p --output-format json` returns on a 401.
_CLAUDE_401 = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "api_error_status": 401,
        "result": "Failed to authenticate. API Error: 401 Invalid authentication credentials",
        "total_cost_usd": 0,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
)


def test_detect_claude_error_401_is_error_flag() -> None:
    """is_error=true → a non-None error carrying the message."""
    err = _detect_claude_error(_CLAUDE_401)
    assert err is not None
    assert "401" in err


def test_detect_claude_error_api_status_only() -> None:
    """A truthy api_error_status alone is enough to flag the failure."""
    raw = json.dumps({"type": "result", "api_error_status": 529, "result": "Overloaded"})
    assert _detect_claude_error(raw) == "Overloaded"


def test_detect_claude_error_soft_subtypes_are_not_fatal() -> None:
    """is_error=true with a *soft* subtype (max-turns / execution) is NOT a fatal
    agent error — the edit may have landed, so ONMC's own verifier must decide."""
    for subtype in ("error_max_turns", "error_during_execution"):
        raw = json.dumps(
            {"type": "result", "subtype": subtype, "is_error": True, "result": "ran out"}
        )
        assert _detect_claude_error(raw) is None, subtype


def test_detect_claude_error_hard_is_error_without_api_status_still_fatal() -> None:
    """A non-soft is_error=true (no api_status) remains fatal."""
    raw = json.dumps({"type": "result", "subtype": "error_other", "is_error": True})
    assert _detect_claude_error(raw) == "Claude reported is_error=true with no message"


def test_detect_claude_error_healthy_output_is_none() -> None:
    """Normal successful output must NOT be flagged as an error."""
    raw = json.dumps({"result": "Done.", "usage": {"input_tokens": 5, "output_tokens": 3}})
    assert _detect_claude_error(raw) is None


def test_detect_claude_error_non_json_is_none() -> None:
    """Plain stdout (no JSON envelope) is not treated as an error here."""
    assert _detect_claude_error("just some text") is None
    assert _detect_claude_error("") is None


def test_claude_adapter_surfaces_api_error(tmp_path: Path) -> None:
    """ClaudeCliAdapter must set .error (and drop tokens/cost) on a 401."""
    adapter = ClaudeCliAdapter(
        tmp_path,
        command_runner=_simple_claude_runner(_CLAUDE_401),
    )
    res: AgentRunResult = adapter("do the thing", escalation_level=0)
    assert res.error is not None
    assert "401" in res.error
    assert res.tokens is None
    assert res.cost_usd is None
    # The error text is also visible in output so a human reading the receipt sees it.
    assert "401" in res.output


def test_claude_adapter_success_has_no_error(tmp_path: Path) -> None:
    """A healthy claude response leaves .error None (regression guard)."""
    raw = json.dumps({"result": "Fixed it.", "usage": {"input_tokens": 10, "output_tokens": 4}})
    adapter = ClaudeCliAdapter(tmp_path, command_runner=_simple_claude_runner(raw))
    res = adapter("do the thing", escalation_level=0)
    assert res.error is None
    assert res.output == "Fixed it."


def test_codex_adapter_nonzero_with_no_stdout_sets_error(tmp_path: Path) -> None:
    """Codex OS-level failure (nonzero exit, empty stdout) sets .error."""
    runner = _make_runner(
        {"codex": CompletedProc(returncode=1, stdout="", stderr="boom")},
    )
    adapter = CodexCliAdapter(tmp_path, command_runner=runner)
    res = adapter("do the thing", escalation_level=0)
    assert res.error is not None
    assert "boom" in res.error
