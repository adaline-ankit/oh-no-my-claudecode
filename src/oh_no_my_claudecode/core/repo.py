from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

_log = logging.getLogger(__name__)

_WORKTREE_GIT_TIMEOUT = 30  # seconds


class RepoDiscoveryError(RuntimeError):
    """Raised when no git repository can be found."""


def discover_repo_root(start_path: Path | None = None) -> Path:
    candidate = (start_path or Path.cwd()).resolve()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=candidate,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        current = candidate
        for path in (current, *current.parents):
            if (path / ".git").exists():
                return path
        msg = f"No git repository found from {candidate}"
        raise RepoDiscoveryError(msg) from None
    return Path(result.stdout.strip()).resolve()


def resolve_hooks_dir(repo_root: Path) -> Path:
    """Return the correct git hooks directory for *repo_root*.

    Works for both standard repositories (where `.git` is a directory) and
    linked worktrees (where `.git` is a file pointing elsewhere).  Falls back
    to the conventional ``.git/hooks`` path if the ``git`` binary cannot be
    found or the command fails for any reason.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-path", "hooks"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        hooks_path = Path(result.stdout.strip())
        if not hooks_path.is_absolute():
            hooks_path = repo_root / hooks_path
        return hooks_path.resolve()
    except (OSError, subprocess.CalledProcessError):
        return repo_root / ".git" / "hooks"


def current_branch(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def relative_path(repo_root: Path, path: Path) -> str:
    return path.resolve().relative_to(repo_root).as_posix()


def is_test_path(path: str) -> bool:
    lowered = path.lower()
    filename = Path(path).name.lower()
    return (
        "/tests/" in lowered
        or lowered.startswith("tests/")
        or filename.startswith("test_")
        or filename.endswith("_test.py")
        or filename.endswith(".spec.ts")
        or filename.endswith(".test.ts")
        or filename.endswith(".spec.tsx")
        or filename.endswith(".test.tsx")
        or filename.endswith(".spec.js")
        or filename.endswith(".test.js")
    )


def path_bucket(path: str, *, depth: int = 2) -> str:
    parts = [part for part in Path(path).parent.as_posix().split("/") if part and part != "."]
    if not parts:
        return "."
    return "/".join(parts[:depth])


# ---------------------------------------------------------------------------
# Worktree isolation
# ---------------------------------------------------------------------------


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    timeout: int = _WORKTREE_GIT_TIMEOUT,
) -> tuple[int, str]:
    """Run a git command and return (returncode, stdout+stderr)."""
    try:
        result = subprocess.run(  # noqa: S603
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout + result.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, str(exc)


class WorktreeIsolationProvider:
    """Real git-worktree-backed isolation provider.

    Creates a linked worktree in a temporary directory so the loop's agent
    works on an isolated copy of the repo.  The caller chooses whether teardown
    keeps the worktree for inspection/recovery or removes it with its temporary
    branch.

    Implements the ``IsolationProvider`` protocol from
    ``oh_no_my_claudecode.loop.models``.
    """

    def __init__(self, *, branch_prefix: str = "onmc-iso") -> None:
        self._branch_prefix = branch_prefix
        self._worktree_path: Path | None = None
        self._branch_name: str | None = None
        self._repo_root: Path | None = None

    def setup(self, repo_root: Path) -> Path | None:
        """Create a linked worktree under a temp directory.

        Returns the worktree path on success, ``None`` on failure (the caller
        falls back to in-place execution).
        """
        import secrets as _secrets

        self._repo_root = repo_root
        suffix = _secrets.token_hex(4)
        self._branch_name = f"{self._branch_prefix}-{suffix}"

        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="onmc-wt-"))
        except OSError as exc:
            _log.warning("worktree isolation: failed to create temp dir: %s", exc)
            return None

        worktree_path = tmp_dir / "worktree"
        rc, out = _run_git(
            ["worktree", "add", "-b", self._branch_name, str(worktree_path)],
            cwd=repo_root,
        )
        if rc != 0:
            _log.warning("worktree isolation: git worktree add failed: %s", out.strip())
            # Clean up the temp dir we created.
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

        self._worktree_path = worktree_path
        return worktree_path

    @property
    def branch_name(self) -> str | None:
        """Return recovery branch for current isolated worktree."""
        return self._branch_name

    def teardown(self, worktree_path: Path, *, keep: bool) -> None:
        """Remove the worktree.

        When *keep* is ``True`` we leave the worktree and branch registered for
        inspection or recovery.  When *keep* is ``False`` we remove both.
        """
        repo_root = self._repo_root
        branch = self._branch_name

        if keep:
            return

        # Failure path: remove the directory so no partial changes leak.
        shutil.rmtree(worktree_path, ignore_errors=True)

        if repo_root is not None:
            _run_git(
                ["worktree", "remove", "--force", str(worktree_path)],
                cwd=repo_root,
            )
            _run_git(["worktree", "prune"], cwd=repo_root)

        if branch is not None and repo_root is not None:
            # Delete the temporary branch created for this worktree.
            _run_git(["branch", "-D", branch], cwd=repo_root)

        # Remove the parent temp directory if it still exists.
        parent = worktree_path.parent
        if parent.exists():
            shutil.rmtree(parent, ignore_errors=True)
