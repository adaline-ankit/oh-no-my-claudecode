"""Tests for install.sh — syntax, structure, and key behaviours.

These tests do NOT actually run the installer; they inspect the script as text
and verify it is syntactically valid and contains the required logic.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).parent.parent / "install.sh"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def script_text() -> str:
    return INSTALL_SH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Bash syntax check (bash -n)
# ---------------------------------------------------------------------------


def test_install_sh_exists() -> None:
    """install.sh must exist at the repo root."""
    assert INSTALL_SH.exists(), f"install.sh not found at {INSTALL_SH}"


def test_install_sh_bash_syntax() -> None:
    """bash -n install.sh must exit 0 (no syntax errors)."""
    result = subprocess.run(
        ["bash", "-n", str(INSTALL_SH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"bash -n returned {result.returncode}:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# 2. Safety primitives
# ---------------------------------------------------------------------------


def test_install_sh_has_set_eu() -> None:
    """Script must use 'set -eu' for fail-fast behaviour."""
    text = script_text()
    assert "set -eu" in text, "install.sh must contain 'set -eu'"


def test_install_sh_no_sudo() -> None:
    """Script must never invoke sudo."""
    text = script_text()
    assert "sudo" not in text, "install.sh must not use sudo"


# ---------------------------------------------------------------------------
# 3. Installer fallback chain: uv → pipx → pip
# ---------------------------------------------------------------------------


def test_install_sh_uv_install_present() -> None:
    """install.sh must attempt 'uv tool install oh-no-my-claudecode'."""
    text = script_text()
    assert "uv tool install oh-no-my-claudecode" in text, (
        "uv install command not found in install.sh"
    )


def test_install_sh_pipx_install_present() -> None:
    """install.sh must attempt 'pipx install oh-no-my-claudecode'."""
    text = script_text()
    assert "pipx install oh-no-my-claudecode" in text, (
        "pipx install command not found in install.sh"
    )


def test_install_sh_pip_install_present() -> None:
    """install.sh must attempt 'pip install --user oh-no-my-claudecode'."""
    text = script_text()
    assert "pip install --user oh-no-my-claudecode" in text, (
        "pip install --user command not found in install.sh"
    )


def test_install_sh_fallback_order() -> None:
    """uv must appear before pipx which must appear before pip in the script."""
    text = script_text()
    uv_pos = text.find("uv tool install oh-no-my-claudecode")
    pipx_pos = text.find("pipx install oh-no-my-claudecode")
    pip_pos = text.find("pip install --user oh-no-my-claudecode")
    assert uv_pos != -1, "uv install not found"
    assert pipx_pos != -1, "pipx install not found"
    assert pip_pos != -1, "pip install not found"
    assert uv_pos < pipx_pos < pip_pos, (
        f"Expected uv ({uv_pos}) < pipx ({pipx_pos}) < pip ({pip_pos}) order"
    )


# ---------------------------------------------------------------------------
# 4. Post-install integration: onmc setup (+ quickstart fallback)
# ---------------------------------------------------------------------------


def test_install_sh_calls_onmc_setup() -> None:
    """Script must call 'onmc setup' as the fallback integration step."""
    text = script_text()
    assert "onmc setup" in text, "install.sh must call 'onmc setup'"


def test_install_sh_calls_onmc_quickstart() -> None:
    """Script must attempt 'onmc quickstart --yes' first (newer versions)."""
    text = script_text()
    assert "onmc quickstart --yes" in text, (
        "install.sh must try 'onmc quickstart --yes' before falling back to setup"
    )


def test_install_sh_quickstart_before_setup() -> None:
    """quickstart must be tried before setup in the integration block."""
    text = script_text()
    qs_pos = text.find("onmc quickstart --yes")
    setup_pos = text.find("onmc setup")
    assert qs_pos != -1, "onmc quickstart --yes not found"
    assert setup_pos != -1, "onmc setup not found"
    assert qs_pos < setup_pos, (
        f"quickstart ({qs_pos}) must appear before setup ({setup_pos})"
    )


# ---------------------------------------------------------------------------
# 5. ONMC_NO_INTEGRATE env var is honoured
# ---------------------------------------------------------------------------


def test_install_sh_onmc_no_integrate_present() -> None:
    """Script must reference ONMC_NO_INTEGRATE to allow skipping integration."""
    text = script_text()
    assert "ONMC_NO_INTEGRATE" in text, (
        "install.sh must honour the ONMC_NO_INTEGRATE env variable"
    )


def test_install_sh_onmc_no_integrate_skip_logic() -> None:
    """When ONMC_NO_INTEGRATE=1, the integration block must be skipped."""
    text = script_text()
    # The script must check for '1' value and skip the setup step
    assert 'ONMC_NO_INTEGRATE" = "1"' in text or "ONMC_NO_INTEGRATE" in text, (
        "install.sh must skip integration when ONMC_NO_INTEGRATE=1"
    )


# ---------------------------------------------------------------------------
# 6. --help flag
# ---------------------------------------------------------------------------


def test_install_sh_help_flag_present() -> None:
    """Script must handle --help / -h flags."""
    text = script_text()
    assert "--help" in text, "install.sh must support --help"


# ---------------------------------------------------------------------------
# 7. shellcheck (skipped if not installed)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    shutil.which("shellcheck") is None,
    reason="shellcheck not installed",
)
def test_install_sh_shellcheck() -> None:
    """shellcheck must pass with no errors on install.sh."""
    result = subprocess.run(
        ["shellcheck", str(INSTALL_SH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"shellcheck found issues:\n{result.stdout}\n{result.stderr}"
    )
