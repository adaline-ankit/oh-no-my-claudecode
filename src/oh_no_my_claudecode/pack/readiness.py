"""Readiness checks for ``onmc pack`` and ``onmc mission``.

A "ready brain" has been ingested (``last_ingest_at`` is set) and has at least
some repo files indexed (``repo_files`` is non-empty).  When the brain is not
ready, ``pack`` and ``mission`` will still run (they degrade gracefully) but the
context they emit is likely wrong or empty — so callers should surface a loud
warning before proceeding.

``brain_readiness_warnings`` returns a list of human-readable warning strings.
An empty list means the brain is ready.  The function never raises.
"""

from __future__ import annotations

from oh_no_my_claudecode.storage import SQLiteStorage

# Minimum number of repo files below which we consider the index suspiciously
# small.  A single-file repo is fine at 1, but 0 always means "never indexed".
_MIN_REPO_FILES = 1


def brain_readiness_warnings(storage: SQLiteStorage) -> list[str]:
    """Return warning strings describing why the brain may be unready.

    Returns an empty list when the brain looks healthy.  Degrades gracefully if
    any storage call fails — a reader error is treated as "not ready" with its
    own message.

    Parameters
    ----------
    storage:
        Open memory store to inspect.
    """
    warnings: list[str] = []

    # Check 1: has the repo ever been ingested?
    try:
        last_ingest = storage.get_meta("last_ingest_at")
    except Exception:  # noqa: BLE001
        last_ingest = None

    if not last_ingest:
        warnings.append(
            "Brain has never been ingested — run `onmc ingest` first."
            " Context pack will be unreliable or empty."
        )

    # Check 2: is the repo-file index populated?
    try:
        repo_files = storage.list_repo_files()
        file_count = len(repo_files)
    except Exception:  # noqa: BLE001
        file_count = 0

    # Warn about empty index only when ingest timestamp is present (avoid
    # duplicate advice — the "never ingested" warning already covers the empty case).
    if file_count < _MIN_REPO_FILES and last_ingest:
        warnings.append(
            "Repo-file index is empty — re-run `onmc ingest` to index the repository."
            " Context pack may return no files."
        )

    return warnings
