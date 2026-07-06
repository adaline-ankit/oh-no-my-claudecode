"""Pure helpers for ``onmc share`` — filenames, descriptions, content mode.

Nothing here touches the filesystem, ``gh``, or any service. The command layer
(:mod:`oh_no_my_claudecode.share.commands`) is responsible for actually
producing the file content (via the existing dashboard exporter or the
scorecard renderer) and shelling out to ``gh``. Keeping this module pure lets
the filename/description logic be tested without a repo, a database, or a
network call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

__all__ = [
    "ShareKind",
    "gist_description",
    "snapshot_filename",
]


class ShareKind(StrEnum):
    """What kind of snapshot is being shared."""

    DASHBOARD = "dashboard"
    SCORECARD = "scorecard"


@dataclass(frozen=True)
class _Ext:
    dashboard: str = "html"
    scorecard: str = "md"


_EXTENSIONS = _Ext()


def _extension(kind: ShareKind) -> str:
    if kind is ShareKind.SCORECARD:
        return _EXTENSIONS.scorecard
    return _EXTENSIONS.dashboard


def snapshot_filename(kind: ShareKind, *, now: datetime | None = None) -> str:
    """Build a deterministic, timestamped filename for the snapshot.

    Format: ``onmc-<kind>-<YYYYmmddTHHMMSSZ>.<ext>``. The timestamp is always
    rendered in UTC so filenames are stable regardless of local timezone;
    callers inject *now* for deterministic tests.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    stamp = moment.strftime("%Y%m%dT%H%M%SZ")
    return f"onmc-{kind.value}-{stamp}.{_extension(kind)}"


def gist_description(kind: ShareKind, *, repo_name: str | None = None) -> str:
    """Build the ``gh gist create --desc`` text for *kind*.

    Includes the repo name when known so a user's gist list stays
    identifiable across multiple shared repos.
    """
    label = "dashboard snapshot" if kind is ShareKind.DASHBOARD else "scorecard"
    if repo_name:
        return f"onmc {label} — {repo_name}"
    return f"onmc {label}"
