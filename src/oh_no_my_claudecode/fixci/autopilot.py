"""Core CI-fix autopilot — pure, deterministic plan synthesis over a CI log.

The single public entry point is :func:`plan_ci_fix`, which is *pure* over the
injected ``log_text``: given the same log, repo, and memory store it always
produces the same :class:`CiFailure`. It performs no network I/O and spawns no
agents — it only *plans*.

Pipeline
--------
1. **Parse** the failing step name + a focused error excerpt out of the raw CI
   log (handles GitHub Actions ``##[group]`` / ``Error:`` markers, pytest
   ``FAILED``/``assert`` lines, and a generic "first error-ish line" fallback).
2. **Recall** related past dead-ends from memory using the error excerpt — we
   reuse :func:`oh_no_my_claudecode.guard.compiler.compile_guard` (FAILED_APPROACH
   bias) and :func:`oh_no_my_claudecode.recall.compiler.compile_recall`
   (error-text normalisation + fix extraction). We do **not** reimplement either.
3. **Map** the error excerpt to likely-fix source files via the structural code
   graph (:func:`oh_no_my_claudecode.codegraph.builder.context_files`), preferring
   any concrete file paths mentioned directly in the log.
4. **Suggest** a swarm unit (a self-contained prompt) the caller *could* run to
   apply the fix — emitted as data only; nothing is dispatched here.

``fetch_ci_log`` is the only impure helper (it shells ``gh run view
--log-failed``) and is intentionally never called from tests.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.codegraph.builder import build_codegraph, context_files
from oh_no_my_claudecode.guard.compiler import compile_guard
from oh_no_my_claudecode.recall.compiler import compile_recall, normalise_error_text
from oh_no_my_claudecode.storage import SQLiteStorage

# ---------------------------------------------------------------------------
# Parsing constants
# ---------------------------------------------------------------------------

# Strip GitHub Actions timestamp prefixes ("2024-01-02T03:04:05.1234567Z ").
_GHA_TS_RE = re.compile(
    r"^\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s?",
    re.MULTILINE,
)

# A GitHub Actions step boundary: "##[group]Run pytest" / "##[error]...".
_GHA_GROUP_RE = re.compile(r"^##\[group\](.+)$")
_GHA_ERROR_RE = re.compile(r"^##\[error\](.+)$")

# Lines that look like an error worth surfacing (case-insensitive).
_ERROR_MARKERS = (
    "error:",
    "error ",
    "traceback (most recent call last)",
    "failed",
    "assertionerror",
    "exception",
    "fatal:",
    "e   ",  # pytest's error-line gutter
    "##[error]",
)

# pytest's per-test failure summary line, e.g.
#   "FAILED tests/test_x.py::test_y - AssertionError: ..."
_PYTEST_FAILED_RE = re.compile(r"^FAILED\s+(\S+?)(?:::\S+)?\s*(?:-\s*(.*))?$")

# A concrete file path mentioned anywhere in the log (so we can prefer the file
# the CI itself pointed at over a fuzzy code-graph guess).
_PATH_RE = re.compile(r"\b((?:[\w.\-]+/)+[\w.\-]+\.\w+)(?::\d+)?")

# Maximum characters of error context to carry in the excerpt.
_MAX_EXCERPT_CHARS = 600
# Maximum likely-fix files to surface.
_MAX_LIKELY_FILES = 6
# Maximum recalled dead-ends to surface.
_MAX_DEAD_ENDS = 5


@dataclass
class CiFailure:
    """A parsed CI failure plus the deterministic fix plan derived from it.

    Fields
    ------
    failing_step:
        The CI step that failed (e.g. ``"Run pytest"``), or ``""`` when the log
        carried no recognisable step boundary.
    error_excerpt:
        A focused excerpt of the error text (bounded to keep agent context small).
    likely_files:
        Repo-relative source paths most likely to need a change, file paths the
        log named first, then code-graph matches. Sorted-deterministic.
    dead_ends:
        Short "DO NOT retry" lines recalled from past failures relevant to this
        error. Empty when memory has nothing relevant — that is not an error.
    suggested_fix:
        A one-line human-readable suggestion for how to proceed.
    swarm_unit:
        A self-contained prompt the caller *could* hand to ``onmc swarm`` to
        apply the fix. Plan-only: nothing is dispatched by this module.
    """

    failing_step: str = ""
    error_excerpt: str = ""
    likely_files: list[str] = field(default_factory=list)
    dead_ends: list[str] = field(default_factory=list)
    suggested_fix: str = ""
    swarm_unit: str = ""

    @property
    def has_failure(self) -> bool:
        """True when the log yielded any actionable signal."""
        return bool(self.error_excerpt or self.failing_step or self.likely_files)

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict (deterministic key order)."""
        return {
            "failing_step": self.failing_step,
            "error_excerpt": self.error_excerpt,
            "likely_files": list(self.likely_files),
            "dead_ends": list(self.dead_ends),
            "suggested_fix": self.suggested_fix,
            "swarm_unit": self.swarm_unit,
        }


# ---------------------------------------------------------------------------
# Log parsing (pure)
# ---------------------------------------------------------------------------


