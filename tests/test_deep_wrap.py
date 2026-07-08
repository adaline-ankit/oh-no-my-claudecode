"""Tests for the ``onmc wrap`` deep-wrap session switch (Part A + B).

Coverage
--------
- ``session.is_active``:
  - default OFF when wrap.json absent (no wrap layer installed → unconditional)
  - default OFF when wrap.json present and no marker
  - ON after set_active(on=True)
  - OFF after set_active(on=False)
  - default_active=True in wrap.json → is_active returns True without marker
- ``session.set_active``: toggle on/off; re-read is consistent
- ``commands.py``:
  - ``onmc wrap on/off/toggle`` round-trips the marker file
  - ``onmc wrap status --json`` reports correct fields
  - install (callback) writes /onmc slash command; unwrap removes it
- ``cli.py`` hooks (feed fake payloads via stdin monkey-patch):
  - SessionStart auto-activates when default_active; then engages the hook
  - SessionStart no-ops (empty stdout) when inactive
  - prompt-recall no-ops when inactive
  - pre-tool-use no-ops when inactive
  - post-tool-use no-ops when inactive
  - subagent-stop no-ops when inactive
  - task-intercept no-ops when inactive (exit 0, empty stdout)
  - All hooks exit 0 always (never brick)
- Existing wrap behaviour preserved (wrap→unwrap round-trip unchanged)
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from oh_no_my_claudecode.command_registry import register_feature_commands
from oh_no_my_claudecode.wrap.session import (
    is_active,
    read_default_active,
    session_active_path,
    set_active,
)
from oh_no_my_claudecode.wrap.state import write_wrap_state

runner = CliRunner()


# ---------------------------------------------------------------------------
# Stdin stub (identical pattern to test_onmc_wrap.py)
# ---------------------------------------------------------------------------


class _StdinStub(io.StringIO):
    """A non-tty stdin replacement so hook payload reading is triggered."""

    def isatty(self) -> bool:
        return False


def _run_hook(monkeypatch: pytest.MonkeyPatch, command: object, payload: dict[str, object]) -> str:
    """Feed *payload* as stdin JSON to a hook *command* and return its stdout."""
    monkeypatch.setattr(sys, "stdin", _StdinStub(json.dumps(payload)))
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        command()  # type: ignore[operator]
    return buffer.getvalue().strip()


# ---------------------------------------------------------------------------
# is_active / set_active unit tests
# ---------------------------------------------------------------------------


def test_is_active_true_when_wrap_not_installed(tmp_path: Path) -> None:
    """When .onmc/wrap.json is absent, is_active returns True (unconditional)."""
    assert is_active(tmp_path) is True


def test_is_active_false_by_default_when_wrap_installed(tmp_path: Path) -> None:
    """When wrap.json is present but no marker, is_active returns False (default off)."""
    write_wrap_state(tmp_path, strict=True, default_active=False)
    assert is_active(tmp_path) is False


def test_set_active_on_makes_is_active_true(tmp_path: Path) -> None:
    """set_active(on=True) after wrap install → is_active returns True."""
    write_wrap_state(tmp_path, strict=True, default_active=False)
    set_active(tmp_path, on=True)
    assert is_active(tmp_path) is True


def test_set_active_off_makes_is_active_false(tmp_path: Path) -> None:
    """set_active(on=False) → is_active returns False regardless of default."""
    write_wrap_state(tmp_path, strict=True, default_active=True)
    set_active(tmp_path, on=False)
    assert is_active(tmp_path) is False


def test_is_active_default_active_true_without_marker(tmp_path: Path) -> None:
    """When wrap.json has default_active=True and no marker, is_active returns True."""
    write_wrap_state(tmp_path, strict=True, default_active=True)
    marker = session_active_path(tmp_path)
    assert not marker.exists()
    assert is_active(tmp_path) is True


def test_is_active_toggle(tmp_path: Path) -> None:
    """is_active reflects the last set_active call correctly."""
    write_wrap_state(tmp_path, strict=True, default_active=False)
    set_active(tmp_path, on=True)
    assert is_active(tmp_path) is True
    set_active(tmp_path, on=False)
    assert is_active(tmp_path) is False
    set_active(tmp_path, on=True)
    assert is_active(tmp_path) is True


def test_read_default_active_false_when_missing(tmp_path: Path) -> None:
    """read_default_active returns False when wrap.json is absent."""
    assert read_default_active(tmp_path) is False


def test_read_default_active_false_when_not_set(tmp_path: Path) -> None:
    """read_default_active returns False when wrap.json has default_active=False."""
    write_wrap_state(tmp_path, strict=True, default_active=False)
    assert read_default_active(tmp_path) is False


def test_read_default_active_true_when_set(tmp_path: Path) -> None:
    """read_default_active returns True when wrap.json has default_active=True."""
    write_wrap_state(tmp_path, strict=True, default_active=True)
    assert read_default_active(tmp_path) is True


# ---------------------------------------------------------------------------
# CLI commands: on / off / toggle / status
# ---------------------------------------------------------------------------


def _fresh_app() -> typer.Typer:
    fresh = typer.Typer()

    @fresh.command("__sentinel__")
    def _sentinel() -> None:  # pragma: no cover
        ...

    return fresh


def test_wrap_commands_still_discovered() -> None:
    """Auto-discovery still registers the 'wrap' feature after the refactor."""
    fresh = _fresh_app()
    registered = register_feature_commands(fresh)
    assert "wrap" in registered


def test_wrap_on_off_toggle_via_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """onmc wrap on/off/toggle sub-commands update the session marker correctly."""
    from oh_no_my_claudecode.cli import app

    monkeypatch.chdir(tmp_path)
    # Simulate a git repo so discover_repo_root succeeds.
    (tmp_path / ".git").mkdir()
    # Install wrap layer so is_active gates are meaningful.
    write_wrap_state(tmp_path, strict=True, default_active=False)

    result = runner.invoke(app, ["wrap", "on"])
    assert result.exit_code == 0
    assert is_active(tmp_path) is True

    result = runner.invoke(app, ["wrap", "off"])
    assert result.exit_code == 0
    assert is_active(tmp_path) is False

    result = runner.invoke(app, ["wrap", "toggle"])
    assert result.exit_code == 0
    assert is_active(tmp_path) is True

    result = runner.invoke(app, ["wrap", "toggle"])
    assert result.exit_code == 0
    assert is_active(tmp_path) is False


def test_wrap_status_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """onmc wrap status --json emits valid JSON with the expected keys."""
    from oh_no_my_claudecode.cli import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    write_wrap_state(tmp_path, strict=True, default_active=False)
    set_active(tmp_path, on=True)

    result = runner.invoke(app, ["wrap", "status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "session_active" in data
    assert "wrap_installed" in data
    assert "default_active" in data
    assert "mode" in data
    assert "slash_command" in data
    assert data["session_active"] is True
    assert data["wrap_installed"] is True
    assert data["mode"] == "strict"


def test_wrap_install_writes_slash_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """onmc wrap (install) writes .claude/commands/onmc.md."""
    from oh_no_my_claudecode.cli import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    result = runner.invoke(app, ["wrap"])
    assert result.exit_code == 0
    slash_cmd = tmp_path / ".claude" / "commands" / "onmc.md"
    assert slash_cmd.is_file(), f"slash command not written: {slash_cmd}"
    body = slash_cmd.read_text(encoding="utf-8")
    assert "onmc wrap toggle" in body
    assert "onmc wrap status" in body


def test_unwrap_removes_slash_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """onmc unwrap removes the /onmc slash command installed by onmc wrap."""
    from oh_no_my_claudecode.cli import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    runner.invoke(app, ["wrap"])
    slash_cmd = tmp_path / ".claude" / "commands" / "onmc.md"
    assert slash_cmd.is_file()

    result = runner.invoke(app, ["unwrap"])
    assert result.exit_code == 0
    assert not slash_cmd.is_file(), "slash command should have been removed by unwrap"


# ---------------------------------------------------------------------------
# Hook gating — no-op when inactive (exit 0, empty stdout)
# ---------------------------------------------------------------------------


def test_session_start_noop_when_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """hooks_session_start_command emits nothing when deep-wrap is inactive."""
    from oh_no_my_claudecode.cli import hooks_session_start_command

    write_wrap_state(tmp_path, strict=True, default_active=False)
    payload = {"cwd": str(tmp_path), "source": "startup"}
    out = _run_hook(monkeypatch, hooks_session_start_command, payload)
    assert out == "", f"expected no output when inactive, got: {out!r}"


def test_prompt_recall_noop_when_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """hooks_prompt_recall_command emits nothing when deep-wrap is inactive."""
    from oh_no_my_claudecode.cli import hooks_prompt_recall_command

    write_wrap_state(tmp_path, strict=True, default_active=False)
    payload = {"cwd": str(tmp_path), "prompt": "build an end-to-end feature"}
    out = _run_hook(monkeypatch, hooks_prompt_recall_command, payload)
    assert out == "", f"expected no output when inactive, got: {out!r}"


def test_pre_tool_use_noop_when_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """hooks_pre_tool_use_command emits nothing when deep-wrap is inactive."""
    from oh_no_my_claudecode.cli import hooks_pre_tool_use_command

    write_wrap_state(tmp_path, strict=True, default_active=False)
    payload = {
        "cwd": str(tmp_path),
        "tool_name": "Edit",
        "tool_input": {"file_path": str(tmp_path / "src" / "foo.py")},
    }
    out = _run_hook(monkeypatch, hooks_pre_tool_use_command, payload)
    assert out == "", f"expected no output when inactive, got: {out!r}"


def test_post_tool_use_noop_when_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """hooks_post_tool_use_command exits 0 with no telemetry when inactive."""
    from oh_no_my_claudecode.cli import hooks_post_tool_use_command

    # Create .onmc/ so handle_post_tool_use would otherwise try to emit.
    (tmp_path / ".onmc" / "live").mkdir(parents=True)
    write_wrap_state(tmp_path, strict=True, default_active=False)
    payload = {"cwd": str(tmp_path), "tool_name": "Bash", "session_id": "sess-001"}
    # No telemetry file should be written when inactive.
    events_file = tmp_path / ".onmc" / "live" / "events.jsonl"
    out = _run_hook(monkeypatch, hooks_post_tool_use_command, payload)
    assert out == ""
    assert not events_file.exists(), "should not emit telemetry when inactive"


def test_subagent_stop_noop_when_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """hooks_subagent_stop_command exits 0 with no telemetry when inactive."""
    from oh_no_my_claudecode.cli import hooks_subagent_stop_command

    (tmp_path / ".onmc" / "live").mkdir(parents=True)
    write_wrap_state(tmp_path, strict=True, default_active=False)
    payload = {"cwd": str(tmp_path), "session_id": "sess-001", "stop_reason": "end_turn"}
    events_file = tmp_path / ".onmc" / "live" / "events.jsonl"
    out = _run_hook(monkeypatch, hooks_subagent_stop_command, payload)
    assert out == ""
    assert not events_file.exists()


def test_task_intercept_noop_when_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """hooks_task_intercept_command exits 0 with empty stdout when inactive."""
    from oh_no_my_claudecode.cli import hooks_task_intercept_command

    write_wrap_state(tmp_path, strict=True, default_active=False)
    payload = {"cwd": str(tmp_path), "tool_name": "Task", "tool_input": {"prompt": "go"}}
    out = _run_hook(monkeypatch, hooks_task_intercept_command, payload)
    assert out == "", f"expected empty output when inactive, got: {out!r}"


def test_task_intercept_acts_when_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """hooks_task_intercept_command emits a deny when deep-wrap is active."""
    from oh_no_my_claudecode.cli import hooks_task_intercept_command

    write_wrap_state(tmp_path, strict=True, default_active=False)
    set_active(tmp_path, on=True)
    payload = {"cwd": str(tmp_path), "tool_name": "Task", "tool_input": {"prompt": "go"}}
    out = _run_hook(monkeypatch, hooks_task_intercept_command, payload)
    assert out, "expected deny output when active"
    parsed = json.loads(out)
    assert parsed["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_post_tool_use_emits_when_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """hooks_post_tool_use_command writes a telemetry event when active."""
    from oh_no_my_claudecode.cli import hooks_post_tool_use_command

    (tmp_path / ".onmc" / "live").mkdir(parents=True)
    write_wrap_state(tmp_path, strict=True, default_active=False)
    set_active(tmp_path, on=True)
    payload = {"cwd": str(tmp_path), "tool_name": "Bash", "session_id": "sess-002"}
    _run_hook(monkeypatch, hooks_post_tool_use_command, payload)
    events_file = tmp_path / ".onmc" / "live" / "events.jsonl"
    assert events_file.exists(), "telemetry event should have been written when active"
    line = events_file.read_text(encoding="utf-8").strip()
    event = json.loads(line)
    assert event["kind"] == "tool_call"
    assert event["tool"] == "Bash"


def test_session_start_auto_activates_on_default_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SessionStart hook auto-activates the session when default_active=True."""
    from oh_no_my_claudecode.cli import hooks_session_start_command

    write_wrap_state(tmp_path, strict=True, default_active=True)
    # No explicit set_active — relying on auto-activation.
    marker = session_active_path(tmp_path)
    assert not marker.exists()

    payload = {"cwd": str(tmp_path), "source": "startup"}
    # The hook will auto-activate and then try to run the boot digest.
    # We don't need to assert on stdout here — just that the marker is written.
    _run_hook(monkeypatch, hooks_session_start_command, payload)
    assert marker.exists(), "SessionStart should have written the active marker"
    assert marker.read_text(encoding="utf-8").strip() == "1"


