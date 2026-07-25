"""Deterministic, offline release drafter.

Given the project's current version and a list of conventional-commit subjects
since the last tag, :func:`draft_release` classifies each subject, computes the
next semantic version, and groups the commits into a CHANGELOG entry that
matches the repo's existing style.

Everything in this module is pure: ``draft_release`` takes the commit log,
date, and current version as arguments (no git, no network, no LLM) so it is
fully deterministic and unit-testable.  The :func:`collect_commits` and
:func:`current_version` helpers exist for the CLI to gather those inputs from
the live repo; they are intentionally *not* used by the pure drafter.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Bump = Literal["major", "minor", "patch"]

# A cliff-runner produces a rendered CHANGELOG section for the *next* release.
# It is injected so tests never shell out to a real binary: ``(repo_root,
# next_version) -> changelog_entry_text``. ``None`` / empty return means the
# caller should fall back to the built-in conventional-commit renderer.
CliffRunner = Callable[[Path, str], "str | None"]

# The external git-cliff binary is looked up on PATH (it is NOT a pip package).
_GIT_CLIFF_BINARY = "git-cliff"

# Conventional-commit type -> CHANGELOG section heading. The order of this dict
# is the order sections appear in a rendered entry.
_SECTION_FOR_TYPE: dict[str, str] = {
    "feat": "Added",
    "fix": "Fixed",
}
_OTHER_SECTION = "Changed"

# Section render order (every section that has at least one entry is rendered).
_SECTION_ORDER: tuple[str, ...] = ("Added", "Changed", "Fixed")

# `type(scope)!: subject` or `type: subject`.
_HEADER_RE = re.compile(
    r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<subject>.+)$"
)
_BREAKING_RE = re.compile(r"BREAKING[ -]CHANGE", re.IGNORECASE)


@dataclass
class ReleaseDraft:
    """The drafted next release.

    Attributes
    ----------
    current_version:
        The version currently declared in ``pyproject.toml``.
    next_version:
        The computed next version after applying *bump*.
    bump:
        The semver bump level implied by the commits (``"major"``,
        ``"minor"``, or ``"patch"``).
    changelog_entry:
        The rendered CHANGELOG entry block (heading + grouped sections),
        matching the repo's existing format.
    commits_by_type:
        Commits grouped by CHANGELOG section heading (e.g. ``"Added"``),
        preserving input order within each section.
    """

    current_version: str
    next_version: str
    bump: Bump
    changelog_entry: str
    commits_by_type: dict[str, list[str]] = field(default_factory=dict)


ReleaseStatus = Literal[
    "ready-to-tag",
    "already-released",
    "no-changelog-entry",
    "regression",
]


@dataclass(frozen=True)
class ReleaseValidation:
    """Offline pre-publish check of the release contract.

    Mirrors the CI ``release-contract`` job (tag ⇔ pyproject alignment) but is
    runnable locally *before* a tag is pushed, so version/tag drift is caught
    at the desk instead of in the publish pipeline.  Pure and deterministic:
    :func:`evaluate_release_readiness` takes the version, the existing tags,
    and the CHANGELOG text as inputs — no git, network, or LLM.

    Attributes
    ----------
    current_version:
        The version declared in ``pyproject.toml``.
    version_tag:
        The tag that *would* release this version (``f"v{current_version}"``).
    last_tag:
        The most recent ``vX.Y.Z`` tag, or ``None`` when the repo has none.
    version_tag_exists:
        Whether *version_tag* already exists (i.e. this version was released).
    changelog_has_entry:
        Whether ``CHANGELOG.md`` has a ``## [current_version]`` heading.
    status:
        The single most-important verdict (see :data:`ReleaseStatus`).
    ready:
        ``True`` only when it is safe to cut ``version_tag`` right now.
    issues:
        Blocking problems (empty when *ready*).
    notes:
        Non-blocking, informational lines (e.g. the exact tag command).
    """

    current_version: str
    version_tag: str
    last_tag: str | None
    version_tag_exists: bool
    changelog_has_entry: bool
    status: ReleaseStatus
    ready: bool
    issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def changelog_has_version(changelog_text: str, version: str) -> bool:
    """True when ``CHANGELOG.md`` has a ``## [<version>]`` heading."""
    pattern = re.compile(rf"^## \[{re.escape(version)}\]", re.MULTILINE)
    return pattern.search(changelog_text) is not None


