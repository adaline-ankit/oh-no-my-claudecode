from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.api import OnmcRepo, init
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.hooks.installer import install_claude_hooks
from oh_no_my_claudecode.mcp_server.tools import call_onmc_tool, list_onmc_tools
from oh_no_my_claudecode.working_context import store
from oh_no_my_claudecode.working_context.hooks import load_working_context


@pytest.fixture
def working_repo(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, OnmcRepo]:
    home = tmp_path / "working-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(sample_repo)
    return sample_repo, init(sample_repo)


def _command(*args: str) -> Any:
    result = CliRunner().invoke(app, ["working", *args])
    assert result.exit_code == 0, result.output + repr(result.exception)
    return result


def _hook(command: str, payload: dict[str, object]) -> str:
    result = CliRunner().invoke(app, ["hooks", command], input=json.dumps(payload))
    assert result.exit_code == 0, repr(result.exception)
    if not result.stdout:
        return ""
    parsed = json.loads(result.stdout)
    assert set(parsed) == {"hookSpecificOutput"}
    body = parsed["hookSpecificOutput"]
    assert set(body) == {"hookEventName", "additionalContext"}
    return str(body["additionalContext"])


def test_working_cli_lifecycle_preserves_constraints_and_disable_configuration(
    working_repo: tuple[Path, OnmcRepo],
) -> None:
    root, _ = working_repo
    config = json.loads(
        _command(
            "enable",
            "--budget-chars",
            "4000",
            "--constraint",
            "Keep old clients compatible",
            "--json",
        ).stdout
    )
    assert config["enabled"] is True
    assert config["budget_chars"] == 4000
    session = json.loads(
        _command("start", "--task", "Fix cache refresh", "--session", "manual", "--json").stdout
    )
    assert session["constraints"] == ["Keep old clients compatible"]
    _command("note", "--session", "manual", "--kind", "decision", "--text", "Use shared cache")
    packet = json.loads(_command("context", "--session", "manual", "--json").stdout)
    assert "Keep old clients compatible" in packet["markdown"]
    assert "Use shared cache" in packet["markdown"]
    assert packet["used_chars"] <= 4000
    refused = CliRunner().invoke(
        app, ["working", "start", "--session", "manual", "--task", "Different task"]
    )
    assert refused.exit_code != 0
    _command("start", "--session", "manual", "--task", "Different task", "--replace")
    config = json.loads(_command("disable", "--json").stdout)
    assert config["enabled"] is False
    assert config["budget_chars"] == 4000
    assert config["constraints"] == ["Keep old clients compatible"]
    assert (root / ".claude" / "settings.json").exists()


