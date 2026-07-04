"""Adversarial diff-level verification — the empty-diff false-converge gate.

A coding loop can declare victory simply because the pre-existing test suite
still passes — even when the agent changed *nothing*.  This module closes that
hole.  :func:`verify_diff` is a pure, offline, deterministic function over an
injected unified diff that passes ONLY when the change is:

- **real** — the diff is non-empty (the headline bug);
- **complete** — every expected new symbol / file is actually present in the
  added lines;
- **covered** — every added executable line is covered (when coverage data is
  supplied);
- **lawful** — no banned or secret pattern appears in any added line (the audit
  secret regexes are reused verbatim).

Everything operates on strings handed in by the caller, so there is no I/O,
no network, and no clock dependency: the same inputs always yield the same
:class:`VerifyReport`.  The real CLI shells ``git diff`` via
:func:`collect_diff` and feeds the text in; tests never touch git.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.audit.rules import _SECRET_PATTERNS

# Coverage is supplied as a mapping of repo-relative file path -> the set of
# 1-based line numbers that the test suite exercised.  ``None`` means "no
# coverage data was provided" (a soft note, not a failure).
Coverage = dict[str, set[int]]

# A structural-diff runner is any callable that, given a unified *diff_text*,
# returns a :class:`StructuralResult` describing whether the change carries a
# *structural* (AST-level) difference — i.e. one that survives formatting /
# whitespace normalisation.  It is injected so the pure gate never shells out;
# the real CLI supplies :func:`difftastic_runner`, tests supply a fake.
StructuralDiffRunner = Callable[[str], "StructuralResult"]

# Name of the difftastic binary on PATH (``difft``).  difftastic is an external
# binary, NOT a pip package — we detect it with :func:`shutil.which`.
_DIFFT_BINARY = "difft"

# A diff hunk header looks like ``@@ -a,b +c,d @@`` — we need the ``+c`` start
# line so we can attribute added lines to their new line numbers.
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# ``+++ b/path/to/file`` (or ``+++ path``) marks the start of a file section.
_PLUS_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+?)\s*$")

# Default banned substrings — case-insensitive markers that should never land
# in a real change.  Callers extend this via ``banned_patterns``.
_DEFAULT_BANNED: tuple[str, ...] = (
    "TODO: remove before merge",
    "DO NOT COMMIT",
    "<<<<<<<",  # unresolved merge conflict marker
    ">>>>>>>",
)


@dataclass(slots=True)
class DiffFinding:
    """A single check outcome.

    Attributes
    ----------
    rule:
        Short identifier for the check (e.g. ``non-empty``, ``symbol`` ...).
    ok:
        ``True`` when the check passed, ``False`` when it failed.
    detail:
        One-line human-readable explanation of the outcome.
    """

    rule: str
    ok: bool
    detail: str


@dataclass(slots=True)
class StructuralResult:
    """Outcome of a structural (AST-level) diff over the change.

    Attributes
    ----------
    changed:
        ``True`` when the tool reports a genuine structural change — i.e. one
        that is *not* pure formatting / whitespace noise.  ``False`` means the
        two sides are structurally identical (only formatting differs), which
        the gate treats as a false-converge just like an empty diff.
    tool:
        Identifier of the tool that produced this result (e.g. ``difftastic``).
    detail:
        One-line human-readable summary of what the tool observed.
    """

    changed: bool
    tool: str
    detail: str


@dataclass(slots=True)
class AddedLine:
    """An added line attributed to its file and new-file line number."""

    file: str
    lineno: int
    text: str


@dataclass(slots=True)
class VerifyReport:
    """Aggregated diff-verification result.

    Attributes
    ----------
    findings:
        Every :class:`DiffFinding` produced, in evaluation order.
    ok:
        ``True`` only when **every** finding passed.
    """

    findings: list[DiffFinding] = field(default_factory=list)
    ok: bool = True

    def failed(self) -> list[DiffFinding]:
        """Return only the findings that failed."""
        return [f for f in self.findings if not f.ok]


def _parse_added_lines(diff_text: str) -> list[AddedLine]:
    """Extract added lines (``+`` lines) with their new-file line numbers.

    File-header ``+++`` lines and hunk ``@@`` headers are skipped; only true
    content additions are returned.  Pure string parsing — no git, no I/O.
    """
    added: list[AddedLine] = []
    current_file = ""
    new_lineno = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++"):
            match = _PLUS_FILE_RE.match(raw)
            current_file = match.group(1) if match else ""
            # ``/dev/null`` means a deletion target — no added lines belong to it.
            if current_file == "/dev/null":
                current_file = ""
            continue
        if raw.startswith("---"):
            continue
        hunk = _HUNK_RE.match(raw)
        if hunk:
            new_lineno = int(hunk.group(1))
            continue
        if raw.startswith("+"):
            added.append(AddedLine(file=current_file, lineno=new_lineno, text=raw[1:]))
            new_lineno += 1
        elif raw.startswith("-"):
            # Removed line — does not advance the new-file cursor.
            continue
        else:
            # Context line (leading space) or other metadata — advances cursor
            # only when we are inside a hunk.
            if new_lineno:
                new_lineno += 1
    return added


def _check_non_empty(diff_text: str, added: list[AddedLine]) -> DiffFinding:
    """The headline check: a diff that adds nothing is a false-converge."""
    if diff_text.strip() and added:
        return DiffFinding(
            rule="non-empty",
            ok=True,
            detail=f"{len(added)} added line(s) across the diff.",
        )
    return DiffFinding(
        rule="non-empty",
        ok=False,
        detail=(
            "Diff is empty — no lines were added.  A passing test suite over an "
            "empty change is the false-converge bug this gate exists to catch."
        ),
    )


def _check_symbols(added: list[AddedLine], expect_symbols: tuple[str, ...]) -> list[DiffFinding]:
    """Assert each expected symbol appears in at least one added line."""
    findings: list[DiffFinding] = []
    added_text = "\n".join(line.text for line in added)
    for symbol in expect_symbols:
        present = symbol in added_text
        findings.append(
            DiffFinding(
                rule=f"symbol:{symbol}",
                ok=present,
                detail=(
                    f"Expected symbol `{symbol}` found in added lines."
                    if present
                    else f"Expected symbol `{symbol}` missing from added lines."
                ),
            )
        )
    return findings


def _check_files(added: list[AddedLine], expect_files: tuple[str, ...]) -> list[DiffFinding]:
    """Assert each expected file path has at least one added line."""
    findings: list[DiffFinding] = []
    touched = {line.file for line in added if line.file}
    for rel in expect_files:
        present = rel in touched
        findings.append(
            DiffFinding(
                rule=f"file:{rel}",
                ok=present,
                detail=(
                    f"Expected file `{rel}` has added lines."
                    if present
                    else f"Expected file `{rel}` has no added lines in the diff."
                ),
            )
        )
    return findings


def _is_coverable(text: str) -> bool:
    """Heuristic: does this added line carry executable intent worth covering?

    Blank lines, comments, and pure-bracket/punctuation lines are never
    "uncovered" in a meaningful sense, so they are excluded from the coverage
    check to avoid false failures.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return False
    # Lines that are only closing/opening punctuation carry no coverable logic.
    return any(ch.isalnum() for ch in stripped)