def test_all_hooks_exit_zero_on_garbage_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every hook command exits 0 (no raise) when fed a garbage payload."""
    from oh_no_my_claudecode.cli import (
        hooks_post_tool_use_command,
        hooks_pre_compact_command,
        hooks_pre_tool_use_command,
        hooks_prompt_recall_command,
        hooks_session_start_command,
        hooks_subagent_stop_command,
        hooks_task_intercept_command,
    )

    garbage = {"unexpected_key": None, "numbers": [1, 2, 3]}
    for cmd in (
        hooks_session_start_command,
        hooks_prompt_recall_command,
        hooks_pre_tool_use_command,
        hooks_pre_compact_command,
        hooks_post_tool_use_command,
        hooks_subagent_stop_command,
        hooks_task_intercept_command,
    ):
        # Should not raise; any exception would propagate here in tests.
        _run_hook(monkeypatch, cmd, garbage)


def test_existing_wrap_unwrap_round_trip_still_works(tmp_path: Path) -> None:
    """The original wrap→unwrap round-trip is byte-identical after the refactor."""
    from oh_no_my_claudecode.hooks.installer import (
        install_wrap_hooks,
        uninstall_wrap_hooks,
        wrap_hooks_installed,
    )

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    original = (
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "echo hi"}],
                        }
                    ]
                }
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    settings_path.write_text(original, encoding="utf-8")
    backup_path = settings_path.with_name("settings.json.onmc-backup")

    install_wrap_hooks(
        repo_root=tmp_path,
        strict=True,
        settings_path=settings_path,
        backup_path=backup_path,
    )
    assert wrap_hooks_installed(settings_path=settings_path)

    uninstall_wrap_hooks(repo_root=tmp_path, settings_path=settings_path)
    assert not wrap_hooks_installed(settings_path=settings_path)
    assert settings_path.read_text(encoding="utf-8") == original
