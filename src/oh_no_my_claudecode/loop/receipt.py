"""Tamper-evident run receipt for onmc loop.

A ``RunReceipt`` captures a complete, tamper-evident record of one loop run:
- All iteration hashes chained together (SHA-256 hash chain).
- Git tree SHA and diff SHA so external auditors can reproduce the exact repo
  state the loop produced.
- Verifier command and final exit code.
- Token, cost, and wall-time accounting.

Tamper-evidence is provided via the hash chain and git SHAs only.
Cryptographic signing (e.g. Sigstore) is deliberately out of scope for this
release — "tamper-evident" here means that any post-hoc change to iteration
data produces a different ``receipt_hash``.

Design notes
------------
- ``build_receipt`` is a pure function.  It accepts all timestamps and SHA
  inputs as parameters so tests can inject deterministic values.
- ``write_receipt`` derives its filename from the receipt content (not from
  wall-clock time) so receipts are idempotent when replayed.
- Git SHAs are computed via an injectable ``CommandRunner`` so tests never
  need a real git repository.
- The hash chain construction:
    h_0 = sha256("" + sig_1 + str(vp_1) + files_1 + str(tokens_1))
    h_i = sha256(h_{i-1} + sig_i + str(vp_i) + files_i + str(tokens_i))
  where ``sig_i`` is the iteration signature from the engine and ``vp_i`` is
  ``verify_passed``.  ``receipt_hash`` = final chain value (hex, 64 chars).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from oh_no_my_claudecode.loop.models import LoopConfig, LoopResult, LoopSpec

# ---------------------------------------------------------------------------
# Injectable subprocess boundary (mirrors adapters.py CommandRunner)
# ---------------------------------------------------------------------------

#: Callable signature: ``(cmd: list[str], cwd: str, timeout: int) -> tuple[int, str]``
#: Returns (returncode, stdout).
GitCommandRunner = Callable[[list[str], str, int], tuple[int, str]]


def _default_git_runner(cmd: list[str], cwd: str, timeout: int) -> tuple[int, str]:
    """Default GitCommandRunner — spawns a real subprocess."""
    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return 1, ""


# ---------------------------------------------------------------------------
# Receipt schema
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = "2"
_RECEIPT_GIT_TIMEOUT = 15  # seconds


@dataclass
class RunReceipt:
    """Tamper-evident record of one onmc loop run.

    Fields
    ------
    schema_version:
        Monotonic integer string for forward-compatible parsing.
    goal:
        The loop goal (truncated to 500 chars).
    agent:
        The agent selector used (e.g. "claude", "codex", or "dry-run").
    model:
        Optional model name when available (e.g. "claude-opus-4-5").
    verified:
        True iff the loop converged AND the final iteration verify passed.
    stop_reason:
        The stop_reason from LoopResult.
    iterations:
        Number of iterations completed.
    tokens_used:
        Total tokens consumed across all iterations.
    cost_usd:
        Total USD cost when reported by the adapter; None otherwise.
    wall_seconds:
        Wall-clock seconds for the run (injected by caller).
    verifier_command:
        The shell command used to verify each iteration.
    verifier_final_exit:
        Exit code of the final verify invocation; None when no iterations ran.
    git_tree_sha:
        SHA of the current git tree (HEAD^{tree}).  None when git is unavailable.
    diff_sha:
        SHA-256 of ``git diff`` output capturing uncommitted changes.  None
        when git is unavailable.
    loop_spec_sha:
        SHA-256 of ``goal + verify_command``.  Uniquely identifies this run's
        inputs across runs.
    output_digest:
        SHA-256 of concatenated (truncated) verify outputs from all iterations.
    onmc_version:
        The installed oh-no-my-claudecode version string (or "unknown").
    started_at:
        ISO-8601 UTC timestamp when the run began (injectable; may be None).
    ended_at:
        ISO-8601 UTC timestamp when the run ended (injectable; may be None).
    iteration_hashes:
        Per-iteration SHA-256 hash chain links (64-char hex each).
    receipt_hash:
        SHA-256 hash chain head: final h_i value.  Changes if ANY iteration
        data changes → tamper evidence.

    Reproducibility envelope (schema_version "2")
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    model_version:
        Resolved model/version string passed to the agent adapter; None when
        the adapter does not surface this.  Never fabricated — only set when
        the caller supplies a non-None value.
    prompt_hash:
        SHA-256 of ``spec.goal``.  Identifies the exact natural-language prompt
        that seeded the run.  Same goal text → same hash, regardless of other
        config.
    tool_defs_hash:
        SHA-256 of ``verify_command || ":" || agent``.  Captures the
        "tools surface" of the run — what verifier and what agent were wired
        up.  None only when neither is available (in practice always set).
    config_hash:
        SHA-256 of the reproducibility-relevant LoopConfig knobs serialised as
        ``max_iterations|budget_tokens|max_cost_usd|max_wall_seconds|verify_command|escalation_threshold|no_progress_window``.
        Same config → same hash; any knob change → different hash.
    python_version:
        ``sys.version_info`` formatted as ``"major.minor"`` (e.g. ``"3.12"``).
        Aids reproducibility analysis across Python upgrades.
    platform:
        ``sys.platform`` value (e.g. ``"darwin"``, ``"linux"``).
    """

    schema_version: str
    goal: str
    agent: str
    model: str | None
    verified: bool
    stop_reason: str
    iterations: int
    tokens_used: int
    cost_usd: float | None
    wall_seconds: float
    verifier_command: str
    verifier_final_exit: int | None
    git_tree_sha: str | None
    diff_sha: str | None
    loop_spec_sha: str
    output_digest: str
    onmc_version: str
    started_at: str | None
    ended_at: str | None
    iteration_hashes: list[str] = field(default_factory=list)
    receipt_hash: str = ""
    # Reproducibility envelope — schema_version "2" additions (all optional for
    # backward-compatible reading of old receipts that lack these keys).
    model_version: str | None = None
    prompt_hash: str | None = None
    tool_defs_hash: str | None = None
    config_hash: str | None = None
    python_version: str | None = None
    platform: str | None = None


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------


def _sha256_hex(data: str) -> str:
    """Return the SHA-256 hex digest of *data* (UTF-8 encoded)."""
    return hashlib.sha256(data.encode()).hexdigest()


def _build_hash_chain(result: LoopResult) -> tuple[list[str], str]:
    """Build the iteration hash chain and return ``(iteration_hashes, receipt_hash)``.

    Each link h_i = sha256(h_{i-1} || iteration_signature_i || verify_passed_i
                           || files_i || tokens_i)
    h_0 has an empty prev-hash.  The chain is deterministic given the result.
    """
    prev_hash = ""
    hashes: list[str] = []
    for contract in result.iterations:
        files_str = ",".join(sorted(contract.files_touched))
        tokens_str = str(contract.tokens) if contract.tokens is not None else "none"
        # iteration_signature mirrors engine._iteration_signature for consistency
        sig = _sha256_hex(
            f"{files_str}||{contract.verify_output[:200]}"
        )[:16]
        link_data = (
            f"{prev_hash}"
            f"|{sig}"
            f"|{contract.verify_passed}"
            f"|{files_str}"
            f"|{tokens_str}"
        )
        h_i = _sha256_hex(link_data)
        hashes.append(h_i)
        prev_hash = h_i

    receipt_hash = prev_hash if prev_hash else _sha256_hex("empty")
    return hashes, receipt_hash


# ---------------------------------------------------------------------------
# Git SHA helpers
# ---------------------------------------------------------------------------


def _get_git_tree_sha(
    repo_root: str,
    runner: Callable[[list[str], str, int], tuple[int, str]],
) -> str | None:
    """Return the SHA of the current git tree (HEAD^{tree}).

    Returns ``None`` when git is unavailable or the repo has no commits.
    """
    rc, stdout = runner(
        ["git", "-C", repo_root, "rev-parse", "HEAD^{tree}"],
        repo_root,
        _RECEIPT_GIT_TIMEOUT,
    )
    if rc == 0 and stdout.strip():
        return stdout.strip()
    return None


def _get_git_diff_sha(
    repo_root: str,
    runner: Callable[[list[str], str, int], tuple[int, str]],
) -> str | None:
    """Return SHA-256 of ``git diff`` output (uncommitted changes).

    An empty diff (clean working tree) hashes to a well-known constant so the
    receipt still records that the tree was clean.  Returns ``None`` only when
    git itself is unavailable.
    """
    rc, stdout = runner(
        ["git", "-C", repo_root, "diff"],
        repo_root,
        _RECEIPT_GIT_TIMEOUT,
    )
    if rc != 0:
        return None
    return _sha256_hex(stdout)


# ---------------------------------------------------------------------------
# Reproducibility-envelope hash helpers
# ---------------------------------------------------------------------------


def _build_prompt_hash(spec: LoopSpec) -> str:
    """Return SHA-256 of the run's goal text.

    Hashed input: ``spec.goal`` (UTF-8).
    Same goal text → same hash across all runs and machines.
    """
    return _sha256_hex(spec.goal)


def _build_tool_defs_hash(verify_command: str, agent: str) -> str:
    """Return SHA-256 capturing the tools surface of the run.

    Hashed input: ``verify_command + ":" + agent`` (UTF-8).
    Covers the verifier (what is run to confirm success) and the agent
    identity (which CLI adapter is wired up).
    """
    return _sha256_hex(f"{verify_command}:{agent}")


def _build_config_hash(config: LoopConfig) -> str:
    """Return SHA-256 of the reproducibility-relevant LoopConfig knobs.

    Hashed input (pipe-separated, None → "None")::

        max_iterations|budget_tokens|max_cost_usd|max_wall_seconds|
        verify_command|escalation_threshold|no_progress_window|
        duplicate_action_limit|repeated_error_limit

    Any change to any of these knobs produces a different hash, enabling
    reproducibility checks between runs.
    """
    parts = "|".join(
        [
            str(config.max_iterations),
            str(config.budget_tokens),
            str(config.max_cost_usd),
            str(config.max_wall_seconds),
            config.verify_command,
            str(config.escalation_threshold),
            str(config.no_progress_window),
            str(config.duplicate_action_limit),
            str(config.repeated_error_limit),
        ]
    )
    return _sha256_hex(parts)


def _runtime_python_version() -> str:
    """Return ``sys.version_info`` as ``"major.minor"``."""
    info = sys.version_info
    return f"{info.major}.{info.minor}"


def _runtime_platform() -> str:
    """Return ``sys.platform``."""
    return sys.platform


# ---------------------------------------------------------------------------
# Pure builder
# ---------------------------------------------------------------------------


def build_receipt(
    result: LoopResult,
    spec: LoopSpec,
    config: LoopConfig,
    *,
    repo_root: str,
    agent: str,
    model: str | None,
    wall_seconds: float,
    onmc_version: str,
    started_at: str | None = None,
    ended_at: str | None = None,
    verifier_final_exit: int | None = None,
    git_runner: Callable[[list[str], str, int], tuple[int, str]] | None = None,
) -> RunReceipt:
    """Build a tamper-evident run receipt from a completed loop result.

    This function is pure and deterministic given its inputs.  All external
    state (git SHAs, timestamps) must be passed in — nothing is queried
    internally beyond the injected ``git_runner``.

    Parameters
    ----------
    result:
        The completed LoopResult.
    spec:
        The LoopSpec used for this run.
    config:
        The LoopConfig used for this run.
    repo_root:
        Absolute path to the repository root (string, for subprocess CWD).
    agent:
        Agent selector string (e.g. "claude", "codex", "dry-run").
    model:
        Optional model name.
    wall_seconds:
        Elapsed wall-clock seconds for the run.
    onmc_version:
        Installed onmc package version string.
    started_at:
        Optional ISO-8601 UTC start timestamp.
    ended_at:
        Optional ISO-8601 UTC end timestamp.
    verifier_final_exit:
        Exit code of the final verify call, or None when no real verify ran.
    git_runner:
        Injectable git command runner.  Defaults to the real subprocess runner.

    Returns
    -------
    RunReceipt
        A fully populated, tamper-evident receipt.
    """
    runner = git_runner if git_runner is not None else _default_git_runner

    # Compute git SHAs.
    git_tree_sha = _get_git_tree_sha(repo_root, runner)
    diff_sha = _get_git_diff_sha(repo_root, runner)

    # loop_spec_sha — identifies the inputs to this run.
    loop_spec_sha = _sha256_hex(f"{spec.goal}||{config.verify_command}")

    # output_digest — sha256 of all verify outputs concatenated (truncated per iteration).
    all_verify_output = "".join(
        c.verify_output[:200] for c in result.iterations
    )
    output_digest = _sha256_hex(all_verify_output)

    # Verified = converged AND final iteration verify_passed.
    verified = result.converged and bool(
        result.iterations and result.iterations[-1].verify_passed
    )

    # Derive verifier_final_exit from the result if not explicitly provided.
    resolved_final_exit = verifier_final_exit
    if resolved_final_exit is None and result.iterations:
        last = result.iterations[-1]
        resolved_final_exit = 0 if last.verify_passed else 1

    # Build hash chain.
    iteration_hashes, receipt_hash = _build_hash_chain(result)

    # Reproducibility envelope (schema_version "2").
    prompt_hash = _build_prompt_hash(spec)
    tool_defs_hash = _build_tool_defs_hash(config.verify_command, agent)
    config_hash = _build_config_hash(config)

    return RunReceipt(
        schema_version=_SCHEMA_VERSION,
        goal=spec.goal[:500],
        agent=agent,
        model=model,
        verified=verified,
        stop_reason=result.stop_reason,
        iterations=len(result.iterations),
        tokens_used=result.total_tokens,
        cost_usd=result.total_cost_usd,
        wall_seconds=round(wall_seconds, 3),
        verifier_command=config.verify_command,
        verifier_final_exit=resolved_final_exit,
        git_tree_sha=git_tree_sha,
        diff_sha=diff_sha,
        loop_spec_sha=loop_spec_sha,
        output_digest=output_digest,
        onmc_version=onmc_version,
        started_at=started_at,
        ended_at=ended_at,
        iteration_hashes=iteration_hashes,
        receipt_hash=receipt_hash,
        model_version=model,  # None when caller does not know the version
        prompt_hash=prompt_hash,
        tool_defs_hash=tool_defs_hash,
        config_hash=config_hash,
        python_version=_runtime_python_version(),
        platform=_runtime_platform(),
    )


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_receipt(repo_root: str | Path, receipt: RunReceipt) -> Path:
    """Write *receipt* to ``.agent-memory/receipts/`` and return the path.

    The filename is derived from content (loop_spec_sha8 + receipt_hash8) so
    the same run produces the same filename deterministically.  The directory
    is created if it does not exist.

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root.
    receipt:
        The RunReceipt to persist.

    Returns
    -------
    Path
        Absolute path to the written JSON file.
    """
    receipts_dir = Path(repo_root) / ".agent-memory" / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)

    spec_short = receipt.loop_spec_sha[:8]
    hash_short = receipt.receipt_hash[:8]
    filename = f"run-{spec_short}-{hash_short}.json"
    dest = receipts_dir / filename

    dest.write_text(
        json.dumps(asdict(receipt), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return dest


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "RunReceipt",
    "build_receipt",
    "write_receipt",
]