def evaluate_release_readiness(
    *,
    current_version: str,
    existing_tags: list[str],
    changelog_text: str,
    last_tag: str | None,
) -> ReleaseValidation:
    """Classify release readiness from injected inputs (pure, offline).

    Decision order (first match wins):

    1. ``regression`` — the pyproject version is *older* than the last tag.
    2. ``already-released`` — ``v{version}`` is already a tag.
    3. ``no-changelog-entry`` — no ``## [version]`` section in CHANGELOG.md.
    4. ``ready-to-tag`` — version bumped, no tag yet, CHANGELOG entry present.
    """
    version_tag = f"v{current_version}"
    version_tag_exists = version_tag in set(existing_tags)
    has_entry = changelog_has_version(changelog_text, current_version)
    issues: list[str] = []
    notes: list[str] = []

    last_tag_version = last_tag[1:] if last_tag and last_tag.startswith("v") else last_tag
    is_regression = (
        last_tag_version is not None
        and not version_tag_exists
        and _parse_version(current_version) < _parse_version(last_tag_version)
    )

    status: ReleaseStatus
    if is_regression:
        status = "regression"
        issues.append(
            f"pyproject version {current_version} is older than the last tag "
            f"{last_tag}. Bump the version forward before releasing."
        )
    elif version_tag_exists:
        status = "already-released"
        issues.append(
            f"{version_tag} is already tagged — version {current_version} was "
            "released. Run `onmc release --write` to bump before tagging again."
        )
    elif not has_entry:
        status = "no-changelog-entry"
        issues.append(
            f"CHANGELOG.md has no `## [{current_version}]` entry. "
            "Run `onmc release --write` to add it before tagging."
        )
    else:
        status = "ready-to-tag"
        drift = f" (main is ahead of the last tag {last_tag})" if last_tag else ""
        notes.append(
            f"Ready to release {version_tag}{drift}. To publish:\n"
            f"    git tag {version_tag} && git push origin {version_tag}"
        )

    return ReleaseValidation(
        current_version=current_version,
        version_tag=version_tag,
        last_tag=last_tag,
        version_tag_exists=version_tag_exists,
        changelog_has_entry=has_entry,
        status=status,
        ready=status == "ready-to-tag",
        issues=issues,
        notes=notes,
    )


