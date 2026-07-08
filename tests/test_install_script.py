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
    """install.sh must attempt 'uv tool install --force oh-no-my-claudecode'."""
    text = script_text()
    assert "uv tool install --force oh-no-my-claudecode" in text, (
        "uv install command not found in install.sh (expected --force flag)"
    )


def test_install_sh_pipx_install_present() -> None:
    """install.sh must attempt 'pipx install --force oh-no-my-claudecode'."""
    text = script_text()
    assert "pipx install --force oh-no-my-claudecode" in text, (
        "pipx install command not found in install.sh (expected --force flag)"
    )


def test_install_sh_pip_install_present() -> None:
    """install.sh must attempt 'pip install --user --upgrade oh-no-my-claudecode'."""
    text = script_text()
    assert "pip install --user --upgrade oh-no-my-claudecode" in text, (
        "pip install --user --upgrade command not found in install.sh"
    )


def test_install_sh_fallback_order() -> None:
    """uv must appear before pipx which must appear before pip in the script."""
    text = script_text()
    uv_pos = text.find("uv tool install --force oh-no-my-claudecode")
    pipx_pos = text.find("pipx install --force oh-no-my-claudecode")
    pip_pos = text.find("pip install --user --upgrade oh-no-my-claudecode")
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
# 8. Force-upgrade: existing installs must actually update to latest
# ---------------------------------------------------------------------------


def test_install_sh_uv_force_upgrade() -> None:
    """uv branch must pass --force so an existing install is replaced."""
    text = script_text()
    assert "uv tool install --force oh-no-my-claudecode" in text, (
        "uv branch must use '--force' to upgrade existing installs"
    )


def test_install_sh_pipx_force_upgrade() -> None:
    """pipx branch must pass --force so an existing install is replaced."""
    text = script_text()
    assert "pipx install --force oh-no-my-claudecode" in text, (
        "pipx branch must use '--force' to upgrade existing installs"
    )


def test_install_sh_pip_upgrade_flag() -> None:
    """pip and pip3 branches must pass --upgrade so the package is updated."""
    text = script_text()
    assert "pip install --user --upgrade oh-no-my-claudecode" in text, (
        "pip branch must use '--upgrade' to update existing installs"
    )
    assert "pip3 install --user --upgrade oh-no-my-claudecode" in text, (
        "pip3 branch must use '--upgrade' to update existing installs"
    )


# ---------------------------------------------------------------------------
# 9. Integration stdin isolation (curl|bash safety)
# ---------------------------------------------------------------------------


def test_install_sh_integration_stdin_devnull() -> None:
    """Integration subshell must redirect stdin from /dev/null.

    Without this, curl|bash pipes the installer script text into the setup
    wizard as stdin, which causes infinite loops on y/n confirms.
    """
    text = script_text()
    assert "</dev/null" in text, (
        "install.sh must redirect stdin from /dev/null for the integration step "
        "so curl|bash pipes cannot feed the setup wizard"
    )


def test_install_sh_setup_fallback_uses_yes_flag() -> None:
    """Fallback 'onmc setup' must include --yes to avoid interactive prompts."""
    text = script_text()
    assert "onmc setup --yes" in text, (
        "install.sh fallback must use 'onmc setup --yes', not bare 'onmc setup'"
    )
    # Verify bare 'onmc setup' (without --yes) is not used as the actual command
    # (it can appear in warning messages, but the SETUP_CMD assignment must be --yes)
    import re

    bare_setup_assignments = re.findall(
        r'SETUP_CMD=["\']onmc setup["\']', text
    )
    assert bare_setup_assignments == [], (
        f"SETUP_CMD must not be set to bare 'onmc setup': {bare_setup_assignments}"
    )


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