def _check_coverage(added: list[AddedLine], coverage: Coverage | None) -> list[DiffFinding]:
    """Flag added executable lines that the supplied coverage does not cover."""
    if coverage is None:
        return [
            DiffFinding(
                rule="coverage",
                ok=True,
                detail="No coverage data supplied — coverage check skipped (soft note).",
            )
        ]
    uncovered: list[AddedLine] = []
    for line in added:
        if not line.file or not _is_coverable(line.text):
            continue
        covered_lines = coverage.get(line.file)
        if covered_lines is None or line.lineno not in covered_lines:
            uncovered.append(line)
    if not uncovered:
        return [
            DiffFinding(
                rule="coverage",
                ok=True,
                detail="All added executable lines are covered.",
            )
        ]
    sample = ", ".join(f"{line.file}:{line.lineno}" for line in uncovered[:5])
    suffix = "" if len(uncovered) <= 5 else f" (+{len(uncovered) - 5} more)"
    return [
        DiffFinding(
            rule="coverage",
            ok=False,
            detail=f"{len(uncovered)} added line(s) not covered by tests: {sample}{suffix}.",
        )
    ]


def _check_lawful(
    added: list[AddedLine],
    banned_patterns: tuple[str, ...],
) -> list[DiffFinding]:
    """Assert no banned substring or secret pattern is present in added lines."""
    findings: list[DiffFinding] = []
    banned = (*_DEFAULT_BANNED, *banned_patterns)

    banned_hits: list[str] = []
    for line in added:
        lowered = line.text.lower()
        for pattern in banned:
            if pattern.lower() in lowered:
                where = f"{line.file}:{line.lineno}" if line.file else f"line {line.lineno}"
                banned_hits.append(f"`{pattern}` at {where}")
    findings.append(
        DiffFinding(
            rule="lawful:banned",
            ok=not banned_hits,
            detail=(
                "No banned substrings in added lines."
                if not banned_hits
                else "Banned substring(s) in added lines: " + "; ".join(banned_hits[:5]) + "."
            ),
        )
    )

    secret_hits: list[str] = []
    for line in added:
        for rule_id, title, pattern, _fix in _SECRET_PATTERNS:
            if re.search(pattern, line.text):
                where = f"{line.file}:{line.lineno}" if line.file else f"line {line.lineno}"
                secret_hits.append(f"{rule_id} ({title}) at {where}")
    findings.append(
        DiffFinding(
            rule="lawful:secret",
            ok=not secret_hits,
            detail=(
                "No secret/credential patterns in added lines."
                if not secret_hits
                else "Secret pattern(s) in added lines: " + "; ".join(secret_hits[:5]) + "."
            ),
        )
    )
    return findings


