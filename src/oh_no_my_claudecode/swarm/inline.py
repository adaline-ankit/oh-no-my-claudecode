"""In-session subagent swarm: token-free fan-out driven by Claude Code.

Two swarm execution models share the same ``.onmc/swarm/<id>/`` state layout:

- **Process swarm** (``orchestrator.run_swarm``) shells out to N independent
  ``claude -p`` / ``codex`` / ``opencode`` PROCESSES.  Each new process must
  authenticate to its model backend on its own — so a credential (keychain
  login or an exported token) is required wherever those processes run.

- **Inline swarm** (this module) is driven by the *Claude Code session itself*.
  The model fans out subagents via its Agent tool; those subagents inherit the
  session's authentication, so **no API key or OAuth token is ever needed.**
  onmc is NOT the spawner here — it is the ACCOUNTABILITY LEDGER:

    1. ``plan_inline_swarm`` allocates a swarm id + manifest (units "pending",
       ``mode="inline"``) and returns the abort-sentinel path.  The model reads
       this, fans subagents out (bounded by Claude Code's own concurrency cap),
       checking the abort sentinel between batches.
    2. ``record_inline_unit`` writes a tamper-evident receipt for each finished
       unit and atomically updates the manifest.

Because the state layout is identical, ``onmc swarm status|list|abort`` work
unchanged for both modes.  ``record_inline_unit`` reuses ``build_receipt`` so an
inline unit's receipt is exactly as auditable as a process unit's (git tree/diff
SHA, hash chain, reproducibility envelope, honest ``verified`` flag).
"""

from __future__ import annotations

import contextlib
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.swarm.orchestrator import (
    _abort_path,
    _manifest_path,
    _swarm_dir,
)


def _now_iso(now: datetime | None) -> str:
    return (now if now is not None else datetime.now(UTC)).isoformat()


def plan_inline_swarm(
    repo_root: Path,
    goals: list[str],
    *,
    concurrency: int,
    agent: str = "claude-code-subagent",
    swarm_id: str | None = None,
    now: datetime | None = None,
    claim_paths: list[list[str]] | None = None,
    auto_model_report: Any | None = None,
) -> dict[str, Any]:
    """Allocate an inline (subagent-driven) swarm and write its manifest.

    Parameters
    ----------
    repo_root:
        Repository root.  State lives under ``.onmc/swarm/<id>/``.
    goals:
        One goal string per unit.  Empty list is rejected by the caller (CLI).
    concurrency:
        Recommended fan-out width.  This is advisory for the model — Claude Code
        caps truly-simultaneous subagents at roughly 10, so the model batches.
    agent:
        Recorded agent label for the units' receipts.  Defaults to
        ``"claude-code-subagent"`` (the inline executor).
    swarm_id:
        Optional explicit id (tests inject a deterministic value).  When
        ``None`` a random 16-hex-char id is generated.
    now:
        Injectable timestamp for ``started_at``.
    claim_paths:
        Optional per-unit list of repo-relative paths the unit intends to edit.
        When supplied (and a unit's list is non-empty) a best-effort lease is
        acquired via the claim ledger so concurrent units don't stomp on the
        same files.  Lease acquisition is NON-FATAL: a conflict or any error is
        recorded on the unit but never blocks planning.
    auto_model_report:
        Optional :class:`~oh_no_my_claudecode.flywheel.analyze.FlywheelReport`.
        When supplied, each unit is annotated (via
        :func:`oh_no_my_claudecode.swarm.auto_model.annotate_units_with_models`)
        with ``suggested_model`` / ``suggested_model_confidence`` — purely
        advisory fields recorded on the manifest and the returned unit dicts.
        When ``None`` (the default), these fields are simply absent — existing
        callers and manifests are byte-for-byte unaffected.

    Returns
    -------
    dict
        ``{swarm_id, mode, concurrency, agent, abort_path, manifest_path,
        state_dir, units: [{id, goal}]}`` — everything the model needs to drive
        the fan-out and later record each unit.  When ``auto_model_report`` is
        given, each unit dict additionally carries ``suggested_model`` and
        ``suggested_model_confidence``.
    """
    sid = swarm_id if swarm_id is not None else secrets.token_hex(8)
    started_at = _now_iso(now)

    units = [{"id": f"unit-{i:04d}", "goal": g} for i, g in enumerate(goals)]

    if auto_model_report is not None:
        from oh_no_my_claudecode.swarm.auto_model import annotate_units_with_models

        units = annotate_units_with_models(units, auto_model_report)

    claimed = _acquire_unit_claims(repo_root, sid, units, claim_paths)

    manifest: dict[str, Any] = {
        "swarm_id": sid,
        "mode": "inline",
        "started_at": started_at,
        "agent": agent,
        "concurrency": concurrency,
        "swarm_max_cost_usd": None,
        "units": {
            u["id"]: {
                "goal": u["goal"][:200],
                "status": "pending",
                "cost_usd": 0.0,
                "receipt_path": None,
                "error": None,
                "verified": None,
                "claimed_paths": claimed.get(u["id"], []),
                **(
                    {
                        "suggested_model": u.get("suggested_model"),
                        "suggested_model_confidence": u.get("suggested_model_confidence"),
                    }
                    if auto_model_report is not None
                    else {}
                ),
            }
            for u in units
        },
    }
    _manifest_path(repo_root, sid).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Self-exemption marker: while this swarm is fanning out subagents, the
    # ``onmc wrap`` Task intercept must let those native spawns through (onmc is
    # the spawner). The marker records ``started_at`` so the intercept can age
    # it out (see ``wrap.logic.swarm_active``). Best-effort: a write failure
    # must never break swarm planning.
    with contextlib.suppress(OSError):
        (_swarm_dir(repo_root, sid) / "ACTIVE").write_text(started_at, encoding="utf-8")

    return {
        "swarm_id": sid,
        "mode": "inline",
        "concurrency": concurrency,
        "agent": agent,
        "abort_path": str(_abort_path(repo_root, sid)),
        "manifest_path": str(_manifest_path(repo_root, sid)),
        "state_dir": str(_swarm_dir(repo_root, sid)),
        "units": units,
    }


