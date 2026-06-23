from importlib.metadata import version

from oh_no_my_claudecode import __version__


def test_runtime_version_matches_installed_package_metadata() -> None:
    assert __version__ == version("oh-no-my-claudecode")