def difftastic_available() -> bool:
    """Return ``True`` when the ``difft`` binary is discoverable on ``PATH``.

    difftastic is an external binary (not a pip package); this is the sole
    detection point.  When it returns ``False`` the structural check is skipped
    and the gate falls back to its existing line-diff behaviour unchanged.
    """
    return shutil.which(_DIFFT_BINARY) is not None


def _check_structural(
    diff_text: str,
    runner: StructuralDiffRunner | None,
) -> DiffFinding:
    """Structural (AST) sanity check — passes when the change is real *shape*.

    When no *runner* is injected (the common case, or when ``difft`` is absent)
    this is a soft passing note and the gate relies on the line-based
    ``non-empty`` check alone — i.e. **zero regression** versus the original
    behaviour.  When a runner is supplied, its :class:`StructuralResult` decides:
    a change that is only formatting noise (``changed == False``) FAILS, because
    a reformat-only diff is the same false-converge the gate exists to catch.
    """
    if runner is None:
        return DiffFinding(
            rule="structural",
            ok=True,
            detail="No structural-diff tool selected — structural check skipped (soft note).",
        )
    result = runner(diff_text)
    return DiffFinding(
        rule="structural",
        ok=result.changed,
        detail=(
            f"{result.tool}: {result.detail}"
            if result.changed
            else (
                f"{result.tool}: {result.detail} — the change is formatting noise only "
                "(no structural/AST difference), a false-converge this gate rejects."
            )
        ),
    )


def verify_diff(
    *,
    diff_text: str,
    coverage: Coverage | None = None,
    expect_symbols: tuple[str, ...] = (),
    expect_files: tuple[str, ...] = (),
    banned_patterns: tuple[str, ...] = (),
    structural_runner: StructuralDiffRunner | None = None,
) -> VerifyReport:
    """Adversarially verify a unified *diff_text*.

    Pure and deterministic: operates only on the injected strings, performs no
    I/O, and makes no network or LLM calls.  The same inputs always produce an
    identical :class:`VerifyReport`.

    Parameters
    ----------
    diff_text:
        A unified diff (``git diff`` output).  An empty/whitespace-only diff —
        or one with no added lines — fails the headline ``non-empty`` check.
    coverage:
        Optional mapping of repo-relative file path -> set of covered 1-based
        line numbers.  When supplied, every added *executable* line must appear
        in its file's covered set.  When ``None``, the coverage check is a soft,
        passing note.
    expect_symbols:
        Symbols (substrings) that must each appear in at least one added line —
        e.g. a new function or class name the change is supposed to introduce.
    expect_files:
        Repo-relative paths that must each receive at least one added line.
    banned_patterns:
        Extra case-insensitive substrings that must not appear in any added
        line, layered on top of the built-in banned markers.
    structural_runner:
        Optional injected callable that performs a structural (AST-level) diff
        and returns a :class:`StructuralResult`.  When supplied — the real CLI
        wires :func:`difftastic_runner` here *only when* the ``difft`` binary is
        on ``PATH`` — the gate additionally rejects reformat-only diffs that
        carry no structural change.  When ``None`` (default, and whenever
        ``difft`` is absent) the structural check is a soft passing note and the
        gate behaves exactly as before (zero regression).  Injecting the runner
        keeps :func:`verify_diff` pure: it never shells a binary itself.

    Returns
    -------
    VerifyReport
        ``ok`` is ``True`` only when every individual finding passed.
    """
    added = _parse_added_lines(diff_text)

    findings: list[DiffFinding] = [_check_non_empty(diff_text, added)]
    findings.append(_check_structural(diff_text, structural_runner))
    findings.extend(_check_symbols(added, expect_symbols))
    findings.extend(_check_files(added, expect_files))
    findings.extend(_check_coverage(added, coverage))
    findings.extend(_check_lawful(added, banned_patterns))

    return VerifyReport(findings=findings, ok=all(f.ok for f in findings))