def test_hook_goal_is_stable_sessions_are_isolated_and_payload_cwd_wins(
    working_repo: tuple[Path, OnmcRepo], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = working_repo
    _command("enable", "--constraint", "Preserve API compatibility")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("oh_no_my_claudecode.cli._wrap_active_for", lambda _: False)
    first = {"cwd": str(root), "session_id": "alpha", "prompt": "Fix cache refresh"}
    text = _hook("prompt-recall", first)
    assert "Fix cache refresh" in text
    assert "Preserve API compatibility" in text
    _hook("prompt-recall", {**first, "prompt": "Now inspect the worker"})
    second = {"cwd": str(root), "session_id": "beta", "prompt": "Add logging"}
    second_text = _hook("prompt-recall", second)
    assert "Add logging" in second_text
    assert "Fix cache refresh" not in second_text
    _, engine = load_working_context(root)
    session = engine.session("alpha")
    assert session is not None
    assert session.goal == "Fix cache refresh"
    assert session.focus == "Now inspect the worker"
    assert not (tmp_path / ".onmc").exists()


def test_adaptive_delivery_deduplicates_without_falling_back_to_legacy(
    working_repo: tuple[Path, OnmcRepo], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = working_repo
    _command("enable")

    def legacy_forbidden() -> None:
        pytest.fail("adaptive delivery must not inject legacy stale recall")

    monkeypatch.setattr("oh_no_my_claudecode.cli._service", legacy_forbidden)
    payload = {"cwd": str(root), "session_id": "alpha", "prompt": "Fix cache refresh"}
    assert _hook("prompt-recall", payload)
    assert _hook("prompt-recall", payload) == ""
    assert _hook("pre-tool-use", {**payload, "tool_name": "Bash", "tool_input": {}}) == ""


@pytest.mark.parametrize("corrupt_config", [False, True])
def test_adaptive_failure_withdraws_trust_without_legacy_fallback(
    working_repo: tuple[Path, OnmcRepo],
    monkeypatch: pytest.MonkeyPatch,
    corrupt_config: bool,
) -> None:
    root, _ = working_repo
    _command("enable")
    payload = {"cwd": str(root), "session_id": "alpha", "prompt": "Fix cache refresh"}
    _hook("prompt-recall", payload)
    _, engine = load_working_context(root)
    key = store.CONFIG_KEY if corrupt_config else store.session_key("alpha")
    engine.storage.set_meta(key, "private-invalid-state")

    def legacy_forbidden() -> None:
        pytest.fail("invalid adaptive state must not restore legacy recall")

    monkeypatch.setattr("oh_no_my_claudecode.cli._service", legacy_forbidden)
    output = _hook("prompt-recall", payload)
    assert "Working context unavailable" in output
    assert "may be stale" in output
    assert "private-invalid-state" not in output


def test_enable_validates_before_install_and_keeps_global_settings_untouched(
    working_repo: tuple[Path, OnmcRepo],
) -> None:
    root, _ = working_repo
    global_settings = Path.home() / ".claude" / "settings.json"
    global_settings.parent.mkdir()
    content = json.dumps(
        {"hooks": {"PostCompact": [{"hooks": [{"command": "onmc hooks session-start"}]}]}}
    )
    global_settings.write_text(content)
    refused = CliRunner().invoke(app, ["working", "enable", "--constraint", "x" * 2001])
    assert refused.exit_code != 0
    assert not (root / ".claude" / "settings.json").exists()
    assert not (root / ".mcp.json").exists()
    _command("enable")
    assert global_settings.read_text() == content


def test_compact_and_resume_restore_the_same_session_after_deduplication(
    working_repo: tuple[Path, OnmcRepo],
) -> None:
    root, _ = working_repo
    _command("enable", "--constraint", "Keep legacy clients working")
    payload = {"cwd": str(root), "session_id": "alpha", "prompt": "Fix cache refresh"}
    assert _hook("prompt-recall", payload)
    assert _hook("prompt-recall", payload) == ""
    for source in ("compact", "resume"):
        text = _hook("session-start", {**payload, "source": source})
        assert "Keep legacy clients working" in text
        assert "Fix cache refresh" in text
    assert _hook("session-start", {**payload, "session_id": "unknown", "source": "compact"}) == ""


def test_cli_inspection_does_not_consume_next_hook_delivery(
    working_repo: tuple[Path, OnmcRepo],
) -> None:
    root, _ = working_repo
    _command("enable")
    _command("start", "--session", "alpha", "--task", "Fix cache refresh")
    _command("context", "--session", "alpha")
    assert _hook(
        "pre-tool-use",
        {"cwd": str(root), "session_id": "alpha", "tool_name": "Bash", "tool_input": {}},
    )


def test_relative_tool_path_uses_payload_cwd(working_repo: tuple[Path, OnmcRepo]) -> None:
    root, _ = working_repo
    _command("enable")
    _command("start", "--session", "nested", "--task", "Fix cache refresh")
    text = _hook(
        "pre-tool-use",
        {
            "cwd": str(root / "src"),
            "session_id": "nested",
            "tool_name": "Read",
            "tool_input": {"file_path": "worker.py"},
        },
    )
    assert "src/worker.py" in text
    _, engine = load_working_context(root)
    current = engine.session("nested")
    assert current is not None and current.active_files == ["src/worker.py"]


def test_tool_hook_invalidates_note_anchor_after_a_dirty_edit(
    working_repo: tuple[Path, OnmcRepo],
) -> None:
    root, _ = working_repo
    _command("enable")
    payload = {"cwd": str(root), "session_id": "alpha", "prompt": "Fix cache refresh"}
    _hook("prompt-recall", payload)
    _command(
        "note",
        "--session",
        "alpha",
        "--kind",
        "hypothesis",
        "--text",
        "Worker invokes cache once",
        "--file",
        "src/worker.py",
    )
    before = _hook(
        "pre-tool-use",
        {**payload, "tool_name": "Read", "tool_input": {"file_path": "src/worker.py"}},
    )
    assert "Worker invokes cache once" in before
    (root / "src" / "worker.py").write_text("# implementation changed\n", encoding="utf-8")
    after = _hook(
        "post-tool-use",
        {**payload, "tool_name": "Edit", "tool_input": {"file_path": "src/worker.py"}},
    )
    assert after
    packet = json.loads(_command("context", "--session", "alpha", "--json").stdout)
    assert any("source changed" in warning for warning in packet["warnings"])
    assert "Worker invokes cache once" not in packet["markdown"]


def test_disabled_missing_session_and_child_events_do_not_mutate_working_state(
    working_repo: tuple[Path, OnmcRepo], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = working_repo
    _command("enable")
    monkeypatch.setattr("oh_no_my_claudecode.cli._wrap_active_for", lambda _: False)
    base = {"cwd": str(root), "prompt": "Fix cache refresh"}
    assert _hook("prompt-recall", base) == ""
    assert _hook("prompt-recall", {**base, "session_id": "child", "agent_id": "subagent"}) == ""
    _command("disable")
    assert _hook("prompt-recall", {**base, "session_id": "disabled"}) == ""
    _, engine = load_working_context(root)
    assert engine.session("default") is None
    assert engine.session("child") is None
    assert engine.session("disabled") is None
    result = CliRunner().invoke(app, ["hooks", "prompt-recall"], input="not json")
    assert result.exit_code == 0
    assert result.stdout == ""


def test_mcp_working_tools_preserve_user_constraints_and_disabled_state(
    working_repo: tuple[Path, OnmcRepo],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONMC_MCP_FORMAT", "json")
    _, repo = working_repo
    _command("enable", "--constraint", "Preserve API compatibility")
    args = {"session_id": "alpha", "goal": "Fix cache refresh"}
    result = json.loads(call_onmc_tool(repo, "start_working_context", args)[0].text)
    assert result["constraints"] == ["Preserve API compatibility"]
    assert set(result) == {"session_id", "goal", "constraints", "revision"}
    with pytest.raises(ValueError):
        call_onmc_tool(repo, "start_working_context", {**args, "goal": "Change everything"})
    note = call_onmc_tool(
        repo,
        "record_working_note",
        {"session_id": "alpha", "kind": "next_step", "text": "Check worker tests"},
    )
    assert set(json.loads(note[0].text)) == {"session_id", "revision", "recorded"}
    output = call_onmc_tool(repo, "get_working_context", {"session_id": "alpha"})[0].text
    packet = json.loads(output)
    assert "Preserve API compatibility" in packet["context"]
    assert "Check worker tests" in packet["context"]
    assert set(packet) == {
        "session_id",
        "revision",
        "context",
        "used_chars",
        "budget_chars",
        "estimated_tokens",
    }
    assert output.count("Check worker tests") == 1
    schemas = {tool.name: tool.inputSchema for tool in list_onmc_tools()}
    assert "constraints" not in schemas["start_working_context"]["properties"]
    assert "replace" not in schemas["start_working_context"]["properties"]
    assert schemas["record_working_note"]["properties"]["files"]["maxItems"] == 16
    _command("disable")
    with pytest.raises(ValueError, match="disabled"):
        call_onmc_tool(repo, "get_working_context", {"session_id": "alpha"})


def test_plugin_and_installer_register_matching_adaptive_events(
    working_repo: tuple[Path, OnmcRepo],
) -> None:
    root, _ = working_repo
    install_claude_hooks(repo_root=root)
    installed = json.loads((root / ".claude" / "settings.json").read_text())["hooks"]
    plugin_path = Path(__file__).resolve().parents[1] / "hooks" / "hooks.json"
    plugin = json.loads(plugin_path.read_text())["hooks"]
    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"):

        def commands(entries: list[dict[str, Any]]) -> set[str]:
            return {hook["command"] for entry in entries for hook in entry["hooks"]}

        assert commands(plugin[event]) == commands(installed[event])
    assert plugin["PreToolUse"][0]["matcher"] == installed["PreToolUse"][0]["matcher"]
