"""A/B outcome-level eval runner.

Public API
----------
- ``run_ab(task, condition, repo_root, ...)`` — run one task under one condition
- ``run_suite(tasks, ...)`` — run all tasks under both conditions and produce an ABReport

Fixture mode
------------
Pass ``fixture=True`` to replay pre-recorded results from fixtures.py instead
of spawning a real agent.  CI MUST use fixture mode.

Live mode
---------
Live mode shells out to ``claude -p <prompt> --output-format json`` (the same
subprocess boundary used by ClaudeCliAdapter in the loop engine). It uses the
Claude CLI's configured authentication, including subscription login. The
baseline is real, not simulated or auto-failed.

ONMC grounding (cc_onmc condition)
------------------------------------
In the cc_onmc condition, the task's prior lesson is stored in an isolated ONMC
SQLite brain and retrieved through the production ``compile_prompt_recall``
path. The resulting context is prepended to the otherwise identical task
prompt. Public-repository tasks pin a real pre-fix commit and apply only the
upstream regression test.

For a fully integrated test that exercises the real ONMC loop see the
``run_ab_with_loop`` variant (future work — requires an instrumented repo).
"""

from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
import textwrap
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from oh_no_my_claudecode.evals.ab.models import (
    ABCondition,
    ABReport,
    ABTask,
    ABTaskComparison,
    ABTaskResult,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DEFAULT_AGENT_TIMEOUT = 120  # seconds per agent call
_DEFAULT_MODEL = "sonnet"
_DEFAULT_EFFORT = "medium"
_DEFAULT_BUDGET_USD = 1.0
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class _AgentOutcome:
    output: str
    tokens: int | None
    error: str | None
    turns: int | None
    cost_usd: float | None
    model: str | None


def _run_setup(task: ABTask, repo_root: Path) -> None:
    """Execute setup_script inside repo_root to plant the buggy state.

    The setup code is executed with the working directory set to repo_root
    so that relative path operations (pathlib.Path("x.py").write_text(...))
    land in the correct directory.
    """
    setup_code = textwrap.dedent(task.setup_script)
    previous = Path.cwd()
    try:
        import os

        os.chdir(repo_root)
        exec(compile(setup_code, "<setup_script>", "exec"), {"__file__": str(repo_root)})  # noqa: S102
    finally:
        os.chdir(previous)


def _run_command(
    command: str | tuple[str, ...],
    repo_root: Path,
    *,
    timeout: int = 60,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one structured command without a shell."""
    import sys

    argv = list(command) if isinstance(command, tuple) else shlex.split(command)
    if not argv:
        raise ValueError("empty benchmark command")
    if argv[0] in {"python", "python3"}:
        argv[0] = sys.executable
    return subprocess.run(  # noqa: S603
        argv,
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_text,
        check=False,
    )


def _prepare_public_repo(task: ABTask, repo_root: Path) -> None:
    if not task.repo_url or not task.repo_commit:
        raise ValueError("public-repository tasks require repo_url and repo_commit")
    if not task.repo_url.startswith("https://github.com/"):
        raise ValueError("public benchmark repositories must use an https://github.com URL")
    if not _COMMIT_RE.fullmatch(task.repo_commit):
        raise ValueError("public benchmark commits must be full 40-character SHAs")

    clone = subprocess.run(  # noqa: S603
        ["git", "clone", "--quiet", "--no-checkout", task.repo_url, str(repo_root)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if clone.returncode != 0:
        raise RuntimeError(f"git clone failed: {clone.stderr.strip()}")
    checkout = _run_command(("git", "checkout", "--quiet", "--detach", task.repo_commit), repo_root)
    if checkout.returncode != 0:
        raise RuntimeError(f"git checkout failed: {checkout.stderr.strip()}")
    if task.setup_patch:
        applied = _run_command(
            ("git", "apply", "--whitespace=nowarn", "-"),
            repo_root,
            input_text=textwrap.dedent(task.setup_patch),
        )
        if applied.returncode != 0:
            raise RuntimeError(f"benchmark patch failed: {applied.stderr.strip()}")
    for command in task.setup_commands:
        result = _run_command(command, repo_root, timeout=300)
        if result.returncode != 0:
            output = (result.stdout + result.stderr).strip()
            raise RuntimeError(f"benchmark setup command failed: {output}")


def _commit_baseline(repo_root: Path) -> str:
    if not (repo_root / ".git").exists():
        init = _run_command(("git", "init", "--quiet"), repo_root)
        if init.returncode != 0:
            raise RuntimeError(init.stderr.strip())
    _run_command(("git", "add", "-A"), repo_root)
    commit = subprocess.run(  # noqa: S603
        ["git", "commit", "--quiet", "--no-gpg-sign", "-m", "onmc eval baseline"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "ONMC Eval",
            "GIT_AUTHOR_EMAIL": "eval@onmc.local",
            "GIT_COMMITTER_NAME": "ONMC Eval",
            "GIT_COMMITTER_EMAIL": "eval@onmc.local",
        },
    )
    if commit.returncode != 0:
        raise RuntimeError(f"failed to commit benchmark baseline: {commit.stderr.strip()}")
    result = _run_command(("git", "rev-parse", "HEAD"), repo_root)
    return result.stdout.strip()


def _prepare_task(task: ABTask, repo_root: Path) -> str:
    if task.repo_url:
        _prepare_public_repo(task, repo_root)
    else:
        repo_root.mkdir(parents=True, exist_ok=True)
        _run_setup(task, repo_root)
    return _commit_baseline(repo_root)


def _run_gate(task: ABTask, repo_root: Path) -> tuple[bool, str]:
    """Run gate_command inside repo_root.  Returns (passed, output).

    ``python`` in the gate_command is substituted with ``sys.executable`` so
    that the correct interpreter (and its installed packages including pytest)
    is used regardless of the PATH in the subprocess environment.
    """
    try:
        proc = _run_command(task.gate_command, repo_root)
        output = (proc.stdout + proc.stderr).strip()
        return proc.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "[gate timed out]"


def _write_hidden_gate_test(task: ABTask, repo_root: Path) -> None:
    """Write task.hidden_gate_test to test_gate.py inside repo_root.

    Called AFTER the agent has finished — the agent never sees this file during
    setup.  When hidden_gate_test is empty, this is a no-op.
    """
    if not task.hidden_gate_test:
        return
    (repo_root / "test_gate.py").write_text(textwrap.dedent(task.hidden_gate_test))


def _compile_onmc_context(task: ABTask) -> str:
    """Seed one repo-memory item and retrieve it through ONMC's real recall path."""
    from oh_no_my_claudecode.hooks.prompt_recall import compile_prompt_recall
    from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
    from oh_no_my_claudecode.storage import SQLiteStorage

    now = datetime.now(UTC)
    digest = hashlib.sha256(f"{task.id}:{task.onmc_hint}".encode()).hexdigest()[:24]
    with tempfile.TemporaryDirectory(prefix="onmc_ab_memory_") as memory_dir:
        storage = SQLiteStorage(Path(memory_dir) / "memory.db")
        storage.initialize()
        storage.upsert_memories(
            [
                MemoryEntry(
                    id=f"eval-{digest}",
                    kind=MemoryKind.GOTCHA,
                    title=f"Prior repository lesson for {task.id}",
                    summary=task.onmc_hint,
                    details=task.onmc_hint,
                    source_type=SourceType.GITHUB_PR,
                    source_ref=task.repo_commit or task.id,
                    tags=task.description.lower().split()[:12],
                    confidence=0.9,
                    created_at=now,
                    updated_at=now,
                )
            ]
        )
        context, _ = compile_prompt_recall(storage, task.description, terse=False)
    return context


def _build_prompt(task: ABTask, condition: ABCondition) -> str:
    """Build the agent prompt for the given condition."""
    if condition == "cc_onmc":
        context = _compile_onmc_context(task)
        return f"{context}\n\n## Task\n\n{task.description}"
    return task.description


def _run_claude_agent(
    prompt: str,
    repo_root: Path,
    timeout: int = _DEFAULT_AGENT_TIMEOUT,
    *,
    model: str = _DEFAULT_MODEL,
    effort: str = _DEFAULT_EFFORT,
    max_budget_usd: float = _DEFAULT_BUDGET_USD,
) -> _AgentOutcome:
    """Shell out to Claude Code with identical, isolated settings per condition.

    ``--dangerously-skip-permissions`` is passed so the agent acts autonomously
    in the throwaway temp repo without stalling on approval prompts.  The eval
    always runs in an isolated temporary directory, so this is safe.
    """
    cmd = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--model",
        model,
        "--effort",
        effort,
        "--max-budget-usd",
        str(max_budget_usd),
    ]
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return _AgentOutcome("", None, "claude CLI not found", None, None, model)
    except subprocess.TimeoutExpired:
        return _AgentOutcome("", None, f"claude timed out after {timeout}s", None, None, model)

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    # Parse JSON envelope when present
    tokens: int | None = None
    output = stdout
    error: str | None = None
    turns: int | None = None
    cost_usd: float | None = None
    actual_model: str | None = model

    try:
        data = json.loads(stdout)
        output = data.get("result", data.get("content", stdout))
        usage = data.get("usage", {})
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0) if usage else None
        if data.get("is_error"):
            error = output
        turns = data.get("num_turns")
        cost_usd = data.get("total_cost_usd")
        # Claude may report helper/subagent models before the requested main
        # model in modelUsage. The controlled variable is the --model value.
        actual_model = model
    except (json.JSONDecodeError, TypeError):
        # Raw text output — tolerated
        if proc.returncode not in (0, 1) and stderr:
            error = stderr

    if not output and stderr:
        output = stderr
        error = error or stderr

    return _AgentOutcome(output[:2000], tokens, error, turns, cost_usd, actual_model)