def collect_diff(repo_root: Path, base: str) -> str:
    """Return ``git diff <base>...HEAD`` for *repo_root* (real-CLI helper).

    This is the only impure entry point: it shells out to git.  It is never
    used by the unit tests, which inject ``diff_text`` directly into
    :func:`verify_diff` to stay offline and deterministic.

    Parameters
    ----------
    repo_root:
        Repository root to run ``git diff`` in.
    base:
        Base ref to diff against (e.g. ``main``).  Uses the three-dot form so
        only changes introduced on the current branch are considered.

    Returns
    -------
    str
        The unified diff text (may be empty when there is no change).
    """
    import subprocess

    result = subprocess.run(
        ["git", "diff", f"{base}...HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


# ``diff --git a/path b/path`` — the canonical file-section header we parse to
# recover the set of changed paths for structural diffing.
_GIT_HEADER_RE = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+?)\s*$")


def _changed_paths(diff_text: str) -> list[str]:
    """Recover repo-relative paths of files touched by *diff_text*.

    Prefers ``diff --git`` headers; falls back to ``+++ b/path`` sections when
    those are absent.  ``/dev/null`` targets are dropped.  Order-preserving and
    de-duplicated so the structural runner walks each file once.
    """
    paths: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        if path and path != "/dev/null" and path not in seen:
            seen.add(path)
            paths.append(path)

    for raw in diff_text.splitlines():
        header = _GIT_HEADER_RE.match(raw)
        if header:
            _add(header.group("b"))
            continue
    if paths:
        return paths
    for raw in diff_text.splitlines():
        if raw.startswith("+++"):
            match = _PLUS_FILE_RE.match(raw)
            if match:
                _add(match.group(1))
    return paths


def make_difftastic_runner(repo_root: Path, base: str) -> StructuralDiffRunner:
    """Build a real :data:`StructuralDiffRunner` backed by the ``difft`` binary.

    This is an *impure* factory: the returned closure shells ``git show`` (to
    recover the base and working-tree versions of each changed file) and
    ``difft`` (to compare them structurally).  It is only ever wired into
    :func:`verify_diff` when :func:`difftastic_available` is ``True``; the unit
    tests inject a fake runner instead, so no real binary is invoked offline.

    difftastic is run with ``--exit-code``: exit status ``0`` means the two
    sides are *structurally identical* (only formatting differs) and ``1`` means
    a genuine structural change.  Any other status (tool error, unparseable
    file) is treated conservatively as "structural change present" so the gate
    never fails a real change just because ``difft`` could not classify it.
    """
    import subprocess
    import tempfile

    def _runner(diff_text: str) -> StructuralResult:
        paths = _changed_paths(diff_text)
        if not paths:
            # Nothing to compare structurally — defer to the line-based
            # non-empty check (which will have already failed on an empty diff).
            return StructuralResult(
                changed=bool(diff_text.strip()),
                tool="difftastic",
                detail="no file sections found in diff.",
            )
        any_structural = False
        for rel in paths:
            old = subprocess.run(
                ["git", "show", f"{base}:{rel}"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            old_text = old.stdout if old.returncode == 0 else ""
            new_path = repo_root / rel
            try:
                new_text = new_path.read_text()
            except OSError:
                new_text = ""
            suffix = Path(rel).suffix or ".txt"
            with (
                tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as old_f,
                tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as new_f,
            ):
                old_f.write(old_text)
                new_f.write(new_text)
                old_name, new_name = old_f.name, new_f.name
            try:
                proc = subprocess.run(
                    [_DIFFT_BINARY, "--exit-code", old_name, new_name],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                Path(old_name).unlink(missing_ok=True)
                Path(new_name).unlink(missing_ok=True)
            # exit 0 == structurally identical; anything else == treat as changed.
            if proc.returncode != 0:
                any_structural = True
        if any_structural:
            return StructuralResult(
                changed=True,
                tool="difftastic",
                detail=f"structural change detected across {len(paths)} file(s).",
            )
        return StructuralResult(
            changed=False,
            tool="difftastic",
            detail=f"{len(paths)} file(s) differ only in formatting.",
        )

    return _runner