def record_inline_unit(
    repo_root: Path,
    swarm_id: str,
    unit_id: str,
    *,
    goal: str,
    summary: str,
    verified: bool,
    aborted: bool = False,
    files_touched: list[str] | None = None,
    tokens: int | None = None,
    cost_usd: float | None = None,
    agent: str = "claude-code-subagent",
    onmc_version: str | None = None,
    now: datetime | None = None,
    git_runner: Callable[[list[str], str, int], tuple[int, str]] | None = None,
    verifier: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Record one finished inline unit: write a receipt + update the manifest.

    Honest status (mirrors the process swarm): a unit is ``done`` ONLY when the
    subagent's work was ``verified``; ``failed`` when it was not, and
    ``aborted`` when it was cut short.

    Two trust models for ``verified``:

    - **Caller attestation (default).** ``verified`` flows straight into the
      receipt's ``verified`` flag — the caller asserts the unit met its success
      criteria.
    - **Honest gate (``verifier`` supplied).** When a ``verifier`` callable is
      injected, the passed-in ``verified`` is IGNORED and the verdict is taken
      from ``verifier()`` — the real per-unit quality gate (see
      ``swarm/staff.py``).  This is staff-engineer mode: a unit that did not
      really build (empty diff) or fails the gate CANNOT be recorded as a
      verified success even if the caller passed ``--verified``.

    The ``verifier`` is not consulted for aborted units (an abort is terminal).

    Returns
    -------
    dict
        ``{unit_id, status, stop_reason, verified, receipt_path}``.
    """
    from oh_no_my_claudecode import __version__ as _pkg_version
    from oh_no_my_claudecode.loop.models import (
        IterationContract,
        LoopConfig,
        LoopResult,
        LoopSpec,
    )
    from oh_no_my_claudecode.loop.receipt import build_receipt, write_receipt

    if verifier is not None and not aborted:
        # The honest gate overrides the caller's attestation: verified reflects
        # the REAL quality-gate result, not the caller's say-so.
        verified = verifier()

    if aborted:
        status, stop_reason = "aborted", "aborted"
    elif verified:
        status, stop_reason = "done", "converged"
    else:
        status, stop_reason = "failed", "subagent-failed"

    files = list(files_touched or [])
    ts = _now_iso(now)

    # Synthesize a single-iteration LoopResult so the standard tamper-evident
    # receipt machinery applies unchanged.  verify_passed == verified means
    # build_receipt's own `verified = converged and last.verify_passed` agrees.
    contract = IterationContract(
        iteration=1,
        prediction=summary[:120],
        action_summary=summary[:400],
        files_touched=files,
        verify_passed=verified,
        verify_output=summary[:2000],
        outcome="win" if verified else "loss",
        tokens=tokens,
    )
    result = LoopResult(
        iterations=[contract],
        converged=verified,
        stop_reason=stop_reason,
        total_tokens=tokens or 0,
        total_cost_usd=cost_usd,
    )
    spec = LoopSpec(goal=goal)
    config = LoopConfig(verify_command="<subagent>")

    receipt = build_receipt(
        result,
        spec,
        config,
        repo_root=str(repo_root),
        agent=agent,
        model=None,
        wall_seconds=0.0,
        onmc_version=onmc_version or _pkg_version,
        started_at=ts,
        ended_at=ts,
        git_runner=git_runner,
    )
    receipt_path = write_receipt(repo_root, receipt)

    _update_inline_manifest(
        repo_root,
        swarm_id,
        unit_id,
        status=status,
        verified=verified,
        cost_usd=cost_usd or 0.0,
        receipt_path=receipt_path,
        error=None if status != "failed" else (summary[:300] or "subagent did not verify"),
    )

    return {
        "unit_id": unit_id,
        "status": status,
        "stop_reason": stop_reason,
        "verified": verified,
        "receipt_path": str(receipt_path),
    }


def _acquire_unit_claims(
    repo_root: Path,
    swarm_id: str,
    units: list[dict[str, str]],
    claim_paths: list[list[str]] | None,
) -> dict[str, list[str]]:
    """Best-effort, non-fatal per-unit path leases via the claim ledger.

    Returns a mapping of ``unit_id -> [successfully-claimed paths]``.  A unit
    with no declared paths, a lease conflict, or any ledger error simply gets an
    empty list — planning never fails because of claims.
    """
    if not claim_paths:
        return {}

    from oh_no_my_claudecode.claim import ClaimLedger

    ledger = ClaimLedger(repo_root)
    claimed: dict[str, list[str]] = {}
    for idx, unit in enumerate(units):
        paths = claim_paths[idx] if idx < len(claim_paths) else []
        wanted = [p for p in paths if p and p.strip()]
        if not wanted:
            continue
        owner = f"swarm:{swarm_id}:{unit['id']}"
        try:
            result = ledger.acquire(owner, wanted)
        except (OSError, ValueError):
            continue
        if result.ok:
            claimed[unit["id"]] = [c.path for c in result.claims if c.owner == owner]
    return claimed


def _update_inline_manifest(
    repo_root: Path,
    swarm_id: str,
    unit_id: str,
    *,
    status: str,
    verified: bool,
    cost_usd: float,
    receipt_path: Path,
    error: str | None,
) -> None:
    """Read-modify-write one unit's entry in the manifest.

    Inline units are recorded by sequential ``onmc swarm record`` CLI calls
    (one OS process each), so a plain read-modify-write is sufficient — there is
    no shared in-process executor to race against.
    """
    mpath = _manifest_path(repo_root, swarm_id)
    try:
        manifest: dict[str, Any] = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    units = manifest.get("units", {})
    if unit_id in units:
        units[unit_id]["status"] = status
        units[unit_id]["verified"] = verified
        units[unit_id]["cost_usd"] = cost_usd
        units[unit_id]["receipt_path"] = str(receipt_path)
        units[unit_id]["error"] = error
        mpath.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