def _strip_log_noise(log_text: str) -> str:
    """Remove GitHub Actions timestamp prefixes from each line."""
    return _GHA_TS_RE.sub("", log_text)


def _extract_failing_step(lines: list[str]) -> str:
    """Return the name of the last ``##[group]`` step before the first error.

    GitHub Actions wraps each step's output in ``##[group]<step name>`` … the
    step whose group most recently opened before the error is the failing one.
    Falls back to the step named by an ``##[error]`` line, else ``""``.
    """
    last_group = ""
    for line in lines:
        group_match = _GHA_GROUP_RE.match(line.strip())
        if group_match:
            last_group = group_match.group(1).strip()
            continue
        error_match = _GHA_ERROR_RE.match(line.strip())
        if error_match:
            # An explicit error marker pins the failing step to the open group.
            return last_group or error_match.group(1).strip()
        if _is_error_line(line):
            return last_group
    return last_group


def _is_error_line(line: str) -> bool:
    """True if *line* looks like part of an error / failure."""
    low = line.strip().lower()
    if not low:
        return False
    return any(marker in low for marker in _ERROR_MARKERS)


def _extract_error_excerpt(lines: list[str]) -> str:
    """Return a focused excerpt around the first error-ish line.

    Prefers a pytest ``FAILED ...`` summary line when present (most actionable);
    otherwise takes the first error-marker line plus a couple of trailing lines
    for context. Bounded to ``_MAX_EXCERPT_CHARS``.
    """
    # 1) pytest FAILED summary lines are the richest single signal.
    failed_lines = [ln.strip() for ln in lines if _PYTEST_FAILED_RE.match(ln.strip())]
    if failed_lines:
        return "\n".join(failed_lines)[:_MAX_EXCERPT_CHARS]

    # 2) First error-marker line + up to two following lines for context.
    for idx, line in enumerate(lines):
        if _is_error_line(line):
            window = [ln.strip() for ln in lines[idx : idx + 3] if ln.strip()]
            return "\n".join(window)[:_MAX_EXCERPT_CHARS]

    # 3) Nothing error-ish — surface the last non-empty line (often the failure).
    for line in reversed(lines):
        if line.strip():
            return line.strip()[:_MAX_EXCERPT_CHARS]
    return ""


