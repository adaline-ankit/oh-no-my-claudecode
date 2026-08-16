"""Default coverage-backed independent verifier for the false-green seam.

The completion gate is fail-closed: with no independent verifier configured,
every run is ungraded and can never report verified. This module supplies the
default grader — it reads the standard ``coverage json`` report (produced by
running the verifier suite with coverage, e.g. ``pytest --cov --cov-report=json``)
and asks :func:`~oh_no_my_claudecode.verifier.adapters.verified_or_false_green`
whether the run's changed executable lines were actually exercised by the
passing suite.

Honest by construction: no report, an unreadable report, or unmeasured changed
lines all grade as false-green (``True``) — evidence must exist to clear a run,
absence of evidence never blesses one.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from oh_no_my_claudecode.verifier.adapters import verified_or_false_green

if TYPE_CHECKING:
    from oh_no_my_claudecode.harness_run.run_policy import VerifierSignal

#: Standard output name of ``coverage json`` at the repo root.
COVERAGE_REPORT_NAME = "coverage.json"

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class _ChangeSetLike(Protocol):
    changed_files: tuple[str, ...]
    diff_text: str


def changed_lines_from_diff(diff_text: str) -> dict[str, set[int]]:
    """Map repo-relative path -> added/modified line numbers from a unified diff.

    Tracks ``+++ b/<path>`` targets and counts new-file line numbers through
    each hunk. Deleted-only files contribute nothing (no new lines to cover).
    """
    changed: dict[str, set[int]] = {}
    path: str | None = None
    new_line = 0
    in_hunk = False
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            path = None if target == "/dev/null" else target.removeprefix("b/")
            in_hunk = False
            continue
        match = _HUNK_RE.match(raw)
        if match:
            new_line = int(match.group(1))
            in_hunk = True
            continue
        if not in_hunk or path is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            changed.setdefault(path, set()).add(new_line)
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            continue  # old-file line; new-file counter unchanged
        else:
            new_line += 1
    return changed


def coverage_false_green_check(
    repo_root: Path,
) -> Callable[[object, tuple[VerifierSignal, ...], _ChangeSetLike], bool]:
    """Build the default ``verifier_false_green_check`` for *repo_root*.

    Returns a callable matching the harness seam ``(request, signals,
    change_set) -> bool`` where ``True`` means false-green (blocks verified).
    """
    root = Path(repo_root)

    def _check(
        request: object,
        signals: tuple[VerifierSignal, ...],
        change_set: _ChangeSetLike,
    ) -> bool:
        del request, signals
        changed = changed_lines_from_diff(change_set.diff_text)
        if not changed:
            # No textual change to grade — nothing claims coverage, not a false green.
            return False
        report = root / COVERAGE_REPORT_NAME
        if not report.is_file():
            # ponytail: consume-evidence-only; auto-running the suite under
            # coverage (cost, extra dep) is the upgrade path if demanded.
            return True
        try:
            return verified_or_false_green(report, changed)
        except Exception:
            return True  # unreadable evidence is not evidence

    return _check


__all__ = ["COVERAGE_REPORT_NAME", "changed_lines_from_diff", "coverage_false_green_check"]
