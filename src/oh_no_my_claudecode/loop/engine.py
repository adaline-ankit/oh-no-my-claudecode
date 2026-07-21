"""Loop engine: memory-grounded iteration with falsifiable prediction-outcome contracts.

Each iteration:
1. RECALL: compile_guard (dead-ends) + prompt_recall (relevant memories) → brief.
2. PROMPT: goal + brief injected into agent prompt.
3. ACT: agent_runner(prompt, escalation_level) → AgentRunResult.
4. VERIFY: verify_runner(command) → VerifyOutcome.
5. CONTRACT: WIN → DECISION memory; LOSS → FAILED_APPROACH memory (blocks next iter).
6. ESCALATE: consecutive_losses >= escalation_threshold → escalation_level++.
7. NO-PROGRESS: same (files, verify_output) signature repeats no_progress_window times → stop.
"""

from __future__ import annotations

import fnmatch
import hashlib
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from oh_no_my_claudecode.guard.compiler import compile_guard
from oh_no_my_claudecode.hooks.prompt_recall import compile_prompt_recall
from oh_no_my_claudecode.loop.checkpoint import (
    CheckpointState,
    CheckpointStore,
    _loop_spec_sha8,
)
from oh_no_my_claudecode.loop.models import (
    AgentRunner,
    AgentRunResult,
    ChangeProbe,
    IsolationProvider,
    IterationContract,
    LoopConfig,
    LoopResult,
    LoopSpec,
    VerifyOutcome,
    VerifyRunner,
)
from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now

_VERIFY_TIMEOUT = 120  # seconds; subprocess guard
_MAX_VERIFY_OUTPUT = 2000  # chars stored per contract
_CHANGE_PROBE_TIMEOUT = 15  # seconds; git status guard


