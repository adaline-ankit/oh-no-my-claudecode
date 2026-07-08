"""Tests for ``onmc wrap --managed`` — org hard-lock enforcement.

Coverage (≥7 tests as required)
--------------------------------
1. macOS default managed path detection via monkeypatched sys.platform.
2. Linux default managed path detection.
3. Windows default managed path detection.
4. --managed-path override (CLI + pure function).
5. merge_managed_hooks adds onmc hooks and preserves other managed keys (temp file).
6. strip_managed_hooks removes only onmc hooks, leaving other keys intact (temp file).
7. Not-writable path → graceful message + manual JSON printed, no crash, exit 1.
8. wrap status --json reports managed_enforcement + managed_path correctly.
9. unwrap --managed removes only onmc entries from managed-settings (temp file).
10. managed_hooks_present returns True after merge and False after strip.
11. Existing project-scoped wrap unchanged when --managed used (round-trip parity).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner

from oh_no_my_claudecode.command_registry import register_feature_commands
from oh_no_my_claudecode.wrap.managed import (
    default_managed_path,
    managed_hooks_present,
    manual_install_json,
    merge_managed_hooks,
    strip_managed_hooks,
)

runner = CliRunner()


def _fresh_app():  # type: ignore[no-untyped-def]
    """Build a fresh typer app with all features registered."""
    import typer

    app = typer.Typer()

    @app.command("__sentinel__")
    def _sentinel() -> None:  # pragma: no cover
        ...

    register_feature_commands(app)
    return app


# ---------------------------------------------------------------------------
# 1-3. Default managed path per OS
# ---------------------------------------------------------------------------


def test_default_managed_path_macos() -> None:
    """macOS: /Library/Application Support/ClaudeCode/managed-settings.json."""
    with patch.object(sys, "platform", "darwin"):
        p = default_managed_path()
    assert str(p) == "/Library/Application Support/ClaudeCode/managed-settings.json"


def test_default_managed_path_linux() -> None:
    """Linux: /etc/claude-code/managed-settings.json."""
    with patch.object(sys, "platform", "linux"):
        p = default_managed_path()
    assert str(p) == "/etc/claude-code/managed-settings.json"


def test_default_managed_path_windows() -> None:
    """Windows: C:\\ProgramData\\ClaudeCode\\managed-settings.json."""
    with patch.object(sys, "platform", "win32"):
        p = default_managed_path()
    assert str(p) == r"C:\ProgramData\ClaudeCode\managed-settings.json"


# ---------------------------------------------------------------------------
# 4. --managed-path override
# ---------------------------------------------------------------------------


def test_managed_path_override_writes_to_custom_path(tmp_path: Path) -> None:
    """--managed-path directs the install to a custom path (no system-path write)."""
    custom = tmp_path / "custom" / "managed.json"
    app = _fresh_app()
    result = runner.invoke(app, ["wrap", "--managed", "--managed-path", str(custom)])
    assert result.exit_code == 0, result.output
    assert custom.is_file(), "Custom managed-settings file not created"
    data = json.loads(custom.read_text())
    assert managed_hooks_present(data), "onmc hooks missing from custom path"


# ---------------------------------------------------------------------------
# 5. merge adds onmc hooks preserving other managed keys (temp file)
# ---------------------------------------------------------------------------


def test_merge_adds_hooks_preserves_other_keys(tmp_path: Path) -> None:
    """merge_managed_hooks merges onmc hooks while keeping unrelated managed keys."""
    original: dict[str, Any] = {
        "allowedTools": ["Bash", "Read"],
        "theme": "dark",
        "hooks": {
            "SessionStart": [
                {"matcher": "", "hooks": [{"type": "command", "command": "echo hello"}]}
            ]
        },
    }
    merged = merge_managed_hooks(original)

    # onmc hooks added
    assert managed_hooks_present(merged)
    # original keys preserved
    assert merged["allowedTools"] == ["Bash", "Read"]
    assert merged["theme"] == "dark"
    # existing SessionStart hook preserved
    assert any(
        h.get("command") == "echo hello"
        for entry in merged.get("hooks", {}).get("SessionStart", [])
        for h in entry.get("hooks", [])
    )

    # Write to temp file and verify round-trip
    managed_file = tmp_path / "managed-settings.json"
    managed_file.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    from_disk = json.loads(managed_file.read_text())
    assert managed_hooks_present(from_disk)
    assert from_disk["theme"] == "dark"


# ---------------------------------------------------------------------------
# 6. strip removes only onmc keys leaving other keys intact (temp file)
# ---------------------------------------------------------------------------


def test_strip_removes_only_onmc_hooks(tmp_path: Path) -> None:
    """strip_managed_hooks removes onmc entries and leaves unrelated keys intact."""
    existing: dict[str, Any] = {
        "allowedTools": ["Bash"],
        "hooks": {
            "SessionStart": [
                {"matcher": "", "hooks": [{"type": "command", "command": "echo hi"}]}
            ]
        },
    }
    merged = merge_managed_hooks(existing)
    assert managed_hooks_present(merged)

    stripped = strip_managed_hooks(merged)

    assert not managed_hooks_present(stripped)
    assert stripped["allowedTools"] == ["Bash"]
    # SessionStart hook preserved
    assert "echo hi" in json.dumps(stripped)
    # onmc commands gone
    assert "task-intercept" not in json.dumps(stripped)
    assert "prompt-router" not in json.dumps(stripped)

    # Write to temp file and verify
    managed_file = tmp_path / "managed-settings.json"
    managed_file.write_text(json.dumps(stripped, indent=2), encoding="utf-8")
    from_disk = json.loads(managed_file.read_text())
    assert not managed_hooks_present(from_disk)
    assert "echo hi" in json.dumps(from_disk)


# ---------------------------------------------------------------------------
# 7. Not-writable path → graceful message + manual JSON, no crash, exit 1
# ---------------------------------------------------------------------------


def test_not_writable_path_prints_manual_json_no_crash(tmp_path: Path) -> None:
    """When managed-settings path is not writable, exit 1 + print manual JSON."""
    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o555)  # read+execute, no write

    managed_file = readonly_dir / "managed-settings.json"
    app = _fresh_app()
    result = runner.invoke(app, ["wrap", "--managed", "--managed-path", str(managed_file)])

    # Must exit 1 (not crash with unhandled exception)
    assert result.exit_code == 1
    # Error message must mention the path and permission
    assert "Permission denied" in result.stderr or "Permission denied" in result.output
    # Manual JSON must be printed (stdout so the user can copy it)
    combined = result.output + result.stderr
    assert "task-intercept" in combined or "hooks" in combined

    # Cleanup
    readonly_dir.chmod(0o755)


def test_not_writable_path_manual_json_is_valid(tmp_path: Path) -> None:
    """The manual JSON printed on permission error is valid parseable JSON."""
    json_fragment = manual_install_json()
    parsed = json.loads(json_fragment)
    assert managed_hooks_present(parsed)


# ---------------------------------------------------------------------------
# 8. wrap status --json reports managed_enforcement and managed_path
# ---------------------------------------------------------------------------


def test_status_json_reports_managed_presence(tmp_path: Path) -> None:
    """wrap status --json includes managed_enforcement=True when hooks are present."""
    managed_file = tmp_path / "managed.json"
    # Install hooks
    app = _fresh_app()
    runner.invoke(app, ["wrap", "--managed", "--managed-path", str(managed_file)])
    assert managed_file.is_file()

    # Now check status — need a git repo for the project-level parts to work
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)

    result = runner.invoke(
        app,
        ["wrap", "status", "--json", "--managed-path", str(managed_file)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["managed_enforcement"] is True
    assert data["managed_path"] == str(managed_file)


def test_status_json_reports_managed_absent(tmp_path: Path) -> None:
    """wrap status --json includes managed_enforcement=False when hooks absent."""
    managed_file = tmp_path / "nonexistent.json"
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)

    app = _fresh_app()
    result = runner.invoke(
        app,
        ["wrap", "status", "--json", "--managed-path", str(managed_file)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["managed_enforcement"] is False
    assert data["managed_path"] == str(managed_file)


# ---------------------------------------------------------------------------
# 9. unwrap --managed removes onmc entries, leaving other keys intact
# ---------------------------------------------------------------------------


def test_unwrap_managed_removes_only_onmc_entries(tmp_path: Path) -> None:
    """unwrap --managed strips onmc hooks from managed-settings, preserves others."""
    managed_file = tmp_path / "managed.json"
    # Pre-populate with onmc hooks + unrelated key.
    original: dict[str, Any] = {"allowedTools": ["Bash"]}
    merged = merge_managed_hooks(original)
    managed_file.write_text(json.dumps(merged, indent=2), encoding="utf-8")

    app = _fresh_app()
    result = runner.invoke(app, ["unwrap", "--managed", "--managed-path", str(managed_file)])
    assert result.exit_code == 0, result.output

    after = json.loads(managed_file.read_text())
    assert not managed_hooks_present(after), "onmc hooks should be removed"
    assert after.get("allowedTools") == ["Bash"], "unrelated key should be preserved"


# ---------------------------------------------------------------------------
# 10. managed_hooks_present True after merge, False after strip
# ---------------------------------------------------------------------------


def test_managed_hooks_present_round_trip() -> None:
    """managed_hooks_present reports correctly after merge and strip."""
    empty: dict[str, Any] = {}
    assert not managed_hooks_present(empty)

    merged = merge_managed_hooks(empty)
    assert managed_hooks_present(merged)

    stripped = strip_managed_hooks(merged)
    assert not managed_hooks_present(stripped)


def test_merge_is_idempotent() -> None:
    """Calling merge_managed_hooks twice produces the same result as once."""
    base: dict[str, Any] = {}
    once = merge_managed_hooks(base)
    twice = merge_managed_hooks(once)
    assert once == twice


# ---------------------------------------------------------------------------
# 11. Existing project-scoped wrap unchanged when --managed used
# ---------------------------------------------------------------------------


def test_managed_install_does_not_touch_project_settings(tmp_path: Path) -> None:
    """--managed writes only to the managed path; project settings.json untouched."""
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)

    project_settings = tmp_path / ".claude" / "settings.json"
    project_settings.parent.mkdir(parents=True, exist_ok=True)
    original_content = json.dumps({"hooks": {}}, indent=2, sort_keys=True) + "\n"
    project_settings.write_text(original_content, encoding="utf-8")

    managed_file = tmp_path / "managed.json"
    app = _fresh_app()
    result = runner.invoke(app, ["wrap", "--managed", "--managed-path", str(managed_file)])
    assert result.exit_code == 0, result.output

    # Project settings.json must be byte-identical
    assert project_settings.read_text(encoding="utf-8") == original_content
    # Managed file must now contain the hooks
    assert managed_file.is_file()
    assert managed_hooks_present(json.loads(managed_file.read_text()))
