"""Draft the next release from conventional-commit history.

This package classifies conventional-commit subjects since the last tag into a
semantic-version bump (``feat`` -> minor, ``fix`` -> patch, ``!`` / BREAKING ->
major, everything else -> patch), computes the next version, and renders a
CHANGELOG entry that matches the repo's existing style.

The core :func:`draft_release` is pure and deterministic — the commit log,
date, and current version are injected, so it never touches git, the network,
or an LLM.  The :func:`collect_commits`, :func:`current_version`, and
:func:`write_release` helpers wire the drafter to the live repo for the CLI.
No schema migration is involved.
"""

from __future__ import annotations

from oh_no_my_claudecode.release.drafter import (
    Bump,
    ReleaseDraft,
    collect_commits,
    current_version,
    draft_release,
    write_release,
)

__all__ = [
    "Bump",
    "ReleaseDraft",
    "collect_commits",
    "current_version",
    "draft_release",
    "write_release",
]
