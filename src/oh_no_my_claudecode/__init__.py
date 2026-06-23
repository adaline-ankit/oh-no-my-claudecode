"""oh-no-my-claudecode package."""

from importlib.metadata import PackageNotFoundError, version

from oh_no_my_claudecode.api import OnmcRepo, init

__all__ = ["__version__", "OnmcRepo", "init"]

try:
    __version__ = version("oh-no-my-claudecode")
except PackageNotFoundError:
    __version__ = "0+unknown"
