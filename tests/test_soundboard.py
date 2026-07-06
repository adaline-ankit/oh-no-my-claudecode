"""Tests for ``onmc soundboard`` — fun terminal event reactions.

Coverage
--------
- default reaction for a known event returns expected text.
- bind overrides the default reaction.
- unbind restores the default reaction.
- --bell appends a terminal bell (``\\a``) to the stored binding.
- unknown event returns a safe default (``"…"``) rather than raising.
- list shows merged bindings (defaults + user overrides).
- determinism: react() is deterministic for the same inputs.
- --json: JSON envelope shape for react, list.
- bind + react round-trip through the filesystem (integration).
- load_bindings returns empty dict when file absent.
- save_bindings + load_bindings round-trip.
- merged_bindings: user override wins over default.
- Reaction.emit(): returns text without bell when has_bell=False.
- Reaction.emit(): appends ``\\a`` when has_bell=True.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.soundboard.board import (
    DEFAULTS,
    Reaction,
    load_bindings,
    merged_bindings,
    react,
    save_bindings,
)

_RUNNER = CliRunner()
_BELL = "\a"


# ---------------------------------------------------------------------------
# Pure unit tests — Reaction dataclass
# ---------------------------------------------------------------------------


def test_reaction_emit_no_bell() -> None:
    """Reaction.emit() returns text-only when has_bell=False."""
    r = Reaction(event="test_pass", text="🎉 ding!", has_bell=False)
    assert r.emit() == "🎉 ding!"


def test_reaction_emit_with_bell() -> None:
    """Reaction.emit() appends \\a when has_bell=True."""
    r = Reaction(event="test_pass", text="🎉 ding!", has_bell=True)
    assert r.emit() == "🎉 ding!" + _BELL


def test_reaction_to_dict() -> None:
    """Reaction.to_dict() serialises all fields."""
    r = Reaction(event="build_break", text="💥 womp womp", has_bell=False)
    d = r.to_dict()
    assert d == {"event": "build_break", "text": "💥 womp womp", "has_bell": False}


# ---------------------------------------------------------------------------
# react() — defaults + override
# ---------------------------------------------------------------------------


def test_react_known_event_default() -> None:
    """Known event with only defaults returns the expected built-in text."""
    bindings = merged_bindings({})
    reaction = react("test_pass", bindings)
    assert reaction.event == "test_pass"
    assert reaction.text == DEFAULTS["test_pass"]
    assert not reaction.has_bell


def test_react_unknown_event_safe_default() -> None:
    """Unknown event returns safe default ``…`` rather than raising."""
    bindings = merged_bindings({})
    reaction = react("nonexistent_event_xyz", bindings)
    assert reaction.text == "…"
    assert not reaction.has_bell


def test_react_determinism() -> None:
    """react() is deterministic: same inputs always produce equal results."""
    bindings = merged_bindings({})
    r1 = react("pr_merged", bindings)
    r2 = react("pr_merged", bindings)
    assert r1 == r2


def test_react_user_override_wins() -> None:
    """User override returned by merged_bindings takes precedence."""
    user = {"test_pass": "custom reaction"}
    bindings = merged_bindings(user)
    reaction = react("test_pass", bindings)
    assert reaction.text == "custom reaction"


def test_react_bell_binding() -> None:
    """A binding with trailing \\a produces has_bell=True."""
    bindings = {"build_break": "💀 uh oh" + _BELL}
    reaction = react("build_break", bindings)
    assert reaction.text == "💀 uh oh"
    assert reaction.has_bell


# ---------------------------------------------------------------------------
# load_bindings / save_bindings
# ---------------------------------------------------------------------------


def test_load_bindings_absent_file(tmp_path: Path) -> None:
    """load_bindings returns empty dict when bindings.json is absent."""
    result = load_bindings(tmp_path / "nonexistent")
    assert result == {}


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    """save_bindings + load_bindings round-trip without data loss."""
    sb_dir = tmp_path / ".onmc" / "soundboard"
    data = {"test_pass": "👍 yep", "build_break": "💥 oops"}
    save_bindings(data, sb_dir)
    loaded = load_bindings(sb_dir)
    assert loaded == data


def test_load_bindings_malformed_json(tmp_path: Path) -> None:
    """Malformed JSON in bindings.json is silently ignored."""
    sb_dir = tmp_path / ".onmc" / "soundboard"
    sb_dir.mkdir(parents=True)
    (sb_dir / "bindings.json").write_text("not json!!!", encoding="utf-8")
    assert load_bindings(sb_dir) == {}


# ---------------------------------------------------------------------------
# merged_bindings
# ---------------------------------------------------------------------------


def test_merged_bindings_empty_user() -> None:
    """merged_bindings with no user overrides returns a copy of DEFAULTS."""
    result = merged_bindings({})
    assert result == DEFAULTS
    # Must be a copy, not the same object.
    assert result is not DEFAULTS


def test_merged_bindings_override_wins() -> None:
    """User override for an existing default key wins."""
    custom_text = "CUSTOM"  # noqa: S105
    user = {"test_pass": custom_text}
    result = merged_bindings(user)
    assert result["test_pass"] == custom_text
    # Other defaults are intact.
    assert result["build_break"] == DEFAULTS["build_break"]


def test_merged_bindings_new_event() -> None:
    """User can add a brand-new event not in DEFAULTS."""
    user = {"my_custom_event": "⭐ neat"}
    result = merged_bindings(user)
    assert result["my_custom_event"] == "⭐ neat"


# ---------------------------------------------------------------------------
# CLI — onmc soundboard react
# ---------------------------------------------------------------------------


def test_cli_react_known_event(tmp_path: Path) -> None:
    """``onmc soundboard react test_pass`` emits the default reaction."""
    result = _RUNNER.invoke(app, ["soundboard", "react", "test_pass"], catch_exceptions=False)
    assert result.exit_code == 0
    assert DEFAULTS["test_pass"] in result.output


def test_cli_react_unknown_event(tmp_path: Path) -> None:
    """``onmc soundboard react unknown_xyz`` exits 0 and emits safe default."""
    result = _RUNNER.invoke(
        app, ["soundboard", "react", "unknown_xyz_event"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert "…" in result.output


def test_cli_react_json_envelope(tmp_path: Path) -> None:
    """``onmc soundboard react test_pass --json`` emits a valid JSON envelope."""
    result = _RUNNER.invoke(
        app, ["soundboard", "react", "test_pass", "--json"], catch_exceptions=False
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["kind"] == "soundboard_reaction"
    assert data["event"] == "test_pass"
    assert "text" in data
    assert "has_bell" in data


# ---------------------------------------------------------------------------
# CLI — onmc soundboard list
# ---------------------------------------------------------------------------


def test_cli_list_shows_defaults() -> None:
    """``onmc soundboard list`` contains at least the default events."""
    result = _RUNNER.invoke(app, ["soundboard", "list"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "test_pass" in result.output
    assert "build_break" in result.output


def test_cli_list_json_envelope() -> None:
    """``onmc soundboard list --json`` emits a valid JSON envelope."""
    result = _RUNNER.invoke(app, ["soundboard", "list", "--json"], catch_exceptions=False)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["kind"] == "soundboard_list"
    assert "bindings" in data
    assert "test_pass" in data["bindings"]


# ---------------------------------------------------------------------------
# CLI — onmc soundboard bind + unbind (filesystem integration)
# ---------------------------------------------------------------------------


def test_cli_bind_persists_and_react_uses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """bind persists the override; a subsequent react uses it."""
    sb_dir = tmp_path / ".onmc" / "soundboard"
    # Patch _resolve_soundboard_dir to use tmp_path.
    monkeypatch.setattr(
        "oh_no_my_claudecode.soundboard.commands._resolve_soundboard_dir",
        lambda: sb_dir,
    )
    # Bind a custom reaction.
    bind_result = _RUNNER.invoke(
        app,
        ["soundboard", "bind", "test_pass", "🦾 nailed it"],
        catch_exceptions=False,
    )
    assert bind_result.exit_code == 0
    assert "test_pass" in bind_result.output

    # React should now return the custom reaction.
    react_result = _RUNNER.invoke(
        app, ["soundboard", "react", "test_pass"], catch_exceptions=False
    )
    assert react_result.exit_code == 0
    assert "🦾 nailed it" in react_result.output


def test_cli_bind_with_bell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """bind --bell stores the bell character in bindings.json."""
    sb_dir = tmp_path / ".onmc" / "soundboard"
    monkeypatch.setattr(
        "oh_no_my_claudecode.soundboard.commands._resolve_soundboard_dir",
        lambda: sb_dir,
    )
    result = _RUNNER.invoke(
        app,
        ["soundboard", "bind", "build_break", "💀 rip", "--bell"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "with bell" in result.output
    # Verify the \\a was actually persisted.
    bindings = load_bindings(sb_dir)
    assert bindings["build_break"].endswith("\a")


def test_cli_unbind_restores_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """unbind removes the user override so react falls back to the default."""
    sb_dir = tmp_path / ".onmc" / "soundboard"
    monkeypatch.setattr(
        "oh_no_my_claudecode.soundboard.commands._resolve_soundboard_dir",
        lambda: sb_dir,
    )
    # First bind a custom reaction.
    _RUNNER.invoke(
        app,
        ["soundboard", "bind", "test_pass", "custom override"],
        catch_exceptions=False,
    )
    # Now unbind.
    unbind_result = _RUNNER.invoke(
        app, ["soundboard", "unbind", "test_pass"], catch_exceptions=False
    )
    assert unbind_result.exit_code == 0
    assert "test_pass" in unbind_result.output

    # React should revert to the default.
    react_result = _RUNNER.invoke(
        app, ["soundboard", "react", "test_pass"], catch_exceptions=False
    )
    assert react_result.exit_code == 0
    assert DEFAULTS["test_pass"] in react_result.output


def test_cli_unbind_no_override_is_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """unbind on an event with no override exits cleanly without error."""
    sb_dir = tmp_path / ".onmc" / "soundboard"
    monkeypatch.setattr(
        "oh_no_my_claudecode.soundboard.commands._resolve_soundboard_dir",
        lambda: sb_dir,
    )
    result = _RUNNER.invoke(
        app, ["soundboard", "unbind", "test_pass"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert "nothing to remove" in result.output
