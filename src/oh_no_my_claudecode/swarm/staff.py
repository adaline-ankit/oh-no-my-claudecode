"""Staff-engineer mode for the in-session swarm: an HONEST per-unit gate.

The inline swarm (``swarm/inline.py``) is an accountability ledger: the model
fans subagents out and reports each unit back via ``onmc swarm record``.  In its
original form a unit's ``verified`` flag was the *caller's attestation* — the
model simply asserted "this unit met its criteria".  That is a trust gap: a
subagent that built nothing, or whose change fails the quality gate, could still
be recorded as a verified success.

This module closes that gap.  A unit is "verified/done" ONLY when it
AUTOMATICALLY passes the same quality gate CI runs — executed in the unit's OWN
worktree, not the caller's say-so:

- :func:`run_preflight` runs ruff/mypy/cli-ref/pytest in the worktree;
- :func:`verify_diff` over :func:`collect_diff` asserts the change is real
  (non-empty) and lawful (no banned/secret patterns).

``ok = preflight_ok and diff_ok``.  Both the executor (for preflight) and the
diff text are injectable, so the gate is fully testable offline and
deterministically — no real subprocess, git, or network is ever required.

A verified unit may then open its OWN pull request via :func:`open_unit_pr`
(``onmc swarm pr``): push the unit's branch and open a PR with ``gh``, then stop
(never auto-merge).  An unverified unit is refused.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.preflight.runner import Executor, run_preflight
from oh_no_my_claudecode.verifydiff.checker import collect_diff, verify_diff

#: A git/gh runner takes an argv list + cwd and returns ``(returncode, output)``.
#: Injected by tests; the real CLI shells out via :mod:`subprocess`.
CommandRunner = Callable[[Sequence[str], Path], "tuple[int, str]"]


@dataclass(frozen=True)
class UnitVerification:
    """The verdict of an honest per-unit quality gate.

    Attributes
    ----------
    unit_id:
        The unit this verdict belongs to.
    preflight_ok:
        ``True`` when the full preflight gate (ruff/mypy/cli-ref/pytest) passed
        in the unit's worktree.
    diff_ok:
        ``True`` when the unit's diff against ``base`` is real and lawful.
    ok:
        ``preflight_ok and diff_ok`` — the unit is verified ONLY when both hold.
    details:
        Ordered human-readable lines explaining each check's outcome.
    """

    unit_id: str
    preflight_ok: bool
    diff_ok: bool
    ok: bool
    details: list[str] = field(default_factory=list)


def verify_unit(
    repo_root: Path,
    worktree: Path,
    base: str = "main",
    *,
    unit_id: str = "",
    preflight_executor: Executor | None = None,
    diff_text: str | None = None,
    provision: bool = True,
) -> UnitVerification:
    """Run the honest quality gate for one swarm unit in its OWN worktree.

    The gate is two independent checks, both of which must pass:

    1. **Preflight** — :func:`run_preflight` executes the CI gate
       (ruff/mypy/cli-ref/pytest) with ``repo_root`` set to ``worktree`` so the
       unit is judged on the code it actually produced, not the caller's tree.
    2. **Diff** — :func:`verify_diff` over the unit's unified diff asserts the
       change is non-empty (the false-converge headline) and lawful (no banned
       or secret patterns in added lines).

    Parameters
    ----------
    repo_root:
        Repository root (used only for context/labels — the gate runs in the
        worktree).
    worktree:
        The unit's isolated worktree.  Preflight runs here and, when
        ``diff_text`` is not injected, the diff is collected from here.
    base:
        Base ref the unit's diff is taken against (e.g. ``main``).
    unit_id:
        Optional label recorded on the returned :class:`UnitVerification`.
    preflight_executor:
        Injectable ``(cmd) -> (returncode, output)`` callable for preflight.
        When ``None`` the default subprocess executor runs in ``worktree``.
        Tests inject a fake for offline, deterministic runs.
    diff_text:
        Injectable unified diff.  When ``None`` the diff is collected live via
        :func:`collect_diff(worktree, base)`.  Tests inject the text directly so
        no git is touched.
    provision:
        Default ``True``: the preflight gate runs each tool via
        ``uv run --with <tool>`` so a FRESH worktree (no dev deps installed)
        resolves ruff/mypy/pytest on demand and pins ``typer==0.26.8`` for the
        cli-reference step — without this the gate FALSE-FAILS in clean
        worktrees.  Pass ``False`` for an already-provisioned env.

    Returns
    -------
    UnitVerification
        ``ok`` is ``True`` ONLY when both preflight and diff checks passed.  An
        empty diff (a unit that did not really build anything) makes ``diff_ok``
        — and therefore ``ok`` — ``False``, regardless of preflight.
    """
    preflight = run_preflight(
        worktree, executor=preflight_executor, provision=provision
    )
    preflight_ok = preflight.ok

    diff = diff_text if diff_text is not None else collect_diff(worktree, base)
    diff_report = verify_diff(diff_text=diff)
    diff_ok = diff_report.ok

    details: list[str] = []
    for step in preflight.steps:
        mark = "ok" if step.ok else "FAIL"
        details.append(f"preflight[{step.label}]: {mark} — {step.summary}")
    for finding in diff_report.findings:
        mark = "ok" if finding.ok else "FAIL"
        details.append(f"diff[{finding.rule}]: {mark} — {finding.detail}")

    return UnitVerification(
        unit_id=unit_id,
        preflight_ok=preflight_ok,
        diff_ok=diff_ok,
        ok=preflight_ok and diff_ok,
        details=details,
    )


def _default_command_runner(cmd: Sequence[str], cwd: Path) -> tuple[int, str]:
    """Subprocess-backed git/gh runner (the real-CLI path)."""
    import subprocess

    completed = subprocess.run(  # noqa: S603 - argv is fixed, never shell
        list(cmd),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout or ""


def _current_branch(worktree: Path, runner: CommandRunner) -> str:
    """Return the worktree's current branch name (or empty on failure)."""
    code, out = runner(["git", "rev-parse", "--abbrev-ref", "HEAD"], worktree)
    return out.strip() if code == 0 else ""


