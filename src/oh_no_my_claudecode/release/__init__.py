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

Changelog rendering is optionally delegated to `git-cliff <https://git-cliff.org>`_
(a standalone binary, not a pip package) when it is present on ``PATH``:
:func:`git_cliff_available` detects it and :func:`default_cliff_runner` returns
an injectable runner that :func:`draft_release` uses to render the CHANGELOG
entry.  When git-cliff is absent the built-in conventional-commit renderer is
used unchanged, so there is zero regression and no new dependency.
"""

from __future__ import annotations

from oh_no_my_claudecode.release.drafter import (
    Bump,
    CliffRunner,
    ReleaseDraft,
    ReleaseStatus,
    ReleaseValidation,
    all_tags,
    changelog_has_version,
    collect_commits,
    current_version,
    default_cliff_runner,
    draft_release,
    evaluate_release_readiness,
    git_cliff_available,
    validate_release,
    write_release,
)

__all__ = [
    "Bump",
    "CliffRunner",
    "ReleaseDraft",
    "ReleaseStatus",
    "ReleaseValidation",
    "all_tags",
    "changelog_has_version",
    "collect_commits",
    "current_version",
    "default_cliff_runner",
    "draft_release",
    "evaluate_release_readiness",
    "git_cliff_available",
    "validate_release",
    "write_release",
]