def _paths_in_log(log_text: str, repo_root: Path) -> list[str]:
    """Return repo-relative file paths the log mentions that exist on disk.

    Only paths resolving to an existing file under *repo_root* are kept, so a
    spurious match like ``http://x/y.html`` is dropped. Deterministic order:
    first appearance wins, deduplicated.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _PATH_RE.finditer(log_text):
        raw = match.group(1).strip()
        candidate = raw.replace("\\", "/").lstrip("./")
        if candidate in seen:
            continue
        if (repo_root / candidate).is_file():
            seen.add(candidate)
            ordered.append(candidate)
    return ordered


# ---------------------------------------------------------------------------
# Memory recall (reuses guard + recall compilers — no reimplementation)
# ---------------------------------------------------------------------------


def _recall_dead_ends(storage: SQLiteStorage, error_excerpt: str) -> list[str]:
    """Recall related past dead-ends as short "DO NOT retry" lines.

    Combines the guard compiler (FAILED_APPROACH bias) with the recall compiler
    (error-text normalisation + fix extraction). Deduplicated by memory id,
    deterministic order (guard first, then recall), bounded to ``_MAX_DEAD_ENDS``.
    """
    if not error_excerpt.strip():
        return []

    lines: list[str] = []
    seen_ids: set[str] = set()

    guard = compile_guard(storage, error_excerpt, limit=_MAX_DEAD_ENDS)
    for entry in guard.entries:
        if entry.memory_id in seen_ids:
            continue
        seen_ids.add(entry.memory_id)
        lines.append(f"{entry.title} — {entry.why_it_failed}".strip(" —"))

    recall = compile_recall(storage, error_excerpt, limit=_MAX_DEAD_ENDS)
    for recalled in recall.entries:
        if recalled.memory_id in seen_ids:
            continue
        seen_ids.add(recalled.memory_id)
        lines.append(f"{recalled.title} — fix: {recalled.resolution}".strip(" —"))

    return lines[:_MAX_DEAD_ENDS]


# ---------------------------------------------------------------------------
# Likely-fix file mapping (reuses codegraph — no reimplementation)
# ---------------------------------------------------------------------------


def _map_likely_files(repo_root: Path, error_excerpt: str, log_text: str) -> list[str]:
    """Map the error to likely-fix repo files.

    Paths the log named directly come first (CI told us where it broke), then
    code-graph matches against the normalised error tokens fill the remainder.
    Bounded to ``_MAX_LIKELY_FILES``, deduplicated, deterministic.
    """
    ordered: list[str] = []
    seen: set[str] = set()

    for path in _paths_in_log(log_text, repo_root):
        if path not in seen:
            seen.add(path)
            ordered.append(path)
            if len(ordered) >= _MAX_LIKELY_FILES:
                return ordered

    goal = normalise_error_text(error_excerpt)
    if goal:
        try:
            graph = build_codegraph(repo_root)
            selection = context_files(graph, goal, budget=_MAX_LIKELY_FILES)
        except Exception:  # noqa: BLE001 - a broken repo must not crash planning
            selection = None
        if selection is not None:
            for path in selection.files:
                if path not in seen:
                    seen.add(path)
                    ordered.append(path)
                    if len(ordered) >= _MAX_LIKELY_FILES:
                        break

    return ordered


# ---------------------------------------------------------------------------
# Plan assembly
# ---------------------------------------------------------------------------


def _build_suggested_fix(failure: CiFailure) -> str:
    """Compose a one-line suggestion from the parsed signal."""
    if not failure.has_failure:
        return "No failing step or error found in the CI log — nothing to fix."
    parts: list[str] = []
    if failure.failing_step:
        parts.append(f"Fix the '{failure.failing_step}' step")
    else:
        parts.append("Fix the failing CI step")
    if failure.likely_files:
        parts.append(f"start with {failure.likely_files[0]}")
    if failure.dead_ends:
        parts.append(f"avoid {len(failure.dead_ends)} known dead-end(s)")
    return "; ".join(parts) + "."


def _build_swarm_unit(pr: str, failure: CiFailure) -> str:
    """Compose a self-contained swarm-unit prompt (data only; not dispatched)."""
    if not failure.has_failure:
        return ""
    files = ", ".join(failure.likely_files) if failure.likely_files else "(see CI log)"
    step = failure.failing_step or "the failing CI step"
    avoid = ""
    if failure.dead_ends:
        avoid = " Do NOT retry these recorded dead-ends: " + " | ".join(failure.dead_ends)
    return (
        f"Fix CI for PR {pr}. Failing step: {step}. "
        f"Error: {failure.error_excerpt!r}. "
        f"Likely files to change: {files}.{avoid} "
        "Make the minimal change to turn CI green; add/adjust a regression test."
    )


def plan_ci_fix(
    storage: SQLiteStorage,
    repo_root: Path,
    *,
    log_text: str,
    pr: str = "",
) -> CiFailure:
    """Produce a deterministic fix plan for a failed CI run.

    Pure over the injected *log_text* — no network, no agent spawn. Given the
    same ``log_text``, ``repo_root`` and memory ``storage``, the returned
    :class:`CiFailure` is identical across runs.

    Args:
        storage: Initialised :class:`SQLiteStorage` (memory store) for dead-end
            recall. May be empty — recall then returns no dead-ends.
        repo_root: Repository root used for code-graph likely-file mapping.
        log_text: The failed CI run's log text (injected; in production this is
            the output of :func:`fetch_ci_log`). An empty/whitespace log yields
            a graceful empty plan rather than raising.
        pr: The PR identifier, used only to label the suggested swarm unit.

    Returns:
        A :class:`CiFailure`. ``has_failure`` is ``False`` for an empty/clean log.
    """
    repo_root = Path(repo_root)
    cleaned = _strip_log_noise(log_text or "")
    lines = cleaned.splitlines()

    failure = CiFailure()
    if not cleaned.strip():
        failure.suggested_fix = _build_suggested_fix(failure)
        return failure

    failure.failing_step = _extract_failing_step(lines)
    failure.error_excerpt = _extract_error_excerpt(lines)
    failure.likely_files = _map_likely_files(repo_root, failure.error_excerpt, cleaned)
    failure.dead_ends = _recall_dead_ends(storage, failure.error_excerpt)
    failure.suggested_fix = _build_suggested_fix(failure)
    failure.swarm_unit = _build_swarm_unit(pr, failure)
    return failure


# ---------------------------------------------------------------------------
# Impure helper (never exercised by tests)
# ---------------------------------------------------------------------------


def fetch_ci_log(pr: str, *, timeout: int = 60) -> str:
    """Fetch the failed-step log for *pr*'s latest CI run via the ``gh`` CLI.

    Shells out to ``gh run view --log-failed`` for the most recent run on the
    PR's head branch. This is the **only** impure function in the module and is
    never called from tests — tests inject ``log_text`` into :func:`plan_ci_fix`
    directly.

    Returns the captured log text (stdout, with stderr appended on failure) so a
    non-zero ``gh`` exit still yields something to parse rather than raising.
    """
    # Resolve the latest run id for the PR, then dump its failed-step logs.
    try:
        run_id = subprocess.run(
            [
                "gh",
                "run",
                "list",
                "--branch",
                _branch_for_pr(pr, timeout=timeout),
                "--limit",
                "1",
                "--json",
                "databaseId",
                "--jq",
                ".[0].databaseId",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""

    args = ["gh", "run", "view"]
    if run_id:
        args.append(run_id)
    args.append("--log-failed")
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout if completed.stdout else completed.stderr


def _branch_for_pr(pr: str, *, timeout: int) -> str:
    """Resolve a PR's head branch via ``gh pr view`` (best-effort)."""
    try:
        completed = subprocess.run(
            ["gh", "pr", "view", pr, "--json", "headRefName", "--jq", ".headRefName"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip()
