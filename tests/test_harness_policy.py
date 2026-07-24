"""Unit tests for the file-backed harness policy engine and run receipt."""

from __future__ import annotations

from pathlib import Path

import pytest

from oh_no_my_claudecode.harness_policy import (
    ChangeSet,
    HarnessPolicy,
    PolicyOutcome,
    evaluate_policy,
    load_policy,
    save_policy,
    scan_secrets,
)
from oh_no_my_claudecode.harness_run.receipt import (
    RunReceipt,
    compute_verified,
    verify_receipt,
)


def _clean_change(**overrides: object) -> ChangeSet:
    base: dict[str, object] = {
        "changed_files": ("src/app.py",),
        "added_lines": 3,
        "removed_lines": 1,
        "diff_text": "+def add(a, b):\n+    return a + b\n",
        "commands": (("pytest",),),
        "verifiers_run": ("pytest",),
    }
    base.update(overrides)
    return ChangeSet(**base)  # type: ignore[arg-type]


def test_clean_change_is_allowed() -> None:
    evaluation = evaluate_policy(HarnessPolicy.permissive(), _clean_change())
    assert evaluation.outcome is PolicyOutcome.ALLOW
    assert evaluation.allowed
    assert evaluation.violations == ()


def test_denied_path_is_rejected() -> None:
    policy = HarnessPolicy(denied_paths=("infra/**",))
    evaluation = evaluate_policy(policy, _clean_change(changed_files=("infra/prod.tf",)))
    assert evaluation.outcome is PolicyOutcome.DENY
    assert any(v.code == "denied-path" for v in evaluation.violations)


def test_allow_list_rejects_paths_outside_it() -> None:
    policy = HarnessPolicy(allowed_paths=("src/**",))
    inside = evaluate_policy(policy, _clean_change(changed_files=("src/app.py",)))
    outside = evaluate_policy(policy, _clean_change(changed_files=("scripts/x.sh",)))
    assert inside.allowed
    assert outside.outcome is PolicyOutcome.DENY
    assert any(v.code == "path-not-allowed" for v in outside.violations)


def test_max_files_and_max_diff_lines() -> None:
    files_policy = HarnessPolicy(max_files_touched=1)
    lines_policy = HarnessPolicy(max_diff_lines=2)
    too_many = evaluate_policy(files_policy, _clean_change(changed_files=("a.py", "b.py")))
    too_big = evaluate_policy(lines_policy, _clean_change(added_lines=5, removed_lines=5))
    assert any(v.code == "too-many-files" for v in too_many.violations)
    assert any(v.code == "diff-too-large" for v in too_big.violations)


def test_required_verifier_must_run() -> None:
    policy = HarnessPolicy(required_verifiers=("pytest", "mypy"))
    evaluation = evaluate_policy(policy, _clean_change(verifiers_run=("pytest",)))
    assert evaluation.outcome is PolicyOutcome.DENY
    reasons = [v.detail for v in evaluation.violations if v.code == "missing-verifier"]
    assert any("mypy" in reason for reason in reasons)


def test_human_approval_gate_when_no_hard_violation() -> None:
    policy = HarnessPolicy(human_approval_required=True)
    evaluation = evaluate_policy(policy, _clean_change())
    assert evaluation.outcome is PolicyOutcome.REQUIRES_APPROVAL
    assert not evaluation.allowed


def test_hard_denial_beats_approval_gate() -> None:
    policy = HarnessPolicy(human_approval_required=True, denied_paths=("src/**",))
    evaluation = evaluate_policy(policy, _clean_change(changed_files=("src/app.py",)))
    assert evaluation.outcome is PolicyOutcome.DENY


@pytest.mark.parametrize(
    "leak",
    [
        "+AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'",
        "+-----BEGIN RSA PRIVATE KEY-----",
        "+token = ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "+password = 'hunter2hunter2'",
    ],
)
def test_secret_scan_flags_credentials(leak: str) -> None:
    findings = scan_secrets(leak)
    assert findings, f"expected a finding for {leak!r}"
    # The excerpt is redacted — it never echoes the full credential back.
    assert "*" in findings[0].excerpt


def test_secret_scan_ignores_removed_lines() -> None:
    # A credential being *deleted* (leading '-') is not a leak.
    assert scan_secrets("-token = ghp_abcdefghijklmnopqrstuvwxyz0123456789") == ()


def test_policy_file_round_trip(tmp_path: Path) -> None:
    policy = HarnessPolicy(
        allowed_paths=("src/**",),
        protected_files=("pyproject.toml",),
        max_files_touched=10,
        required_verifiers=("pytest",),
        human_approval_required=True,
    )
    save_policy(policy, policy_dir=tmp_path)
    assert load_policy(policy_dir=tmp_path) == policy


def test_missing_policy_file_falls_back_to_permissive(tmp_path: Path) -> None:
    assert load_policy(policy_dir=tmp_path) == HarnessPolicy.permissive()


def test_malformed_policy_is_a_hard_error(tmp_path: Path) -> None:
    (tmp_path / "policy.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match="unreadable"):
        load_policy(policy_dir=tmp_path)


def test_receipt_verified_requires_all_three_conditions() -> None:
    assert compute_verified(status="completed", proof_complete=True, policy_outcome="allow")
    assert not compute_verified(status="failed", proof_complete=True, policy_outcome="allow")
    assert not compute_verified(status="completed", proof_complete=False, policy_outcome="allow")
    assert not compute_verified(status="completed", proof_complete=True, policy_outcome="deny")


def test_tampered_receipt_that_flips_verified_fails_verification() -> None:
    receipt = RunReceipt.build(
        run_id="run-1",
        status="failed",
        proof_complete=False,
        policy_outcome="deny",
        stages=(),
        policy={"outcome": "deny"},
        capability_decisions=(),
        proof={"complete": False},
    )
    assert receipt.verified is False
    assert verify_receipt(receipt.to_json())
    forged = receipt.to_json().replace('"verified":false', '"verified":true')
    assert forged != receipt.to_json()
    assert verify_receipt(forged) is False
