from importlib.metadata import version

from typer.testing import CliRunner

from oh_no_my_claudecode import __version__
from oh_no_my_claudecode.cli import app

runner = CliRunner()


def test_runtime_version_matches_installed_package_metadata() -> None:
    assert __version__ == version("oh-no-my-claudecode")


def test_version_flag_prints_version_and_exits_zero() -> None:
    """``onmc --version`` prints ``onmc <version>`` and exits 0."""
    result = runner.invoke(app, ["--version"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "onmc" in result.output
    assert __version__ in result.output


def test_short_version_flag_matches_long_flag() -> None:
    """``onmc -V`` behaves identically to ``onmc --version``."""
    result = runner.invoke(app, ["-V"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert __version__ in result.output


def test_no_args_still_shows_help_not_version() -> None:
    """Bare ``onmc`` shows help (no_args_is_help) and does not crash."""
    result = runner.invoke(app, [])
    assert "Usage" in result.output or "commands" in result.output.lower()


def test_subcommand_still_runs_with_root_callback() -> None:
    """Adding the root --version callback must not break subcommands."""
    result = runner.invoke(app, ["commands", "--help"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