def _diff_metrics(repo_root: Path, baseline_sha: str) -> tuple[list[str], int, int]:
    names = _run_command(("git", "diff", "--name-only", baseline_sha), repo_root)
    tracked = [line for line in names.stdout.splitlines() if line]
    # ``git diff`` never lists untracked/newly-created files.  An agent-created
    # file (e.g. a new conftest.py / autouse fixture that shadows a failing test)
    # would then be invisible both to the diff-scope provenance report and to the
    # protected-path tamper guard.  Mirror the loop engine's probe and fold in
    # untracked files so new files are counted and scope-checked.
    others = _run_command(
        ("git", "ls-files", "--others", "--exclude-standard"), repo_root
    )
    untracked = [line for line in others.stdout.splitlines() if line]
    changed_files = sorted(set(tracked) | set(untracked))
    numstat = _run_command(("git", "diff", "--numstat", baseline_sha), repo_root)
    additions = 0
    deletions = 0
    for line in numstat.stdout.splitlines():
        added, deleted, *_ = line.split("\t")
        if added.isdigit():
            additions += int(added)
        if deleted.isdigit():
            deletions += int(deleted)
    for rel in untracked:
        try:
            content = (repo_root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        additions += content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    return changed_files, additions, deletions


def _run_pass_to_pass(task: ABTask, repo_root: Path) -> tuple[bool, str]:
    outputs: list[str] = []
    for command in task.pass_to_pass_commands:
        result = _run_command(command, repo_root, timeout=300)
        outputs.append((result.stdout + result.stderr).strip())
        if result.returncode != 0:
            return False, "\n".join(outputs)
    return True, "\n".join(outputs)


# ---------------------------------------------------------------------------
# Public: run one task under one condition
# ---------------------------------------------------------------------------


def run_ab(
    task: ABTask,
    condition: ABCondition,
    *,
    repo_root: Path | None = None,
    timeout: int = _DEFAULT_AGENT_TIMEOUT,
    model: str = _DEFAULT_MODEL,
    effort: str = _DEFAULT_EFFORT,
    max_budget_usd: float = _DEFAULT_BUDGET_USD,
) -> ABTaskResult:
    """Run one ABTask under one condition in a fresh temporary repo.

    Creates a temp directory, runs setup_script to plant the bug, invokes
    the agent, then evaluates the gate.  The temp directory is preserved on
    failure for debugging.

    Parameters
    ----------
    task:
        The task to run.
    condition:
        ``"cc_alone"`` (bare agent) or ``"cc_onmc"`` (with ONMC memory hint).
    repo_root:
        Optional pre-existing directory.  When None, a fresh tmpdir is used.
        Callers that want to preserve the dir between conditions must supply
        an isolated path per condition.
    timeout:
        Seconds before the agent subprocess is killed.

    Returns
    -------
    ABTaskResult
        Concrete outcome — passed, tokens, duration_s, agent_output.
    """
    tmpdir_obj: tempfile.TemporaryDirectory[str] | None = None
    if repo_root is None:
        tmpdir_obj = tempfile.TemporaryDirectory(prefix=f"onmc_ab_{task.id}_")
        active_root = Path(tmpdir_obj.name)
    else:
        active_root = repo_root

    try:
        baseline_sha = _prepare_task(task, active_root)

        # Fix 3: baseline precheck — run gate before touching the stub so we can
        # record whether the task has signal.  For hidden-gate tasks the hidden
        # test is NOT yet written, so the gate only sees the gate_command on the
        # plain stub (which should fail; if it passes, the task has no signal).
        pre_gate_passed, pre_gate_output = _run_gate(task, active_root)
        stub_fails_precheck: bool = not pre_gate_passed

        if pre_gate_passed:
            import warnings

            warnings.warn(
                f"Task {task.id!r}: stub already passes the gate before the agent runs — "
                "this task has no signal (stub_fails_precheck=False).  The result is "
                "recorded but the task should be repaired or excluded.",
                stacklevel=2,
            )
            return ABTaskResult(
                task_id=task.id,
                condition=condition,
                passed=False,
                tokens=None,
                duration_s=0.0,
                agent_output="",
                error="invalid benchmark: stub already passes gate (no signal)",
                gate_output=pre_gate_output,
                repo_url=task.repo_url,
                repo_commit=task.repo_commit,
                prompt_sha256="",
                stub_fails_precheck=False,
            )

        # Build prompt
        prompt = _build_prompt(task, condition)

        # Run agent
        t0 = time.monotonic()
        outcome = _run_claude_agent(
            prompt,
            active_root,
            timeout=timeout,
            model=model,
            effort=effort,
            max_budget_usd=max_budget_usd,
        )
        duration_s = round(time.monotonic() - t0, 2)

        # Fix 2: write the hidden gate test (withheld during setup) now that the
        # agent has finished.  If hidden_gate_test is empty this is a no-op.
        _write_hidden_gate_test(task, active_root)

        passed, gate_output = _run_gate(task, active_root)
        pass_to_pass, pass_to_pass_output = _run_pass_to_pass(task, active_root)
        passed = passed and pass_to_pass
        if outcome.error and not outcome.output:
            passed = False
        changed_files, additions, deletions = _diff_metrics(active_root, baseline_sha)
        protected_changes = sorted(
            path
            for path in changed_files
            if any(fnmatch.fnmatch(path, pattern) for pattern in task.protected_paths)
        )
        if protected_changes:
            passed = False
            violations = "\n".join(
                f"protected benchmark file modified: {path}" for path in protected_changes
            )
            gate_output = f"{gate_output}\n{violations}".strip()

        return ABTaskResult(
            task_id=task.id,
            condition=condition,
            passed=passed,
            tokens=outcome.tokens,
            duration_s=duration_s,
            agent_output=outcome.output,
            error=outcome.error,
            fixture=False,
            evidence_kind="live",
            gate_output=f"{gate_output}\n{pass_to_pass_output}".strip(),
            changed_files=changed_files,
            additions=additions,
            deletions=deletions,
            turns=outcome.turns,
            cost_usd=outcome.cost_usd,
            model=outcome.model,
            repo_url=task.repo_url,
            repo_commit=task.repo_commit,
            prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
            stub_fails_precheck=stub_fails_precheck,
        )
    finally:
        if tmpdir_obj is not None:
            with contextlib.suppress(Exception):
                tmpdir_obj.cleanup()


# ---------------------------------------------------------------------------
# Public: run full suite
# ---------------------------------------------------------------------------


def run_suite(
    tasks: list[ABTask],
    *,
    fixture: bool = False,
    task_filter: str | None = None,
    timeout: int = _DEFAULT_AGENT_TIMEOUT,
    model: str = _DEFAULT_MODEL,
    effort: str = _DEFAULT_EFFORT,
    max_budget_usd: float = _DEFAULT_BUDGET_USD,
) -> ABReport:
    """Run all tasks under both conditions and produce an ABReport.

    Parameters
    ----------
    tasks:
        Tasks to run.  Typically ``BUILTIN_TASKS`` from tasks.py.
    fixture:
        When True, replay pre-recorded fixture results from fixtures.py.
        CI MUST use fixture mode (no live LLM or Claude authentication needed).
        When False, shell out to the claude CLI for each (task, condition).
    task_filter:
        When set, only run the task with this id.
    timeout:
        Per-agent timeout in seconds (live mode only).

    Returns
    -------
    ABReport
        Full comparison report with per-task and aggregate results.
    """
    active_tasks = tasks
    if task_filter:
        active_tasks = [t for t in tasks if t.id == task_filter]
        if not active_tasks:
            raise ValueError(f"No task with id {task_filter!r}. Available: {[t.id for t in tasks]}")

    if fixture:
        return _run_suite_fixture(active_tasks)

    return _run_suite_live(
        active_tasks,
        timeout=timeout,
        model=model,
        effort=effort,
        max_budget_usd=max_budget_usd,
    )


def _run_suite_fixture(tasks: list[ABTask]) -> ABReport:
    """Replay pre-recorded fixture results."""
    from oh_no_my_claudecode.evals.ab.fixtures import load_fixture_results

    fixture_map = load_fixture_results()
    comparisons: list[ABTaskComparison] = []

    for task in tasks:
        alone_key = (task.id, "cc_alone")
        onmc_key = (task.id, "cc_onmc")

        alone = fixture_map.get(
            alone_key,
            ABTaskResult(
                task_id=task.id,
                condition="cc_alone",
                passed=False,
                tokens=None,
                duration_s=0.0,
                agent_output="[no fixture for this task]",
                error="missing fixture",
                fixture=True,
            ),
        )
        onmc = fixture_map.get(
            onmc_key,
            ABTaskResult(
                task_id=task.id,
                condition="cc_onmc",
                passed=False,
                tokens=None,
                duration_s=0.0,
                agent_output="[no fixture for this task]",
                error="missing fixture",
                fixture=True,
            ),
        )
        comparisons.append(ABTaskComparison(task=task, alone=alone, onmc=onmc))

    return ABReport(comparisons=comparisons, fixture=True)


def _run_suite_live(
    tasks: list[ABTask],
    timeout: int = _DEFAULT_AGENT_TIMEOUT,
    model: str = _DEFAULT_MODEL,
    effort: str = _DEFAULT_EFFORT,
    max_budget_usd: float = _DEFAULT_BUDGET_USD,
) -> ABReport:
    """Run all tasks live using Claude Code's configured auth."""

    comparisons: list[ABTaskComparison] = []

    for task in tasks:
        # Each condition gets its own isolated tmpdir so repo state is fresh
        with (
            tempfile.TemporaryDirectory(prefix=f"onmc_ab_{task.id}_alone_") as alone_dir,
            tempfile.TemporaryDirectory(prefix=f"onmc_ab_{task.id}_onmc_") as onmc_dir,
        ):
            alone = run_ab(
                task,
                "cc_alone",
                repo_root=Path(alone_dir),
                timeout=timeout,
                model=model,
                effort=effort,
                max_budget_usd=max_budget_usd,
            )
            onmc = run_ab(
                task,
                "cc_onmc",
                repo_root=Path(onmc_dir),
                timeout=timeout,
                model=model,
                effort=effort,
                max_budget_usd=max_budget_usd,
            )
            comparisons.append(ABTaskComparison(task=task, alone=alone, onmc=onmc))

    return ABReport(comparisons=comparisons, fixture=False)