@dataclass(frozen=True)
class UnitPrResult:
    """Outcome of opening a per-unit pull request.

    Attributes
    ----------
    unit_id:
        The unit the PR belongs to.
    ok:
        ``True`` when the branch pushed and the PR was opened.
    branch:
        The branch that was pushed.
    pr_url:
        The opened PR's URL (empty when ``ok`` is ``False``).
    details:
        Ordered human-readable lines explaining each step's outcome.
    """

    unit_id: str
    ok: bool
    branch: str
    pr_url: str
    details: list[str] = field(default_factory=list)


def open_unit_pr(
    repo_root: Path,
    worktree: Path,
    base: str = "main",
    *,
    unit_id: str = "",
    title: str | None = None,
    body: str = "",
    branch: str | None = None,
    runner: CommandRunner | None = None,
) -> UnitPrResult:
    """Push a verified unit's branch and open its OWN PR (PR-and-stop).

    This NEVER merges — it pushes the branch and opens a pull request via
    ``gh pr create``, then stops.  The caller (``onmc swarm pr``) refuses to
    invoke this for a unit that is not verified, so an un-gated change can never
    reach a PR.

    Parameters
    ----------
    repo_root:
        Repository root (context only).
    worktree:
        The unit's worktree, whose branch is pushed.
    base:
        Base branch the PR targets (e.g. ``main``).
    unit_id:
        Optional label recorded on the result.
    title:
        PR title.  Defaults to a unit-scoped title when omitted.
    body:
        PR body text.
    branch:
        Branch to push.  When ``None`` it is read from the worktree's HEAD.
    runner:
        Injectable ``(cmd, cwd) -> (returncode, output)`` git/gh runner.  When
        ``None`` a subprocess-backed runner is used.  Tests inject a fake so no
        real git/gh/network is touched.

    Returns
    -------
    UnitPrResult
        ``ok`` is ``True`` only when both the push and ``gh pr create`` exited
        zero; ``pr_url`` carries the opened PR URL.
    """
    run = runner if runner is not None else _default_command_runner
    details: list[str] = []

    head = branch if branch is not None else _current_branch(worktree, run)
    if not head:
        details.append("branch: FAIL — could not resolve the worktree's current branch.")
        return UnitPrResult(unit_id=unit_id, ok=False, branch="", pr_url="", details=details)

    push_code, push_out = run(["git", "push", "-u", "origin", head], worktree)
    if push_code != 0:
        tail = push_out.strip().splitlines()[-1] if push_out.strip() else ""
        details.append(f"push: FAIL (exit {push_code}) {tail}".rstrip())
        return UnitPrResult(unit_id=unit_id, ok=False, branch=head, pr_url="", details=details)
    details.append(f"push: ok — {head} -> origin")

    pr_title = title if title is not None else f"swarm unit {unit_id or head}".strip()
    pr_code, pr_out = run(
        [
            "gh",
            "pr",
            "create",
            "--base",
            base,
            "--head",
            head,
            "--title",
            pr_title,
            "--body",
            body,
        ],
        worktree,
    )
    if pr_code != 0:
        tail = pr_out.strip().splitlines()[-1] if pr_out.strip() else ""
        details.append(f"pr: FAIL (exit {pr_code}) {tail}".rstrip())
        return UnitPrResult(unit_id=unit_id, ok=False, branch=head, pr_url="", details=details)

    pr_url = pr_out.strip().splitlines()[-1] if pr_out.strip() else ""
    details.append(f"pr: ok — {pr_url}")
    return UnitPrResult(unit_id=unit_id, ok=True, branch=head, pr_url=pr_url, details=details)
