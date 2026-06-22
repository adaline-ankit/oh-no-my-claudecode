"""Remote-source acquisition for cross-repo federation.

Supports shallow-cloning a remote git repository and pulling its
``.agent-memory/`` export into the local brain.  The clone step is
intentionally injectable (``_clone_fn`` parameter) so tests can run offline
without any network access.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oh_no_my_claudecode.federation.pull import PullResult
    from oh_no_my_claudecode.storage import SQLiteStorage

# ---------------------------------------------------------------------------
# URL detection
# ---------------------------------------------------------------------------

_GIT_URL_PREFIXES = ("http://", "https://", "git@", "ssh://")


def is_git_url(source: str) -> bool:
    """Return *True* when *source* looks like a remote git URL.

    Recognised forms:
    - ``https://github.com/org/repo``
    - ``http://github.com/org/repo``
    - ``git@github.com:org/repo.git``
    - ``ssh://git@github.com/org/repo.git``
    - Any string ending with ``.git`` (catches edge cases like bare-clone URLs)
    """
    if any(source.startswith(prefix) for prefix in _GIT_URL_PREFIXES):
        return True
    return source.endswith(".git")


# ---------------------------------------------------------------------------
# Label derivation from URL
# ---------------------------------------------------------------------------


def repo_label_from_url(git_url: str) -> str:
    """Derive a short repo label from a git URL.

    Examples::

        https://github.com/org/my-repo      → "my-repo"
        git@github.com:org/my-repo.git      → "my-repo"
        ssh://git@github.com/org/my-repo    → "my-repo"
        https://github.com/org/repo.git     → "repo"

    Falls back to the raw URL string when no path segment can be extracted.
    """
    # Strip trailing slashes and .git suffix.
    cleaned = git_url.rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[: -len(".git")]

    # For SCP-style git@host:path, normalise the colon separator.
    if ":" in cleaned and not cleaned.startswith(("http://", "https://", "ssh://")):
        # git@github.com:org/repo  →  org/repo
        cleaned = cleaned.split(":", 1)[-1]

    # Take the last non-empty path segment.
    last_segment = cleaned.rstrip("/").split("/")[-1]
    return last_segment if last_segment else git_url


# ---------------------------------------------------------------------------
# Clone helper
# ---------------------------------------------------------------------------

_DEFAULT_CLONE_TIMEOUT = 120  # seconds


def _default_clone(git_url: str, dest: Path, ref: str | None) -> None:
    """Shallow-clone *git_url* into *dest* using ``git clone --depth 1``.

    When *ref* is given, ``--branch <ref>`` is added so a specific
    branch or tag is checked out.

    Raises
    ------
    RuntimeError
        When ``git clone`` exits non-zero, with stderr included in the message.
    """
    cmd = ["git", "clone", "--depth", "1"]
    if ref:
        cmd += ["--branch", ref]
    cmd += [git_url, str(dest)]

    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_CLONE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        msg = f"git clone timed out after {_DEFAULT_CLONE_TIMEOUT}s for {git_url!r}"
        raise RuntimeError(msg) from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        msg = f"git clone failed for {git_url!r}: {stderr}"
        raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

CloneFn = Callable[[str, Path, str | None], None]


def clone_and_pull(
    storage: SQLiteStorage,
    git_url: str,
    *,
    ref: str | None = None,
    repo_label: str | None = None,
    _clone_fn: CloneFn | None = None,
) -> PullResult:
    """Shallow-clone *git_url*, import its ``.agent-memory/``, then remove the clone.

    Parameters
    ----------
    storage:
        The local brain's initialised ``SQLiteStorage`` instance.
    git_url:
        Remote git URL (https, http, git@, or ssh://).
    ref:
        Optional branch, tag, or commit-ish to clone.  When *None* the
        remote's default branch is used.
    repo_label:
        Override the short label used for the ``federated:<label>`` tag.
        When *None* the label is derived from *git_url* via
        :func:`repo_label_from_url`.
    _clone_fn:
        Injectable clone callable for testing (signature:
        ``(url: str, dest: Path, ref: str | None) -> None``).
        Defaults to :func:`_default_clone`.

    Returns
    -------
    PullResult
        Summary counts: how many memories were imported vs. skipped.

    Raises
    ------
    RuntimeError
        When the clone step fails (non-zero git exit, timeout).
    FileNotFoundError
        When the cloned repo does not contain a valid ``.agent-memory/`` export.
    """
    from oh_no_my_claudecode.federation.pull import pull_memories

    clone_fn: CloneFn = _clone_fn if _clone_fn is not None else _default_clone
    resolved_label = repo_label or repo_label_from_url(git_url)

    tmp_dir = Path(tempfile.mkdtemp(prefix="onmc-pull-"))
    try:
        clone_fn(git_url, tmp_dir, ref)
        return pull_memories(storage, tmp_dir, repo_label=resolved_label)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
