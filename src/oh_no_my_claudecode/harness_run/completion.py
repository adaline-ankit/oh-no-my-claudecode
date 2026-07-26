"""Runtime completion gate for ``onmc run``.

This is the final authority between "the agent loop stopped" and "the run may
be reported as complete". The proof graph judges verifier evidence; this module
adds the runtime facts the proof graph cannot see by itself: observed repository
changes, final verifier signals, independent false-green checks, and policy /
reference-monitor outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass

from oh_no_my_claudecode.proof_graph import ProofAssessment

from .run_policy import RunPolicyDecision, VerifierSignal


@dataclass(frozen=True, slots=True)
class CompletionGateDecision:
    """Typed verdict for the final runtime completion gate."""

    proof_complete: bool
    policy_ok: bool
    assessment: ProofAssessment
    proof_reasons: tuple[str, ...]
    policy_reasons: tuple[str, ...]


def evaluate_completion_gate(
    *,
    loop_converged: bool,
    changed_files: tuple[str, ...],
    verifier_signals: tuple[VerifierSignal, ...],
    proof: ProofAssessment,
    policy: RunPolicyDecision,
    monitor_blocked: bool,
    verifier_false_green: bool,
) -> CompletionGateDecision:
    """Decide whether a run has enough evidence to be called complete.

    A passing verifier is not enough: the harness also requires a non-vacuous
    observed repository change and no independent false-green signal. This keeps
    agent prose, process exit, and stale green tests from becoming completion.
    """
    proof_reasons = list(proof.reasons)
    if not loop_converged:
        proof_reasons.append("agent loop did not converge")
    if not changed_files:
        proof_reasons.append("no observed working-tree change")
    if not verifier_signals:
        proof_reasons.append("no verifier was executed")
    failed_verifiers = tuple(signal.name for signal in verifier_signals if not signal.passed)
    for name in failed_verifiers:
        proof_reasons.append(f"verifier failed: {name}")
    if proof.false_green:
        proof_reasons.append("proof graph reported a false green")
    if verifier_false_green:
        proof_reasons.append("independent verifier reported a false green")

    canonical_proof_reasons = tuple(dict.fromkeys(reason for reason in proof_reasons if reason))
    proof_complete = (
        loop_converged
        and bool(changed_files)
        and bool(verifier_signals)
        and not failed_verifiers
        and proof.complete
        and not proof.false_green
        and not verifier_false_green
    )
    effective_assessment = ProofAssessment(
        complete=proof_complete,
        false_green=not proof_complete,
        reasons=canonical_proof_reasons,
    )

    policy_reasons = [violation.message for violation in policy.violations]
    if monitor_blocked:
        policy_reasons.append("reference monitor blocked an observed effect")
    canonical_policy_reasons = tuple(dict.fromkeys(reason for reason in policy_reasons if reason))
    policy_ok = policy.allowed and not policy.approvals_required and not monitor_blocked

    return CompletionGateDecision(
        proof_complete=proof_complete,
        policy_ok=policy_ok,
        assessment=effective_assessment,
        proof_reasons=canonical_proof_reasons,
        policy_reasons=canonical_policy_reasons,
    )


__all__ = ["CompletionGateDecision", "evaluate_completion_gate"]
