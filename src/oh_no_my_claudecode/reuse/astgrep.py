"""Optional ast-grep structural code-search backend for the reuse radar.

When the ``ast-grep`` (or ``sg``) binary is on ``PATH``, :func:`find_reuse_structural`
can supplement the text/token heuristic in :mod:`oh_no_my_claudecode.reuse.radar`
with AST-pattern matching that is blind to identifier naming — catching
structurally-identical code that the token approach misses.

Architecture
------------
- :func:`ast_grep_available` — pure PATH lookup, the sole detection point.
- :data:`AstGrepRunner` — injectable ``Callable[[str, str], list[StructuralMatch]]``.
  The real CLI (:func:`make_ast_grep_runner`) shells out; tests inject a fake.
- :func:`find_reuse_structural` — offline-safe wrapper: when the runner is ``None``
  (or the binary is absent) it returns an empty list and the caller continues with
  the existing text-only results unchanged.

The result type :class:`StructuralMatch` is a separate dataclass so callers can
distinguish text-based :class:`~oh_no_my_claudecode.reuse.radar.ReuseHit` from
structural hits, then merge them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class StructuralMatch:
    """A structurally-similar code region found by ast-grep.

    Attributes
    ----------
    file:
        Repo-relative POSIX path of the file where the match was found.
    line_start:
        1-based start line of the matched region.
    line_end:
        1-based end line of the matched region (inclusive).
    text:
        The matched source text (may be truncated by ast-grep for long nodes).
    """

    file: str
    line_start: int
    line_end: int
    text: str


# An ``AstGrepRunner`` is any callable that, given:
#   - *pattern*: an ast-grep pattern string (the structural query)
#   - *root*: the repo-root directory as a POSIX string
# returns a list of :class:`StructuralMatch` objects.
# The real implementation shells ``ast-grep run``; tests inject a fake.
AstGrepRunner = Callable[[str, str], list[StructuralMatch]]

# Preferred binary name, then fallback.
_BINARY_NAMES = ("ast-grep", "sg")

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def ast_grep_available() -> bool:
    """Return ``True`` when an ``ast-grep`` or ``sg`` binary is on ``PATH``.

    This is the sole detection point.  When it returns ``False`` the structural
    check is not run and :func:`find_reuse_structural` returns an empty list —
    i.e. **zero regression** versus the existing text-only reuse behaviour.
    """
    return any(shutil.which(name) is not None for name in _BINARY_NAMES)


def _ast_grep_binary() -> str | None:
    """Return the first available ast-grep binary name, or ``None``."""
    for name in _BINARY_NAMES:
        if shutil.which(name) is not None:
            return name
    return None


# ---------------------------------------------------------------------------
# Real runner (impure — shells out)
# ---------------------------------------------------------------------------


def make_ast_grep_runner(root: Path) -> AstGrepRunner:
    """Build a real :data:`AstGrepRunner` backed by the ``ast-grep`` binary.

    This is the *only* place where the binary is invoked.  The returned closure
    is an impure shell-out; tests **never** call this factory — they inject a
    fake runner directly into :func:`find_reuse_structural`.

    The runner executes::

        ast-grep run --pattern <pattern> --json --lang python <root>

    and parses the JSON output into :class:`StructuralMatch` objects.  On any
    error (binary not found, non-zero exit, malformed output) it returns an empty
    list so the caller silently falls back to text-only results.

    Args:
        root: Repository root to scan.

    Returns:
        An :data:`AstGrepRunner` callable.
    """
    binary = _ast_grep_binary()

    def _runner(pattern: str, root_str: str) -> list[StructuralMatch]:
        if binary is None:
            return []
        try:
            proc = subprocess.run(
                [binary, "run", "--pattern", pattern, "--json", "--lang", "python", root_str],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []

        raw = proc.stdout.strip()
        if not raw:
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []

        # ast-grep --json emits either a JSON array of match objects or a
        # newline-delimited stream of objects.  Normalise to a list.
        if not isinstance(data, list):
            data = [data]

        matches: list[StructuralMatch] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            # ast-grep JSON shape:
            # {"file": "...", "range": {"start": {"line": N}, "end": {"line": M}}, "text": "..."}
            try:
                file_path = item.get("file", "")
                range_info = item.get("range", {})
                start_line = range_info.get("start", {}).get("line", 0) + 1  # 0-indexed → 1-indexed
                end_line = range_info.get("end", {}).get("line", 0) + 1
                text = item.get("text", "")
                if file_path:
                    # Make path relative to root when possible.
                    try:
                        rel = Path(file_path).relative_to(root_str).as_posix()
                    except ValueError:
                        rel = file_path
                    matches.append(
                        StructuralMatch(
                            file=rel,
                            line_start=start_line,
                            line_end=end_line,
                            text=text,
                        )
                    )
            except (KeyError, TypeError, AttributeError):
                continue

        return matches

    return _runner


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_reuse_structural(
    repo_root: Path | str,
    pattern: str,
    *,
    runner: AstGrepRunner | None = None,
) -> list[StructuralMatch]:
    """Find structurally-similar code using ast-grep's AST-pattern matching.

    This is the opt-in complement to the text/token heuristic in
    :func:`~oh_no_my_claudecode.reuse.radar.find_reuse`.  It is entirely
    **offline-safe**: when *runner* is ``None`` (i.e. the binary is absent or
    the caller did not opt in), it returns an empty list and the caller
    continues with text-only results unchanged — zero regression.

    Args:
        repo_root: Directory to scan for structurally-matching code.
        pattern: An ast-grep pattern string (e.g. ``"def $FUNC($$$ARGS):"``)
                 describing the structural shape to search for.
        runner: Injected :data:`AstGrepRunner` callable.  When ``None``, the
                function is a no-op.  The real CLI injects
                :func:`make_ast_grep_runner`; tests inject a fake.

    Returns:
        A list of :class:`StructuralMatch` objects, possibly empty.  Order
        reflects the runner's output (typically file-path + line order).
        Never raises — any runner error produces an empty list.
    """
    if runner is None:
        return []
    if not pattern or not pattern.strip():
        return []
    root = Path(repo_root)
    if not root.is_dir():
        return []
    try:
        return runner(pattern, root.as_posix())
    except Exception:  # noqa: BLE001 — never propagate; caller has fallback
        return []
