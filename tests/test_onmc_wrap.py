"""Tests for the ``onmc wrap`` layer — Task intercept + prompt router.

Coverage
--------
- ``compile_task_intercept``:
  - raw Task spawn → strict deny JSON of the correct PreToolUse shape;
  - allowed (returns "") when ``ONMC_ALLOW_TASK`` is truthy;
  - allowed (returns "") when an onmc swarm is active (self-exemption);
  - non-Task tool → "" (untouched);
  - malformed payload → "" with no raise (never-brick);
  - soft mode → additionalContext warning (not a deny).
- ``compile_prompt_policy``: mentions the routed strategy; never raises.
- ``swarm_active``: fresh marker + pending unit → True; stale / all-recorded
  → False.
- ``wrap`` → ``unwrap`` leaves a temp settings.json byte-identical (round-trip),
  and strict vs soft are recorded distinctly.
- The hook entrypoints are fed stdin directly (NO Rich ``--help`` assertions).

The hooks are exercised by feeding a JSON payload to stdin and capturing
stdout — never by asserting on Rich help text.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer
from typer.testing import CliRunner

from oh_no_my_claudecode.command_registry import register_feature_commands
from oh_no_my_claudecode.hooks.installer import (
    install_wrap_hooks,
    uninstall_wrap_hooks,
    wrap_hooks_installed,
)
from oh_no_my_claudecode.wrap import (
    compile_prompt_policy,
    compile_task_intercept,
    read_wrap_strict,
    remove_claude_md_stanza,
    swarm_active,
    upsert_claude_md_stanza,
    write_wrap_state,
)
from oh_no_my_claudecode.wrap.state import CLAUDE_MD_BEGIN

runner = CliRunner()

_NOW = datetime(2026, 6, 29, 12, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _write_active_swarm(
    repo_root: Path,
    *,
    swarm_id: str = "swarm0001",
    started_at: datetime = _NOW,
    unit_status: str = "pending",
) -> None:
    """Create a swarm dir with an ACTIVE marker and a manifest with one unit."""
    sdir = repo_root / ".onmc" / "swarm" / swarm_id
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "ACTIVE").write_text(started_at.isoformat(), encoding="utf-8")
    manifest = {
        "swarm_id": swarm_id,
        "mode": "inline",
        "units": {"unit-0000": {"goal": "do a thing", "status": unit_status}},
    }
    (sdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


# --------------------------------------------------------------------------- #
# compile_task_intercept
# --------------------------------------------------------------------------- #
def test_task_raw_spawn_strict_denies_with_correct_shape(tmp_path: Path) -> None:
    """A raw Task spawn in strict mode returns a valid PreToolUse deny payload."""
    payload = {"tool_name": "Task", "tool_input": {"prompt": "go build it"}}
    out = compile_task_intercept(payload, tmp_path, strict=True, now=_NOW, env={})
    assert out
    parsed = json.loads(out)
    hook = parsed["hookSpecificOutput"]
    assert hook["hookEventName"] == "PreToolUse"
    assert hook["permissionDecision"] == "deny"
    assert "onmc swarm" in hook["permissionDecisionReason"]


def test_task_allowed_when_env_override_truthy(tmp_path: Path) -> None:
    """ONMC_ALLOW_TASK truthy → the intercept allows the Task (returns "")."""
    payload = {"tool_name": "Task"}
    out = compile_task_intercept(
        payload, tmp_path, strict=True, now=_NOW, env={"ONMC_ALLOW_TASK": "1"}
    )
    assert out == ""


def test_task_allowed_when_swarm_active(tmp_path: Path) -> None:
    """An active onmc swarm self-exempts native Task spawns (returns "")."""
    _write_active_swarm(tmp_path, started_at=_NOW)
    payload = {"tool_name": "Task"}
    out = compile_task_intercept(payload, tmp_path, strict=True, now=_NOW, env={})
    assert out == ""


def test_non_task_tool_untouched(tmp_path: Path) -> None:
    """Any tool other than Task is allowed through unchanged (returns "")."""
    for tool in ("Edit", "Write", "Bash", "Read", "Grep", ""):
        payload = {"tool_name": tool}
        assert compile_task_intercept(payload, tmp_path, strict=True, now=_NOW, env={}) == ""


def test_malformed_payload_never_raises(tmp_path: Path) -> None:
    """Garbage payloads must return "" and never raise (never-brick)."""
    bad_payloads: list[dict[str, object]] = [
        {},
        {"tool_name": 123},
        {"tool_name": None},
        {"tool_name": ["Task"]},
        {"unexpected": object()},
    ]
    for payload in bad_payloads:
        assert compile_task_intercept(payload, tmp_path, strict=True, now=_NOW, env={}) == ""


def test_soft_mode_is_additional_context_not_deny(tmp_path: Path) -> None:
    """Soft mode nudges via additionalContext and does NOT deny the call."""
    payload = {"tool_name": "Task"}
    out = compile_task_intercept(payload, tmp_path, strict=False, now=_NOW, env={})
    assert out
    hook = json.loads(out)["hookSpecificOutput"]
    assert hook["hookEventName"] == "PreToolUse"
    assert "permissionDecision" not in hook
    assert "additionalContext" in hook


def test_strict_and_soft_differ(tmp_path: Path) -> None:
    """Strict and soft produce materially different outputs for the same Task."""
    payload = {"tool_name": "Task"}
    strict_out = compile_task_intercept(payload, tmp_path, strict=True, now=_NOW, env={})
    soft_out = compile_task_intercept(payload, tmp_path, strict=False, now=_NOW, env={})
    assert strict_out != soft_out
    assert "deny" in strict_out
    assert "deny" not in soft_out


# --------------------------------------------------------------------------- #
# swarm_active
# --------------------------------------------------------------------------- #
def test_swarm_active_true_for_fresh_pending(tmp_path: Path) -> None:
    """A fresh marker with a pending unit reads as active."""
    _write_active_swarm(tmp_path, started_at=_NOW, unit_status="pending")
    assert swarm_active(tmp_path, _NOW) is True


def test_swarm_active_false_when_stale(tmp_path: Path) -> None:
    """A marker older than the TTL no longer exempts (reads inactive)."""
    old = _NOW - timedelta(hours=2)
    _write_active_swarm(tmp_path, started_at=old, unit_status="pending")
    assert swarm_active(tmp_path, _NOW) is False


def test_swarm_active_false_when_all_units_recorded(tmp_path: Path) -> None:
    """A fresh marker whose units are all recorded reads as inactive."""
    _write_active_swarm(tmp_path, started_at=_NOW, unit_status="done")
    assert swarm_active(tmp_path, _NOW) is False


def test_swarm_active_false_when_no_swarm_dir(tmp_path: Path) -> None:
    """No swarm directory at all → inactive (and no raise)."""
    assert swarm_active(tmp_path, _NOW) is False


def test_plan_inline_swarm_writes_active_marker(tmp_path: Path) -> None:
    """plan_inline_swarm drops a fresh ACTIVE marker that self-exempts Task."""
    from oh_no_my_claudecode.swarm.inline import plan_inline_swarm

    plan = plan_inline_swarm(tmp_path, ["goal one", "goal two"], concurrency=2, now=_NOW)
    marker = tmp_path / ".onmc" / "swarm" / plan["swarm_id"] / "ACTIVE"
    assert marker.is_file()
    # The intercept must self-exempt while this swarm is live.
    assert swarm_active(tmp_path, _NOW) is True
    assert compile_task_intercept({"tool_name": "Task"}, tmp_path, strict=True, now=_NOW) == ""


# --------------------------------------------------------------------------- #
# compile_prompt_policy
# --------------------------------------------------------------------------- #
def test_prompt_policy_mentions_routed_strategy() -> None:
    """A broad build prompt routes to swarm; the nudge names that strategy."""
    out = compile_prompt_policy("build an end-to-end feature", None, strict=True)
    assert out
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "swarm" in ctx
    assert "onmc swarm" in ctx


def test_prompt_policy_loop_strategy_for_test_fix() -> None:
    """A failing-test prompt routes to loop and nudges toward `onmc loop`."""
    out = compile_prompt_policy("fix the failing test", None, strict=False)
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "loop" in ctx
    assert "soft" in ctx


def test_prompt_policy_empty_returns_blank() -> None:
    """Empty/whitespace prompts produce no context."""
    assert compile_prompt_policy("", None, strict=True) == ""
    assert compile_prompt_policy("   ", None, strict=True) == ""


def test_prompt_policy_never_raises_on_bad_storage() -> None:
    """A storage object that raises on use degrades to routing-only, no raise."""

    class _Boom:
        def __getattr__(self, name: str) -> object:
            raise RuntimeError("boom")

    out = compile_prompt_policy("implement a feature", _Boom(), strict=True)  # type: ignore[arg-type]
    assert out  # routing still works without dead-ends
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "onmc" in ctx


# --------------------------------------------------------------------------- #
# wrap → unwrap round-trip (settings.json byte-identical)
# --------------------------------------------------------------------------- #
def test_wrap_unwrap_round_trip_byte_identical(tmp_path: Path) -> None:
    """Installing then uninstalling the wrap hooks restores settings exactly."""
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    # A pre-existing, non-onmc settings.json with an unrelated hook.
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
    # The wrap install must not have removed the unrelated Bash hook.
    after_install = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "echo hi" in json.dumps(after_install)

    uninstall_wrap_hooks(repo_root=tmp_path, settings_path=settings_path)
    assert not wrap_hooks_installed(settings_path=settings_path)
    assert settings_path.read_text(encoding="utf-8") == original


def test_wrap_unwrap_round_trip_no_prior_settings(tmp_path: Path) -> None:
    """With no prior settings, wrap creates them and unwrap removes the hooks.

    The post-unwrap file is the empty-but-formatted settings the installer
    writes once hooks are stripped — and crucially contains no onmc commands.
    """
    settings_path = tmp_path / ".claude" / "settings.json"
    backup_path = settings_path.with_name("settings.json.onmc-backup")

    install_wrap_hooks(
        repo_root=tmp_path,
        strict=False,
        settings_path=settings_path,
        backup_path=backup_path,
    )
    assert wrap_hooks_installed(settings_path=settings_path)

    uninstall_wrap_hooks(repo_root=tmp_path, settings_path=settings_path)
    remaining = settings_path.read_text(encoding="utf-8")
    assert "task-intercept" not in remaining
    assert "prompt-router" not in remaining


def test_wrap_state_records_strict_vs_soft(tmp_path: Path) -> None:
    """write/read_wrap_strict round-trips both modes distinctly."""
    write_wrap_state(tmp_path, strict=True, now=_NOW)
    assert read_wrap_strict(tmp_path) is True
    write_wrap_state(tmp_path, strict=False, now=_NOW)
    assert read_wrap_strict(tmp_path) is False


def test_read_wrap_strict_defaults_strict_when_missing(tmp_path: Path) -> None:
    """A missing state file reads as strict (the safer default)."""
    assert read_wrap_strict(tmp_path) is True


# --------------------------------------------------------------------------- #
# CLAUDE.md stanza
# --------------------------------------------------------------------------- #
def test_claude_md_stanza_round_trip(tmp_path: Path) -> None:
    """Adding then removing the stanza restores CLAUDE.md byte-identically."""
    claude_md = tmp_path / "CLAUDE.md"
    original = "# My Project\n\nSome existing instructions.\n"
    claude_md.write_text(original, encoding="utf-8")

    upsert_claude_md_stanza(tmp_path)
    text = claude_md.read_text(encoding="utf-8")
    assert CLAUDE_MD_BEGIN in text
    assert "Some existing instructions." in text

    remove_claude_md_stanza(tmp_path)
    assert claude_md.read_text(encoding="utf-8") == original


def test_claude_md_stanza_idempotent(tmp_path: Path) -> None:
    """Upserting twice does not duplicate the stanza."""
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# Proj\n", encoding="utf-8")
    upsert_claude_md_stanza(tmp_path)
    upsert_claude_md_stanza(tmp_path)
    text = claude_md.read_text(encoding="utf-8")
    assert text.count(CLAUDE_MD_BEGIN) == 1


def test_claude_md_created_then_removed_when_only_stanza(tmp_path: Path) -> None:
    """A CLAUDE.md that held only the stanza is deleted on removal."""
    upsert_claude_md_stanza(tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.is_file()
    remove_claude_md_stanza(tmp_path)
    assert not claude_md.is_file()


# --------------------------------------------------------------------------- #
# CLI auto-discovery (verbs + hook entrypoints via stdin — no --help)
# --------------------------------------------------------------------------- #
def _fresh_app() -> typer.Typer:
    fresh = typer.Typer()

    @fresh.command("__sentinel__")
    def _sentinel() -> None:  # pragma: no cover - never invoked
        ...

    return fresh


class _StdinStub(io.StringIO):
    """A stdin replacement whose ``isatty`` reports a non-tty (piped) stream.

    ``_read_hook_payload`` skips reading when stdin is a tty; a bare StringIO
    lacks ``isatty``, so the hook would see no payload. This stub makes the
    feed look like a real piped stdin.
    """

    def isatty(self) -> bool:  # noqa: D401 - trivial override
        return False


def _run_hook(monkeypatch, command, payload: dict[str, object]) -> str:
    """Feed *payload* as stdin JSON to a hook *command* and return its stdout.

    The test suite runs under ``-p no:capture`` (capsys is unavailable), so we
    redirect ``sys.stdout`` into a buffer ourselves.
    """
    monkeypatch.setattr(sys, "stdin", _StdinStub(json.dumps(payload)))
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        command()
    return buffer.getvalue().strip()


def test_wrap_commands_discovered() -> None:
    """Auto-discovery registers the ``wrap`` feature (zero hub edits)."""
    fresh = _fresh_app()
    registered = register_feature_commands(fresh)
    assert "wrap" in registered


def test_task_intercept_hook_entrypoint_via_stdin(monkeypatch, tmp_path: Path) -> None:
    """`onmc hooks task-intercept` reads stdin and emits a deny for a Task."""
    from oh_no_my_claudecode.cli import hooks_task_intercept_command

    payload = {"tool_name": "Task", "cwd": str(tmp_path)}
    # read_wrap_strict defaults to strict with no state file.
    out = _run_hook(monkeypatch, hooks_task_intercept_command, payload)
    assert out
    hook = json.loads(out)["hookSpecificOutput"]
    assert hook["permissionDecision"] == "deny"


def test_task_intercept_hook_silent_for_non_task(monkeypatch, tmp_path: Path) -> None:
    """The hook writes nothing for a non-Task tool."""
    from oh_no_my_claudecode.cli import hooks_task_intercept_command

    payload = {"tool_name": "Edit", "cwd": str(tmp_path)}
    assert _run_hook(monkeypatch, hooks_task_intercept_command, payload) == ""


def test_prompt_router_hook_entrypoint_via_stdin(monkeypatch, tmp_path: Path) -> None:
    """`onmc hooks prompt-router` reads stdin and emits a routed nudge."""
    from oh_no_my_claudecode.cli import hooks_prompt_router_command

    payload = {"prompt": "build an end-to-end feature", "cwd": str(tmp_path)}
    out = _run_hook(monkeypatch, hooks_prompt_router_command, payload)
    assert out
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "onmc" in ctx


def test_prompt_router_hook_silent_for_empty_prompt(monkeypatch, tmp_path: Path) -> None:
    """An empty prompt produces no hook output."""
    from oh_no_my_claudecode.cli import hooks_prompt_router_command

    assert _run_hook(monkeypatch, hooks_prompt_router_command, {"prompt": "   "}) == ""