def _make_git_change_probe(repo_root: Path) -> ChangeProbe:
    """Build the default working-tree change probe backed by ``git status``.

    Uses ``git status --porcelain`` (NOT ``git diff``) so that *untracked* new
    files created by the agent count as changes — a plain ``git diff`` would miss
    a freshly-written new file and wrongly flag a legitimate run as a no-op.

    Returns ``None`` when git is unavailable or the path is not a repository, so
    the engine cleanly skips the vacuous-pass gate in non-git environments
    (e.g. unit tests running in a bare tmp dir).
    """

    def _probe() -> str | None:
        try:
            result = subprocess.run(  # noqa: S603
                ["git", "-C", str(repo_root), "status", "--porcelain"],  # noqa: S607
                capture_output=True,
                text=True,
                timeout=_CHANGE_PROBE_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout

    return _probe


def _files_from_git_status(status_output: str | None) -> frozenset[str]:
    """Parse ``git status --porcelain`` output into a set of file paths.

    Handles the common status codes (M, A, D, R, ?, …) and rename entries
    (``old -> new``) by keeping only the new path.  Returns an empty frozenset
    when *status_output* is ``None`` or blank.
    """
    if not status_output:
        return frozenset()
    files: set[str] = set()
    for line in status_output.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            # rename: "old -> new" — scope-check the destination
            path = path.split(" -> ", 1)[1].strip()
        if path:
            files.add(path)
    return frozenset(files)


def _changed_files_delta(
    pre_status: str | None,
    post_status: str | None,
) -> frozenset[str]:
    """Files changed *this iteration*: porcelain lines in *post* but not *pre*.

    The scope gate must only judge files the current iteration touched.  Using
    the full ``post`` status would flag files that were already dirty before the
    agent ran (a user's unrelated uncommitted edit, or leftovers from an earlier
    losing iteration) as out-of-scope, forcing a spurious loss on an otherwise
    valid win.  Comparing verbatim porcelain lines isolates the per-iteration
    delta: a file whose status line is identical before and after is excluded.

    Returns an empty frozenset when *post_status* is ``None`` (git unavailable).
    """
    if not post_status:
        return frozenset()
    pre_lines = set((pre_status or "").splitlines())
    delta = "\n".join(line for line in post_status.splitlines() if line not in pre_lines)
    return _files_from_git_status(delta)


def _scope_violation(
    changed_files: frozenset[str],
    allowed_paths: list[str],
    protected_paths: list[str],
) -> str | None:
    """Return a violation message when *changed_files* break the declared scope.

    Two independent checks run in order:

    1. **Protected check** — any file matching a pattern in *protected_paths*
       was modified → violation (these files must NEVER be touched).
    2. **Allowlist check** — when *allowed_paths* is non-empty, any file that
       does NOT match at least one pattern → violation (the change went outside
       the declared scope).

    Returns ``None`` when no violation is found.  Returns a short human-readable
    violation message otherwise; the engine prepends a ``[scope-violation]`` tag
    before storing it in the :class:`IterationContract`.
    """
    violations: list[str] = []

    if protected_paths:
        for path in sorted(changed_files):
            if any(fnmatch.fnmatch(path, pat) for pat in protected_paths):
                violations.append(f"protected file modified: {path!r}")

    if allowed_paths:
        for path in sorted(changed_files):
            if not any(fnmatch.fnmatch(path, pat) for pat in allowed_paths):
                violations.append(f"out-of-scope file modified: {path!r} (not in allowed_paths)")

    return "; ".join(violations) if violations else None


def _default_verify_runner(command: str) -> VerifyOutcome:
    """Real verify runner — runs command via subprocess with a timeout.

    This is the default used in production.  Tests must inject a fake runner
    instead of calling this function.
    """
    try:
        result = subprocess.run(  # noqa: S602, S603
            command,
            shell=True,  # noqa: S602
            capture_output=True,
            text=True,
            timeout=_VERIFY_TIMEOUT,
        )
        output = (result.stdout + result.stderr)[:_MAX_VERIFY_OUTPUT]
        return VerifyOutcome(passed=result.returncode == 0, output=output)
    except subprocess.TimeoutExpired:
        return VerifyOutcome(passed=False, output="[verify timed out]")
    except Exception as exc:  # noqa: BLE001
        return VerifyOutcome(passed=False, output=f"[verify error: {exc}]")


def _default_agent_runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
    """Stub real agent runner.

    A real implementation would shell out to an agent CLI (e.g. ``claude --print``).
    This stub is the default so that callers who inject their own runner can rely on
    the correct protocol signature.  Tests must inject a fake runner.
    """
    del prompt, escalation_level
    return AgentRunResult(
        output="[no agent configured — inject an AgentRunner]",
        prediction="",
        files_touched=[],
        tokens=None,
    )


def _iteration_signature(contract: IterationContract) -> str:
    """Deterministic fingerprint of (files_touched, verify_output_head).

    Used for no-progress detection.
    """
    files_str = ",".join(sorted(contract.files_touched))
    output_head = contract.verify_output[:200]
    return hashlib.sha256(f"{files_str}||{output_head}".encode()).hexdigest()[:16]


def _build_brief(
    storage: SQLiteStorage,
    goal: str,
    last_loss: IterationContract | None,
    escalation_level: int,
) -> str:
    """Build the memory-grounded brief injected into each iteration's prompt.

    Combines:
    - Relevant memories via prompt_recall (signal for what to try).
    - Dead-ends via compile_guard (signal for what NOT to try).
    - Last failure summary (concrete feedback from the previous iteration).
    - Escalation hint (when consecutive losses exceed threshold).
    """
    parts: list[str] = []

    # 1. Relevant memories via prompt recall.
    try:
        recall_md, _ = compile_prompt_recall(storage, goal)
        if recall_md:
            parts.append(recall_md)
    except Exception:  # noqa: BLE001, S110
        pass  # best-effort; never fail the loop because recall is unavailable

    # 2. Dead-ends — the DON'T-REPEAT section (the memory-grounded core property).
    try:
        guard = compile_guard(storage, goal)
        if guard.has_dead_ends:
            parts.append(guard.to_markdown())
    except Exception:  # noqa: BLE001, S110
        pass  # best-effort; never fail the loop because guard is unavailable

    # 3. Last failure summary — concrete context from the immediately prior loss.
    if last_loss is not None:
        parts.append(
            "## Last attempt failed\n\n"
            f"**What was tried:** {last_loss.action_summary}\n\n"
            f"**Prediction that failed:** {last_loss.prediction}\n\n"
            "**Verify output (truncated):**\n"
            f"```\n{last_loss.verify_output[:500]}\n```\n"
        )

    # 4. Escalation hint — surface after repeated failures.
    if escalation_level > 0:
        parts.append(
            f"## Escalation level {escalation_level}\n\n"
            "Previous strategies failed multiple times in a row. "
            "Try a fundamentally different approach — do not repeat the pattern of prior attempts."
        )

    return "\n\n".join(parts)


def _record_win(
    storage: SQLiteStorage,
    goal: str,
    contract: IterationContract,
    now: datetime,
) -> str:
    """Record a successful approach as a DECISION memory; return its id."""
    summary = (
        f"Approach that worked for goal: {goal[:120]}. Action: {contract.action_summary[:200]}."
    )
    mid = stable_id(
        MemoryKind.DECISION.value,
        f"loop-win:{goal[:80]}",
        summary,
        "loop:engine",
        prefix="loop",
    )
    entry = MemoryEntry(
        id=mid,
        kind=MemoryKind.DECISION,
        title=f"Loop win: {goal[:80]}",
        summary=summary,
        details=(
            f"Prediction: {contract.prediction}\nFiles touched: {', '.join(contract.files_touched)}"
        ),
        source_type=SourceType.SESSION,
        source_ref="loop:engine",
        tags=["loop-win", "loop"],
        confidence=0.85,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return mid


# Lowercase substrings that indicate a transient or environment failure rather than a
# substantive approach/logic failure.  When any of these appear in the harness-controlled
# verify output the loss is classified as "environment" and NOT written as a
# FAILED_APPROACH dead-end — such entries would only pollute the guard with noise.
_ENV_PATTERNS: tuple[str, ...] = (
    "permission denied",
    "permission approval",
    "pending permission",
    "file-write blocked",
    "file-writes blocked",
    "not granted",
    "network error",
    "network timeout",
    "connection error",
    "connection refused",
    "connection reset",
    "connection timed out",
    "read timed out",
    "request timed out",
    "rate limit",
    "rate-limit",
    "too many requests",
    "http 429",
    "status 429",
    "status code 429",
    "error 429",
    "429 too many requests",
    "out of memory",
    " oom",
    "command not found",
    "env: pytest: no such file or directory",
    "executable file not found",
    "[agent-error]",
    "[scope-unverifiable]",
)


def _classify_failure_cause(verify_output: str) -> str:
    """Return ``'environment'`` for transient/environment failures, ``'approach'`` otherwise.

    Environment/transient signals include permission errors, network issues, rate limits,
    OOM, and agent invocation errors.  These should NOT be stored as guarding dead-ends
    because they are not indicative of a bad approach — they are noise from the environment.

    Classification keys ONLY on the harness-controlled ``verify_output``.  The agent's
    own action summary is untrusted input (CLAUDE.md): an agent that merely mentions
    "rate limit" or "permission denied" in its narration must not be able to launder a
    genuine bad-approach loss into an unrecorded "environment" failure and defeat the
    don't-repeat guard.
    """
    text = verify_output.lower()
    return "environment" if any(pat in text for pat in _ENV_PATTERNS) else "approach"


def _record_loss(
    storage: SQLiteStorage,
    goal: str,
    contract: IterationContract,
    now: datetime,
) -> str | None:
    """Record a failed approach as FAILED_APPROACH so next iteration's guard blocks it.

    This is the core of the don't-repeat property: every loss is immediately
    written to memory tagged loop-deadend, so compile_guard() retrieves it on
    the very next iteration brief.

    Returns the memory id written, or ``None`` when the failure is classified as
    transient/environment (permission denied, network error, rate limit, etc.).
    Transient failures are NOT stored as dead-ends — they are environment noise,
    not evidence of a bad approach, and should never surface in guard output.
    """
    if _classify_failure_cause(contract.verify_output) == "environment":
        return None
    summary = (
        f"Failed approach for goal: {goal[:120]}. "
        f"Tried: {contract.action_summary[:200]}. "
        f"Prediction was: {contract.prediction[:100]}."
    )
    mid = stable_id(
        MemoryKind.FAILED_APPROACH.value,
        f"loop-deadend:{goal[:80]}",
        summary,
        f"loop:iter:{contract.iteration}",
        prefix="loop",
    )
    entry = MemoryEntry(
        id=mid,
        kind=MemoryKind.FAILED_APPROACH,
        title=f"Loop dead-end (iter {contract.iteration}): {goal[:60]}",
        summary=summary,
        details=(
            f"Verify output:\n{contract.verify_output[:800]}\n\n"
            f"Files touched: {', '.join(contract.files_touched)}"
        ),
        source_type=SourceType.SESSION,
        source_ref=f"loop:iter:{contract.iteration}",
        tags=["loop-deadend", "loop", "failed_approach"],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return mid


def _verify_output_head(output: str, *, chars: int = 200) -> str:
    """Return a normalised head of verify output for repeated-error detection."""
    return output[:chars]


def run_loop(
    storage: SQLiteStorage,
    repo_root: Path,
    spec: LoopSpec,
    config: LoopConfig,
    *,
    agent_runner: AgentRunner,
    verify_runner: VerifyRunner,
    now: datetime | None = None,
    clock: Callable[[], float] | None = None,
    isolation_provider: IsolationProvider | None = None,
    checkpoint_store: CheckpointStore | None = None,
    resume: bool = False,
    should_continue: Callable[[], bool] | None = None,
    change_probe: ChangeProbe | None = None,
) -> LoopResult:
    """Run a memory-grounded loop until convergence, budget, or max iterations.

    Parameters
    ----------
    storage:
        Initialised SQLiteStorage instance.  Dead-ends are written here and
        recalled here on the next iteration — this is the memory substrate.
    repo_root:
        Absolute path to the repo root.  Used as the base for worktree
        isolation when ``config.isolate`` is True.
    spec:
        Loop goal and optional success criteria.
    config:
        Runtime knobs: max_iterations, budget_tokens, verify_command,
        escalation_threshold, no_progress_window, max_cost_usd,
        max_wall_seconds, duplicate_action_limit, repeated_error_limit,
        isolate.
    agent_runner:
        Injectable callable matching the AgentRunner protocol.  The default
        _default_agent_runner is a no-op stub; real runs inject a CLI agent.
        Tests MUST inject a fake — never the real subprocess runner.
    verify_runner:
        Injectable callable matching the VerifyRunner protocol.  The default
        _default_verify_runner shells out.  Tests MUST inject a fake.
    now:
        Reference timestamp for memory records (injectable for deterministic tests).
    clock:
        Injectable monotonic clock (``Callable[[], float]``).  Defaults to
        ``time.monotonic``.  Tests inject a fake for deterministic wall-time
        limit testing.
    isolation_provider:
        Injectable worktree isolation provider.  When ``None`` and
        ``config.isolate`` is ``True``, the real
        :class:`~oh_no_my_claudecode.core.repo.WorktreeIsolationProvider` is
        used.  Pass a fake implementation in tests.
    checkpoint_store:
        Optional injectable :class:`~oh_no_my_claudecode.loop.checkpoint.CheckpointStore`.
        When provided, the engine writes a checkpoint after every iteration
        (atomic write) and clears it on terminal stop (converged or any
        non-resumable stop reason when ``resume`` is False).
        ``FileCheckpointStore`` is used by the service layer; tests inject
        ``InMemoryCheckpointStore`` for deterministic behaviour.
        When ``None``, no checkpointing is performed — existing behaviour.
    resume:
        When ``True`` and a matching checkpoint exists in ``checkpoint_store``,
        restore prior state (iterations, counters, recorded memory ids) and
        continue from where the previous run left off.  When ``False`` (default),
        any existing checkpoint is ignored and the loop starts fresh.
    should_continue:
        Optional callable that returns ``False`` to request a graceful abort.
        Checked at the top of every iteration.  When it returns ``False``, the
        loop stops immediately with ``stop_reason="aborted"`` without running
        the agent or verify for that iteration.  ``None`` (default) means no
        external abort signal — existing behaviour is unchanged.
    change_probe:
        Optional injectable :class:`~oh_no_my_claudecode.loop.models.ChangeProbe`
        used to detect whether the agent actually modified the working tree each
        iteration.  When ``None`` (default), a git-``status``-backed probe over
        the effective repo root is used.  When the probe reports NO change and
        the verify command nonetheless passed, that pass is *vacuous* and is
        refused a convergence win (guards the false-green failure mode where an
        agent's edits are blocked yet a lenient verifier exits 0).  A probe that
        returns ``None`` (git unavailable / not a repo) disables the gate.
        Tests inject a fake for deterministic behaviour.

    Returns
    -------
    LoopResult
        stop_reason is one of:
        'converged' | 'max-iterations' | 'budget' | 'no-progress' | 'cost' |
        'wall-time' | 'duplicate-action' | 'repeated-error' | 'no-changes' |
        'aborted' | 'agent-error'.
    """
    import logging as _logging

    _log = _logging.getLogger(__name__)

    ref_now: datetime = now if now is not None else datetime.now(UTC)
    _clock: Callable[[], float] = clock if clock is not None else time.monotonic

    # --- Worktree isolation setup ---
    # When config.isolate is True, create a fresh git worktree so the agent's
    # changes are isolated.  Roll back (remove the worktree) on failure; keep
    # on success.  Degrade gracefully if git worktree add fails.
    _provider: IsolationProvider | None = None
    _worktree_path: Path | None = None
    _effective_repo_root = repo_root  # may be replaced by worktree path

    if config.isolate:
        if isolation_provider is not None:
            _provider = isolation_provider
        else:
            from oh_no_my_claudecode.core.repo import WorktreeIsolationProvider

            _provider = WorktreeIsolationProvider()

        wt = _provider.setup(repo_root)
        if wt is not None:
            _worktree_path = wt
            _effective_repo_root = wt
            _log.debug("worktree isolation: using worktree at %s", wt)
        else:
            _log.warning("worktree isolation: setup failed — running in-place (no isolation)")

    # --- Working-tree change probe ---
    # Detects whether the agent actually modified files each iteration.  A
    # verify pass with zero changes is vacuous and never counts as a win.
    _probe: ChangeProbe = (
        change_probe if change_probe is not None else _make_git_change_probe(_effective_repo_root)
    )

    # --- Checkpoint / resume setup ---
    _ckpt_sha8: str | None = None
    if checkpoint_store is not None:
        _ckpt_sha8 = _loop_spec_sha8(spec.goal, config.verify_command)

    iterations: list[IterationContract] = []
    recorded_memory_ids: list[str] = []
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    consecutive_losses: int = 0
    escalation_level: int = 0
    last_loss: IterationContract | None = None
    signature_counts: dict[str, int] = {}
    # Circuit-breaker state.
    consecutive_same_error: int = 0
    last_error_head: str | None = None
    # Consecutive iterations that passed verify but changed nothing (vacuous).
    consecutive_noops: int = 0

    # Restore prior state when resuming from checkpoint.
    _resume_from: int = 1  # first iteration index to execute (1 = start fresh)
    if resume and checkpoint_store is not None and _ckpt_sha8 is not None:
        _saved = checkpoint_store.load(_ckpt_sha8)
        if _saved is not None:
            iterations = list(_saved.iterations)
            recorded_memory_ids = list(_saved.recorded_memory_ids)
            total_tokens = _saved.total_tokens
            total_cost_usd = _saved.total_cost_usd
            consecutive_losses = _saved.consecutive_losses
            escalation_level = _saved.escalation_level
            signature_counts = dict(_saved.signature_counts)
            consecutive_same_error = _saved.consecutive_same_error
            last_error_head = _saved.last_error_head
            # Restore last_loss from the most recent loss contract (if any).
            last_loss = next(
                (c for c in reversed(iterations) if c.outcome == "loss"),
                None,
            )
            # Continue from the iteration AFTER the last recorded one.
            _resume_from = (iterations[-1].iteration + 1) if iterations else 1
            _log.debug(
                "checkpoint resumed: %d prior iterations, continuing from %d",
                len(iterations),
                _resume_from,
            )

    wall_start: float = _clock()

    def _save_checkpoint() -> None:
        """Persist current loop state to the checkpoint store (best-effort)."""
        if checkpoint_store is None or _ckpt_sha8 is None:
            return
        state = CheckpointState(
            goal=spec.goal,
            verify_command=config.verify_command,
            iterations=list(iterations),
            recorded_memory_ids=list(recorded_memory_ids),
            total_tokens=total_tokens,
            total_cost_usd=total_cost_usd,
            consecutive_losses=consecutive_losses,
            escalation_level=escalation_level,
            signature_counts=dict(signature_counts),
            consecutive_same_error=consecutive_same_error,
            last_error_head=last_error_head,
        )
        checkpoint_store.save(_ckpt_sha8, state)

    def _clear_checkpoint() -> None:
        """Remove the checkpoint (called on terminal stop)."""
        if checkpoint_store is not None and _ckpt_sha8 is not None:
            checkpoint_store.clear(_ckpt_sha8)

    def _make_result(
        converged: bool,
        stop_reason: str,
    ) -> LoopResult:
        """Build the LoopResult, handle worktree teardown, and manage checkpoint."""
        if _provider is not None and _worktree_path is not None:
            _provider.teardown(_worktree_path, keep=converged)
        # Clear checkpoint on any terminal stop (converged or exhausted).
        # A partial stop (budget/cost/wall-time) also clears so callers that do
        # NOT want resume semantics get a clean slate.  The checkpoint was
        # already saved after the last iteration; clearing it here is safe
        # because the caller has the full LoopResult in memory.
        # Exception: we do NOT clear so the caller can resume — the loop
        # itself clears only on truly terminal stops (converged, max-iterations,
        # no-progress, duplicate-action, repeated-error).  Resumable stops
        # (budget, cost, wall-time) leave the checkpoint in place.
        _resumable_stops = {"budget", "cost", "wall-time"}
        if stop_reason not in _resumable_stops:
            _clear_checkpoint()
        return LoopResult(
            iterations=iterations,
            converged=converged,
            stop_reason=stop_reason,
            recorded_memory_ids=recorded_memory_ids,
            total_tokens=total_tokens,
            total_cost_usd=total_cost_usd if total_cost_usd > 0 else None,
        )

    # Build the iteration range.  When resuming, the range starts AFTER the
    # already-completed iterations so we never re-run them.  The upper bound
    # stays at config.max_iterations so the total budget is unchanged.
    _iter_range = range(_resume_from, config.max_iterations + 1)

    for i in _iter_range:
        # Budget check before spending more tokens.
        if config.budget_tokens is not None and total_tokens >= config.budget_tokens:
            return _make_result(False, "budget")

        # Cost limit check before each iteration.
        if config.max_cost_usd is not None and total_cost_usd >= config.max_cost_usd:
            return _make_result(False, "cost")

        # Wall-time limit check before each iteration.
        if config.max_wall_seconds is not None:
            elapsed = _clock() - wall_start
            if elapsed >= config.max_wall_seconds:
                return _make_result(False, "wall-time")

        # External abort signal check — checked before spending any tokens.
        if should_continue is not None and not should_continue():
            return _make_result(False, "aborted")

        # Build the memory-grounded prompt.
        brief = _build_brief(storage, spec.goal, last_loss, escalation_level)
        prompt = (
            f"## Goal\n\n{spec.goal}\n\n"
            + (
                f"## Success criteria\n\n{spec.success_criteria}\n\n"
                if spec.success_criteria
                else ""
            )
            + brief
        )

        # Capture the working-tree signature BEFORE the agent acts, so we can
        # tell whether this iteration actually changed anything.
        pre_sig = _probe()

        # Agent acts.
        agent_result: AgentRunResult = agent_runner(prompt, escalation_level=escalation_level)
        if agent_result.tokens is not None:
            total_tokens += agent_result.tokens
        if agent_result.cost_usd is not None:
            total_cost_usd += agent_result.cost_usd

        # --- Hard agent failure (auth/API/OS error) ---
        # The agent invocation itself failed, so no real work happened.  Record
        # the iteration as a forced loss (NEVER a win, even if a lenient verify
        # would pass against pre-existing state) and stop loudly.  This closes
        # the hole where a 401/api-error could be parsed as ordinary output and
        # a passing verifier reported the run as ``verified``.
        if agent_result.error is not None:
            error_contract = IterationContract(
                iteration=i,
                prediction=agent_result.prediction,
                action_summary=agent_result.output[:400],
                files_touched=list(agent_result.files_touched),
                verify_passed=False,
                verify_output=f"[agent-error] {agent_result.error}"[:_MAX_VERIFY_OUTPUT],
                outcome="loss",
                tokens=agent_result.tokens,
            )
            iterations.append(error_contract)
            mid = _record_loss(storage, spec.goal, error_contract, ref_now)
            if mid is not None:
                recorded_memory_ids.append(mid)
            _save_checkpoint()
            return _make_result(False, "agent-error")

        # Verify.
        verify_outcome: VerifyOutcome = verify_runner(config.verify_command)

        # --- Vacuous-pass gate ---
        # Determine whether the agent actually changed the working tree.  A
        # verify pass with zero changes is vacuous: the verifier only exercised
        # pre-existing state, so it proves nothing about the goal.  This closes
        # the false-green hole where an agent's edits are blocked (e.g. pending
        # permission approval) yet a lenient verifier still exits 0 and the loop
        # stamps a "verified / converged" receipt.
        post_sig = _probe()
        if pre_sig is None or post_sig is None:
            made_changes: bool | None = None  # undeterminable (not a git repo)
        else:
            made_changes = post_sig != pre_sig

        vacuous_pass = verify_outcome.passed and made_changes is False
        if vacuous_pass:
            verify_passed = False
            outcome: str = "loss"
            verify_output_text = (
                "[no-op] agent produced no file changes this iteration; the "
                "verify command passed but the result is vacuous — it reflects "
                "pre-existing state, not that the goal was addressed.\n\n" + verify_outcome.output
            )
        else:
            verify_passed = verify_outcome.passed
            outcome = "win" if verify_outcome.passed else "loss"
            verify_output_text = verify_outcome.output

        # --- Scope gate ---
        # Even when verify passes AND real changes were made, those changes must
        # stay within the declared scope (allowed_paths) and must not touch any
        # protected file (protected_paths).  A scope violation forces a loss and
        # prepends a diagnostic message so the agent knows what to fix.
        # The gate is skipped when both lists are empty (default) so backward
        # compatibility is 100% preserved.
        if outcome == "win" and (config.allowed_paths or config.protected_paths):
            if pre_sig is None or post_sig is None:
                # Scope constraints are declared but the working-tree change probe
                # is unavailable (not a git repo / git failed), so we cannot confirm
                # the change stayed inside allowed_paths and never touched a protected
                # path.  protected_paths is a security "must NEVER touch" list, so an
                # unverifiable win must fail safe (forced loss), not silently pass.
                verify_passed = False
                outcome = "loss"
                verify_output_text = (
                    "[scope-unverifiable] scope constraints are declared "
                    "(allowed_paths/protected_paths) but the working-tree change probe "
                    "is unavailable, so the change set cannot be confirmed to stay in "
                    "scope; failing safe.\n\n" + verify_output_text
                )
            else:
                changed_files = _changed_files_delta(pre_sig, post_sig)
                violation = _scope_violation(
                    changed_files,
                    config.allowed_paths,
                    config.protected_paths,
                )
                if violation is not None:
                    verify_passed = False
                    outcome = "loss"
                    verify_output_text = (
                        f"[scope-violation] {violation}. The verify command passed but "
                        "the agent modified files outside the declared scope.\n\n"
                        + verify_output_text
                    )

        contract = IterationContract(
            iteration=i,
            prediction=agent_result.prediction,
            action_summary=agent_result.output[:400],
            files_touched=list(agent_result.files_touched),
            verify_passed=verify_passed,
            verify_output=verify_output_text[:_MAX_VERIFY_OUTPUT],
            outcome=outcome,  # type: ignore[arg-type]
            tokens=agent_result.tokens,
        )
        iterations.append(contract)

        if outcome == "win":
            # WIN: record success memory first, then persist checkpoint (with
            # win contract) so a crash after memory write but before return
            # can be detected.  _make_result will clear the checkpoint.
            consecutive_noops = 0
            mid = _record_win(storage, spec.goal, contract, ref_now)
            recorded_memory_ids.append(mid)
            _save_checkpoint()
            return _make_result(True, "converged")
        else:
            # LOSS: record dead-end so next iteration's guard blocks it.
            # Transient/environment failures are NOT recorded as dead-ends.
            mid = _record_loss(storage, spec.goal, contract, ref_now)
            if mid is not None:
                recorded_memory_ids.append(mid)
            consecutive_losses += 1
            last_loss = contract

            # Escalate after threshold consecutive losses.
            if consecutive_losses >= config.escalation_threshold:
                escalation_level += 1
                consecutive_losses = 0

            # --- Circuit breaker 0: no-changes (vacuous pass) ---
            # A verify that passed while the agent changed nothing means the
            # agent is stuck (blocked edits, no-op output).  Stop loudly after
            # a bounded number of consecutive no-ops so we never burn cost on a
            # loop that cannot make progress and never mistake it for success.
            if vacuous_pass:
                consecutive_noops += 1
                if config.no_change_limit > 0 and consecutive_noops >= config.no_change_limit:
                    _save_checkpoint()
                    return _make_result(False, "no-changes")
            else:
                consecutive_noops = 0

            sig = _iteration_signature(contract)

            # --- Circuit breaker 1: duplicate-action ---
            # Fires when the EXACT same (files_touched, verify_output_head)
            # signature repeats >= duplicate_action_limit times.  This is
            # tighter than no-progress (which counts a sliding window of
            # distinct signatures); this fires only on exact repetitions.
            if config.duplicate_action_limit > 0:
                signature_counts[sig] = signature_counts.get(sig, 0) + 1
                if signature_counts[sig] >= config.duplicate_action_limit:
                    _save_checkpoint()
                    return _make_result(False, "duplicate-action")
            else:
                signature_counts[sig] = signature_counts.get(sig, 0) + 1

            # --- Circuit breaker 2: repeated-error ---
            # Fires when the verify output HEAD is identical for N consecutive
            # losses in a row (regardless of which files were touched).
            error_head = _verify_output_head(contract.verify_output)
            if config.repeated_error_limit > 0:
                if error_head == last_error_head:
                    consecutive_same_error += 1
                else:
                    consecutive_same_error = 1
                    last_error_head = error_head
                if consecutive_same_error >= config.repeated_error_limit:
                    _save_checkpoint()
                    return _make_result(False, "repeated-error")
            else:
                last_error_head = error_head

            # --- Existing no-progress detection (slower, sliding window) ---
            if signature_counts[sig] >= config.no_progress_window:
                _save_checkpoint()
                return _make_result(False, "no-progress")

            # Persist checkpoint after this loss iteration so a resume can
            # continue from the next iteration.
            _save_checkpoint()

    # max-iterations stop: clear checkpoint (terminal).
    _save_checkpoint()
    return _make_result(False, "max-iterations")


# Keep utc_now import for callers who might use it.
__all__ = [
    "_build_brief",
    "_changed_files_delta",
    "_classify_failure_cause",
    "_default_agent_runner",
    "_default_verify_runner",
    "_files_from_git_status",
    "_iteration_signature",
    "_scope_violation",
    "_verify_output_head",
    "run_loop",
]
# 'should_continue' is a new keyword-only parameter added to run_loop (default None).
# Existing callers are unaffected — passing None is identical to omitting it.

_ = utc_now  # referenced above; suppress unused-import
