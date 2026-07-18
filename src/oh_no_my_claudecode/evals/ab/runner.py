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
subprocess boundary used by ClaudeCliAdapter in the loop engine).  Requires the
claude CLI and a valid ANTHROPIC_API_KEY.  The baseline is REAL — not simulated
or auto-failed.

ONMC grounding (cc_onmc condition)
------------------------------------
In the cc_onmc condition the agent prompt is prefixed with the task's
``onmc_hint`` — the same context that ONMC's compile_recall / compile_guard
would inject.  This simulates a grounded agent session without requiring a live
ONMC loop (which would need a full SQLite brain seeded with relevant memories).

For a fully integrated test that exercises the real ONMC loop see the
``run_ab_with_loop`` variant (future work — requires an instrumented repo).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import time
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


def _run_setup(task: ABTask, repo_root: Path) -> None:
    """Execute setup_script inside repo_root to plant the buggy state.

    The setup code is executed with the working directory set to repo_root
    so that relative path operations (pathlib.Path("x.py").write_text(...))
    land in the correct directory.
    """
    import os

    setup_code = textwrap.dedent(task.setup_script)
    prev_cwd = os.getcwd()
    try:
        os.chdir(repo_root)
        exec(compile(setup_code, "<setup_script>", "exec"), {"__file__": str(repo_root)})  # noqa: S102
    finally:
        os.chdir(prev_cwd)


def _run_gate(task: ABTask, repo_root: Path) -> tuple[bool, str]:
    """Run gate_command inside repo_root.  Returns (passed, output).

    ``python`` in the gate_command is substituted with ``sys.executable`` so
    that the correct interpreter (and its installed packages including pytest)
    is used regardless of the PATH in the subprocess environment.
    """
    import sys

    gate_cmd = task.gate_command.replace("python", sys.executable, 1)
    try:
        proc = subprocess.run(
            gate_cmd,
            shell=True,  # noqa: S602
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = (proc.stdout + proc.stderr).strip()
        return proc.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "[gate timed out]"


def _build_prompt(task: ABTask, condition: ABCondition) -> str:
    """Build the agent prompt for the given condition."""
    if condition == "cc_onmc":
        return task.onmc_hint + task.description
    return task.description


def _run_claude_agent(
    prompt: str,
    repo_root: Path,
    timeout: int = _DEFAULT_AGENT_TIMEOUT,
) -> tuple[str, int | None, str | None]:
    """Shell out to claude CLI.  Returns (output, tokens, error)."""
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return "", None, "claude CLI not found — install @anthropic-ai/claude-code"
    except subprocess.TimeoutExpired:
        return "", None, f"claude timed out after {timeout}s"

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    # Parse JSON envelope when present
    tokens: int | None = None
    output = stdout
    error: str | None = None

    try:
        data = json.loads(stdout)
        output = data.get("result", data.get("content", stdout))
        usage = data.get("usage", {})
        tokens = (
            usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            if usage
            else None
        )
        if data.get("is_error"):
            error = output
    except (json.JSONDecodeError, TypeError):
        # Raw text output — tolerated
        if proc.returncode not in (0, 1) and stderr:
            error = stderr

    if not output and stderr:
        output = stderr
        error = error or stderr

    return output[:2000], tokens, error  # truncate for storage


# ---------------------------------------------------------------------------
# Public: run one task under one condition
# ---------------------------------------------------------------------------


def run_ab(
    task: ABTask,
    condition: ABCondition,
    *,
    repo_root: Path | None = None,
    timeout: int = _DEFAULT_AGENT_TIMEOUT,
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
    use_tmpdir = repo_root is None
    if use_tmpdir:
        tmpdir_obj = tempfile.TemporaryDirectory(prefix=f"onmc_ab_{task.id}_")
        repo_root = Path(tmpdir_obj.name)
    else:
        tmpdir_obj = None  # type: ignore[assignment]

    try:
        # Plant the buggy state
        _run_setup(task, repo_root)

        # Build prompt
        prompt = _build_prompt(task, condition)

        # Run agent
        t0 = time.monotonic()
        agent_output, tokens, error = _run_claude_agent(prompt, repo_root, timeout=timeout)
        duration_s = round(time.monotonic() - t0, 2)

        # Evaluate gate
        passed, _gate_out = _run_gate(task, repo_root)
        if error and not agent_output:
            passed = False

        return ABTaskResult(
            task_id=task.id,
            condition=condition,
            passed=passed,
            tokens=tokens,
            duration_s=duration_s,
            agent_output=agent_output,
            error=error,
            fixture=False,
        )
    finally:
        if use_tmpdir and tmpdir_obj is not None:
            try:
                tmpdir_obj.cleanup()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Public: run full suite
# ---------------------------------------------------------------------------


def run_suite(
    tasks: list[ABTask],
    *,
    fixture: bool = False,
    task_filter: str | None = None,
    timeout: int = _DEFAULT_AGENT_TIMEOUT,
) -> ABReport:
    """Run all tasks under both conditions and produce an ABReport.

    Parameters
    ----------
    tasks:
        Tasks to run.  Typically ``BUILTIN_TASKS`` from tasks.py.
    fixture:
        When True, replay pre-recorded fixture results from fixtures.py.
        CI MUST use fixture mode (no live LLM, no API key needed).
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
            raise ValueError(
                f"No task with id {task_filter!r}. "
                f"Available: {[t.id for t in tasks]}"
            )

    if fixture:
        return _run_suite_fixture(active_tasks)

    return _run_suite_live(active_tasks, timeout=timeout)


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
) -> ABReport:
    """Run all tasks live — requires claude CLI and ANTHROPIC_API_KEY."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set.  "
            "Set the env var or use --fixture for CI-safe offline mode."
        )

    comparisons: list[ABTaskComparison] = []

    for task in tasks:
        # Each condition gets its own isolated tmpdir so repo state is fresh
        with tempfile.TemporaryDirectory(prefix=f"onmc_ab_{task.id}_alone_") as alone_dir, \
             tempfile.TemporaryDirectory(prefix=f"onmc_ab_{task.id}_onmc_") as onmc_dir:

            alone = run_ab(
                task,
                "cc_alone",
                repo_root=Path(alone_dir),
                timeout=timeout,
            )
            onmc = run_ab(
                task,
                "cc_onmc",
                repo_root=Path(onmc_dir),
                timeout=timeout,
            )
            comparisons.append(ABTaskComparison(task=task, alone=alone, onmc=onmc))

    return ABReport(comparisons=comparisons, fixture=False)
