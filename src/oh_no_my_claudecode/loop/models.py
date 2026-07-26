"""Data models for the onmc loop engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol


@dataclass
class LoopSpec:
    """Goal and success criteria for one loop run."""

    goal: str
    success_criteria: str = ""


@dataclass
class IterationContract:
    """The falsifiable prediction-outcome contract for one iteration."""

    iteration: int
    prediction: str
    action_summary: str
    files_touched: list[str]
    verify_passed: bool
    verify_output: str
    outcome: Literal["win", "loss"]
    tokens: int | None = None
    route_decision: dict[str, object] | None = None


@dataclass
class LoopResult:
    """Aggregated result from a completed loop run."""

    iterations: list[IterationContract] = field(default_factory=list)
    converged: bool = False
    stop_reason: str = ""
    recorded_memory_ids: list[str] = field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float | None = None
    worktree_path: str | None = None
    """Preserved isolated worktree containing a successful run, when applicable."""


@dataclass
class LoopConfig:
    """Runtime parameters for run_loop."""

    max_iterations: int = 10
    budget_tokens: int | None = None
    verify_command: str = "pytest"
    escalation_threshold: int = 3
    no_progress_window: int = 3
    max_cost_usd: float | None = None
    """Stop before the next iteration when cumulative cost exceeds this value."""
    max_wall_seconds: int | None = None
    """Stop when wall-clock elapsed seconds exceed this value."""
    duplicate_action_limit: int = 0
    """Stop with stop_reason='duplicate-action' when the SAME iteration signature
    (files_touched + verify_output_head) repeats this many times.  Fires faster
    than no_progress_window because it counts exact repetitions, not a sliding
    window of distinct signatures.  Default 0 = disabled (opt-in).  A value of
    2 is a good starting point for aggressive token-storm prevention."""
    repeated_error_limit: int = 0
    """Stop with stop_reason='repeated-error' when the verify-output head is
    identical for this many *consecutive* losses in a row.  Default 0 = disabled
    (opt-in).  A value of 3 is a good starting point."""
    no_change_limit: int = 2
    """Stop with stop_reason='no-changes' after this many *consecutive* iterations
    where the verify command passed but the agent made NO file changes to the
    working tree.  Such a pass is vacuous — it reflects pre-existing state, not
    that the goal was addressed — so it can NEVER be counted as a convergence
    win.  Guards against the false-green failure mode where an agent's edits are
    blocked (e.g. pending permission approval) yet a lenient verifier still exits
    0.  Default 2 (allow one retry, e.g. after escalation).  0 disables the
    dedicated breaker, but a vacuous pass is still refused a win regardless."""
    isolate: bool = False
    """When True, run the loop agent inside a fresh ``git worktree add`` so all
    file changes are isolated from the caller's working tree.  On success
    (converged + verified) the worktree path is preserved and reported.  On
    failure the worktree is removed and no changes leak.  Degrades gracefully
    to in-place execution when ``git worktree add`` fails."""
    allowed_paths: list[str] = field(default_factory=list)
    """Optional scope allowlist — ``fnmatch``-style patterns for file paths that
    are permitted to be modified.  When non-empty, any file the agent modifies
    that does NOT match at least one pattern causes the iteration to be counted
    as a *loss* (even when the verify command exits 0).  Empty list (default)
    means no restriction — all paths are allowed.

    Examples: ``["src/**", "tests/**"]``, ``["*.py"]``.
    """
    protected_paths: list[str] = field(default_factory=list)
    """Optional scope blocklist — ``fnmatch``-style patterns for file paths that
    must NEVER be modified.  When non-empty, any match causes the iteration to
    be counted as a *loss* regardless of the verify outcome.  Empty list
    (default) means no files are protected.

    Examples: ``[".env", "secrets/*", "CLAUDE.md"]``.
    """


@dataclass
class AgentRunResult:
    """Output from one agent invocation."""

    output: str
    prediction: str
    files_touched: list[str]
    tokens: int | None = None
    cost_usd: float | None = None
    """Optional USD cost reported by the agent adapter (e.g. from Claude JSON total_cost_usd)."""
    error: str | None = None
    """Set when the agent invocation itself failed (auth/API/OS error) rather than
    producing real work.  An iteration with a non-None ``error`` can NEVER be
    counted as a win — the loop forces a loss and stops with
    ``stop_reason='agent-error'`` so an authentication/API failure can never be
    silently reported as ``verified``."""


@dataclass
class VerifyOutcome:
    """Result from one verify command invocation."""

    passed: bool
    output: str


class AgentRunner(Protocol):
    """Injectable agent runner protocol."""

    def __call__(self, prompt: str, *, escalation_level: int) -> AgentRunResult:
        """Run agent and return result."""
        ...


class VerifyRunner(Protocol):
    """Injectable verify runner protocol."""

    def __call__(self, command: str) -> VerifyOutcome:
        """Run verify command and return outcome."""
        ...


class ChangeProbe(Protocol):
    """Injectable working-tree change probe.

    Returns an opaque signature of the working tree's current state (e.g. the
    output of ``git status --porcelain``).  The engine captures the signature
    before and after each agent invocation; if it is unchanged AND the verify
    command passed, the pass is *vacuous* (the agent did no work) and is refused
    a convergence win.

    Returns ``None`` when the state cannot be determined (git unavailable or the
    path is not a git repository); the engine then skips the vacuous-pass gate
    and preserves legacy behaviour.
    """

    def __call__(self) -> str | None:
        """Return a working-tree signature, or ``None`` when undeterminable."""
        ...


class IsolationProvider(Protocol):
    """Injectable worktree isolation provider.

    Responsible for creating a git worktree, handing the path back, and
    cleaning it up on failure.  The protocol is separated from the engine so
    tests can exercise the isolation/rollback logic with a real temp git repo
    but a fake agent — without ever spawning a real agent subprocess.
    """

    def setup(self, repo_root: Path) -> Path | None:
        """Create an isolated worktree and return its path.

        Returns ``None`` when worktree creation fails (graceful degradation).
        The caller falls back to in-place execution in that case.
        """
        ...

    def teardown(self, worktree_path: Path, *, keep: bool) -> None:
        """Remove the worktree.

        When *keep* is ``True`` (converged run) the worktree is left on disk
        and only the git bookkeeping entry is removed.  When *keep* is
        ``False`` (failed run) the worktree directory is removed entirely so no
        partial changes leak.
        """
        ...