def all_tags(repo_root: Path) -> list[str]:
    """Return all ``vX.Y.Z`` tags in the repo (unordered). Empty on git failure."""
    try:
        result = subprocess.run(
            ["git", "tag", "--list", "v*"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def validate_release(repo_root: Path) -> ReleaseValidation:
    """Wire the live repo into :func:`evaluate_release_readiness`.

    Reads the current version from ``pyproject.toml``, the existing tags and
    last reachable tag from git, and the ``CHANGELOG.md`` text.  Offline; never
    touches the network.

    Raises
    ------
    FileNotFoundError
        When ``pyproject.toml`` does not exist.
    ValueError
        When the ``[project] version`` key is absent.
    """
    version = current_version(repo_root)
    changelog = repo_root / "CHANGELOG.md"
    changelog_text = changelog.read_text(encoding="utf-8") if changelog.exists() else ""
    return evaluate_release_readiness(
        current_version=version,
        existing_tags=all_tags(repo_root),
        changelog_text=changelog_text,
        last_tag=_last_tag(repo_root),
    )


def _parse_version(version: str) -> tuple[int, int, int]:
    """Parse ``"X.Y.Z"`` into an ``(major, minor, patch)`` tuple.

    Any pre-release / build suffix on the patch component is dropped (e.g.
    ``"0.5.0rc1"`` -> ``(0, 5, 0)``) so the next stable version is computed.
    """
    match = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        msg = f"Cannot parse version {version!r} as X.Y.Z."
        raise ValueError(msg)
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _bump_for_subject(subject: str, body: str = "") -> Bump:
    """Classify a single conventional-commit message into a bump level."""
    header = subject.strip()
    if _BREAKING_RE.search(header) or _BREAKING_RE.search(body):
        return "major"
    match = _HEADER_RE.match(header)
    if match is None:
        # Not a conventional commit — treat conservatively as a patch.
        return "patch"
    if match.group("bang"):
        return "major"
    commit_type = match.group("type").lower()
    if commit_type == "feat":
        return "minor"
    return "patch"


def _section_for_subject(subject: str) -> str:
    """Return the CHANGELOG section heading for a conventional-commit subject."""
    match = _HEADER_RE.match(subject.strip())
    if match is None:
        return _OTHER_SECTION
    if match.group("bang") or _BREAKING_RE.search(subject):
        # Breaking changes are still grouped by their declared type's section.
        commit_type = match.group("type").lower()
        return _SECTION_FOR_TYPE.get(commit_type, _OTHER_SECTION)
    commit_type = match.group("type").lower()
    return _SECTION_FOR_TYPE.get(commit_type, _OTHER_SECTION)


def _clean_subject(subject: str) -> str:
    """Strip the conventional-commit prefix, leaving a human-readable summary.

    ``"feat(loop): add resume flag"`` -> ``"add resume flag"``.  Non-conforming
    subjects are returned unchanged (trimmed).
    """
    match = _HEADER_RE.match(subject.strip())
    if match is None:
        return subject.strip()
    return match.group("subject").strip()


def _apply_bump(version: tuple[int, int, int], bump: Bump) -> tuple[int, int, int]:
    major, minor, patch = version
    if bump == "major":
        return major + 1, 0, 0
    if bump == "minor":
        return major, minor + 1, 0
    return major, minor, patch + 1


def _highest_bump(bumps: list[Bump]) -> Bump:
    """Return the strongest bump in *bumps* (major > minor > patch)."""
    if "major" in bumps:
        return "major"
    if "minor" in bumps:
        return "minor"
    return "patch"


def _is_release_chore(subject: str) -> bool:
    """True for ``chore(release): ...`` commits, which are skipped from drafts."""
    match = _HEADER_RE.match(subject.strip())
    if match is None:
        return False
    return match.group("type").lower() == "chore" and (match.group("scope") or "") == "release"


def draft_release(
    *,
    current_version: str,
    commits: list[str],
    date: str,
    cliff_runner: CliffRunner | None = None,
    repo_root: Path | None = None,
) -> ReleaseDraft:
    """Draft the next release from conventional-commit subjects.

    Pure and deterministic: the commit log, *date*, and *current_version* are
    all injected, so the same inputs always produce the same draft (no git,
    network, or LLM access).

    Version bump and grouped ``commits_by_type`` are always computed from the
    injected *commits* — that logic never changes.  Only the rendered
    ``changelog_entry`` can optionally be produced by git-cliff: when
    *cliff_runner* is provided and it returns a non-empty string for the
    computed *next_version*, that text becomes ``changelog_entry``.  If the
    runner is absent, returns ``None``/empty, or raises, the built-in
    conventional-commit renderer is used instead — a strict superset with zero
    regression when git-cliff is unavailable.

    Parameters
    ----------
    current_version:
        The version currently in ``pyproject.toml`` (``"X.Y.Z"``).
    commits:
        Conventional-commit subject lines since the last tag (newest first or
        oldest first — order is preserved within sections).  ``chore(release):``
        commits are ignored.  May be empty.
    date:
        The release date as ``"YYYY-MM-DD"`` for the CHANGELOG heading.
    cliff_runner:
        Optional injected callable ``(repo_root, next_version) -> str | None``
        that renders the CHANGELOG section (e.g. a git-cliff wrapper).  When
        ``None`` (default) or when it yields nothing/errors, the built-in
        renderer is used.  Injected so tests never shell out to a real binary.
    repo_root:
        Repo root passed through to *cliff_runner*.  Only consulted when a
        runner is supplied.

    Returns
    -------
    ReleaseDraft
        The computed bump, next version, grouped commits, and rendered
        CHANGELOG entry.
    """
    meaningful = [c.strip() for c in commits if c.strip() and not _is_release_chore(c)]

    bumps: list[Bump] = [_bump_for_subject(c) for c in meaningful]
    bump: Bump = _highest_bump(bumps) if bumps else "patch"

    current_tuple = _parse_version(current_version)
    next_tuple = _apply_bump(current_tuple, bump)
    next_version = ".".join(str(part) for part in next_tuple)

    commits_by_type: dict[str, list[str]] = {}
    for subject in meaningful:
        section = _section_for_subject(subject)
        commits_by_type.setdefault(section, []).append(_clean_subject(subject))

    changelog_entry = _changelog_via_cliff(
        cliff_runner=cliff_runner,
        repo_root=repo_root,
        next_version=next_version,
    )
    if changelog_entry is None:
        changelog_entry = _render_entry(
            version=next_version,
            date=date,
            commits_by_type=commits_by_type,
        )

    return ReleaseDraft(
        current_version=current_version,
        next_version=next_version,
        bump=bump,
        changelog_entry=changelog_entry,
        commits_by_type=commits_by_type,
    )


def _changelog_via_cliff(
    *,
    cliff_runner: CliffRunner | None,
    repo_root: Path | None,
    next_version: str,
) -> str | None:
    """Return a git-cliff-rendered entry, or ``None`` to signal fallback.

    Any missing runner, empty/whitespace output, or runner exception yields
    ``None`` so the caller falls back to the built-in renderer — the git-cliff
    path can never regress the deterministic default.
    """
    if cliff_runner is None:
        return None
    root = repo_root if repo_root is not None else Path.cwd()
    try:
        rendered = cliff_runner(root, next_version)
    except Exception:  # noqa: BLE001 — git-cliff must never break the draft.
        return None
    if not rendered or not rendered.strip():
        return None
    return rendered if rendered.endswith("\n") else rendered + "\n"


def _render_entry(
    *,
    version: str,
    date: str,
    commits_by_type: dict[str, list[str]],
) -> str:
    """Render a CHANGELOG entry block matching the repo's existing format.

    Format (mirrors ``CHANGELOG.md``)::

        ## [X.Y.Z] — YYYY-MM-DD

        ### Added

        - subject
    """
    lines: list[str] = [f"## [{version}] — {date}"]
    has_any = any(commits_by_type.get(section) for section in _SECTION_ORDER)
    if not has_any:
        lines.extend(["", "_No notable changes._"])
        return "\n".join(lines) + "\n"

    for section in _SECTION_ORDER:
        entries = commits_by_type.get(section)
        if not entries:
            continue
        lines.extend(["", f"### {section}", ""])
        lines.extend(f"- {entry}" for entry in entries)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Live-repo helpers (used by the CLI, NOT by the pure drafter or its tests)
# ---------------------------------------------------------------------------


def git_cliff_available() -> bool:
    """True when the external ``git-cliff`` binary is on ``PATH``.

    git-cliff is a standalone Rust binary, not a pip package, so availability
    is a pure PATH lookup — no import, no pip dependency.
    """
    return shutil.which(_GIT_CLIFF_BINARY) is not None


def _run_git_cliff(repo_root: Path, next_version: str) -> str | None:
    """Default cliff-runner: shell the real ``git-cliff`` binary.

    Renders only the *unreleased* section, tagged as *next_version*, so the
    output slots into ``CHANGELOG.md`` the same way the built-in renderer's
    entry does.  Returns ``None`` on any failure (binary missing, non-zero
    exit, empty output) so the caller falls back to the built-in renderer.

    This helper is intentionally NOT exercised by the offline test suite — it
    is the only place that shells a real binary, and tests inject their own
    runner instead.
    """
    binary = shutil.which(_GIT_CLIFF_BINARY)
    if binary is None:
        return None
    try:
        result = subprocess.run(
            [binary, "--unreleased", "--strip", "all", "--tag", next_version],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    return output or None


def default_cliff_runner() -> CliffRunner | None:
    """Return the real git-cliff runner when the binary is present, else ``None``.

    The CLI uses this to opt into git-cliff transparently: when git-cliff is
    installed the returned runner is passed to :func:`draft_release`; otherwise
    the drafter falls back to its built-in conventional-commit renderer.
    """
    if not git_cliff_available():
        return None
    return _run_git_cliff


def current_version(repo_root: Path) -> str:
    """Read ``version = "X.Y.Z"`` from ``<repo_root>/pyproject.toml``.

    Raises
    ------
    FileNotFoundError
        When ``pyproject.toml`` does not exist.
    ValueError
        When the ``[project] version`` key is absent.
    """
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        msg = f"{pyproject} not found."
        raise FileNotFoundError(msg)
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(version, str) or not version:
        msg = "No [project] version found in pyproject.toml."
        raise ValueError(msg)
    return version


def _last_tag(repo_root: Path) -> str | None:
    """Return the most recent ``vX.Y.Z`` tag reachable from HEAD, or ``None``."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v*"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    tag = result.stdout.strip()
    return tag or None


def collect_commits(repo_root: Path) -> list[str]:
    """Collect conventional-commit subjects since the last ``vX.Y.Z`` tag.

    When no tag exists, collects every commit subject.  Returns subjects newest
    first.  Returns an empty list on any git failure (e.g. not a git repo).
    """
    tag = _last_tag(repo_root)
    rev_range = f"{tag}..HEAD" if tag else "HEAD"
    try:
        result = subprocess.run(
            ["git", "log", "--no-merges", "--pretty=format:%s", rev_range],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


_UNRELEASED_RE = re.compile(r"^## \[Unreleased\]\s*$", re.MULTILINE)
_VERSION_LINE_RE = re.compile(r'^(version\s*=\s*)"[^"]*"', re.MULTILINE)


def write_release(repo_root: Path, draft: ReleaseDraft) -> tuple[Path, Path]:
    """Apply *draft* to ``pyproject.toml`` and ``CHANGELOG.md`` in place.

    - Bumps the ``[project] version`` to ``draft.next_version``.
    - Prepends ``draft.changelog_entry`` immediately under the ``[Unreleased]``
      heading in ``CHANGELOG.md`` (the ``[Unreleased]`` stub is preserved).

    Returns the ``(pyproject_path, changelog_path)`` pair that was edited.

    Raises
    ------
    FileNotFoundError
        When either file is missing.
    ValueError
        When the expected anchors (version line / ``[Unreleased]`` heading) are
        absent.
    """
    pyproject = repo_root / "pyproject.toml"
    changelog = repo_root / "CHANGELOG.md"
    if not pyproject.exists():
        msg = f"{pyproject} not found."
        raise FileNotFoundError(msg)
    if not changelog.exists():
        msg = f"{changelog} not found."
        raise FileNotFoundError(msg)

    pyproject_text = pyproject.read_text(encoding="utf-8")
    new_pyproject, count = _VERSION_LINE_RE.subn(
        rf'\1"{draft.next_version}"', pyproject_text, count=1
    )
    if count == 0:
        msg = 'No `version = "..."` line found in pyproject.toml.'
        raise ValueError(msg)
    pyproject.write_text(new_pyproject, encoding="utf-8")

    changelog_text = changelog.read_text(encoding="utf-8")
    match = _UNRELEASED_RE.search(changelog_text)
    if match is None:
        msg = "No `## [Unreleased]` heading found in CHANGELOG.md."
        raise ValueError(msg)
    head = changelog_text[: match.end()]
    tail = changelog_text[match.end() :].lstrip("\n")
    entry = draft.changelog_entry.rstrip("\n")
    new_changelog = f"{head}\n\n{entry}\n\n{tail}"
    changelog.write_text(new_changelog, encoding="utf-8")

    return pyproject, changelog
