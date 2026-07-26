# U1/U2 Baseline and Runtime Contract Audit

Date: 2026-07-26  
Base: `origin/main` at `7f30934197ece425a26bccaf57c1218c01e19b9c`

## Verdict

| Unit | Status | Evidence |
|---|---|---|
| U1: discriminative baseline | Partial | The offline claim gates are fail-closed for saturation, cost coverage, frozen task content, stale revisions, and incomplete task/condition/trial cells. The saved v3 report still cannot support a quality or cost claim, and no complete v4 benchmark result exists. |
| U2: canonical graph contracts | Partial | The typed graph, native backend, durable replay, idempotency, completion evidence, approvals, cancellation, leases, corrupt-event detection, and harness compatibility contracts pass the focused suite. Dependency success is enforced, but required dependency-output schemas are not yet declared or validated before downstream execution. |

## U1 Acceptance Matrix

| Plan scenario | Result | Exact evidence |
|---|---|---|
| Seeded regression must fail its verifier before an agent call | Partial | `scripts/run_external_eval.py::guard_regression_active` is called before agent execution, and `tests/test_external_corpus.py` proves every v4 task has a mutation and an allowed verifier. There is no direct ordering test that asserts the agent runner was not called after a vacuity failure. |
| Missing reproducibility or verifier metadata invalidates a report | Pass | `test_manifest_gate_blocks_missing_report_metadata`, `test_manifest_gate_blocks_environment_manifest_mismatch`, and `test_manifest_gate_blocks_incomplete_verifier_artifacts`. |
| Incomplete cost coverage cannot support a cost claim | Pass | `test_incomplete_cost_blocks_cost_claim_but_not_quality_claim`; the saved v3 artifact reports `bare-agent` cost telemetry incomplete. |
| Randomized order is reproducible from the seed | Pass | `test_randomized_order_is_seed_stable_and_a_permutation`, `test_different_seeds_change_execution_order`, and `test_report_is_deterministic_for_same_seed`. |
| Saturated tasks are disclosed and do not create a false quality claim | Pass | `test_saturated_report_is_not_claim_ready`; the saved v3 report records 24 saturated tasks and zero discriminative tasks. |
| Frozen revision is bound to exact task definitions | Pass | v4 carries `task_set_sha256=b48c2b7cb444dc01dbc36e2306dcf9d37d18ef309d054d42d949de9c0233d82d`; `test_portfolio_rejects_task_set_hash_that_does_not_bind_tasks`, `test_valid_portfolio_without_task_set_hash_stays_internal`, and `test_manifest_gate_rejects_task_set_hash_mismatch`. |
| Claimed trial count matches actual cells | Pass | `test_manifest_gate_rejects_missing_trial_cell_despite_claimed_trial_count` and `test_manifest_gate_rejects_duplicate_trial_cell`. The v3-vs-v4 artifact now reports 168 expected cells, 48 reported cells, and 120 missing cells. |

## U2 Acceptance Matrix

| Plan scenario | Result | Exact evidence |
|---|---|---|
| Side effects require idempotency, timeout, budget, retry, capabilities, and completion condition | Pass | `test_side_effecting_nodes_require_idempotency_timeout_budget_and_capabilities`. |
| Invalid graph edges fail before execution | Pass | `test_run_spec_rejects_invalid_edges_and_serializes_stably`. |
| Missing dependency outputs fail before agent execution | Partial | The native backend rejects unsatisfied dependency state, but `NodeSpec` does not declare required dependency output keys or schemas, so an empty successful dependency output is currently accepted. |
| Completed idempotency keys replay without another side effect | Pass | `test_native_backend_replays_completed_idempotency_without_side_effect`, `test_native_backend_recovers_result_written_before_crash_without_side_effect`, and `test_native_backend_resumes_approval_interrupt_without_duplicate_side_effect`. |
| Native output remains compatible with harness results and receipts | Pass | `test_harness_plan_compiles_to_canonical_run_spec`, `test_clean_run_is_verified_and_receipt_is_tamper_evident`, and `test_receipt_build_is_deterministic`. |
| Resume, approval, cancellation, lease expiry, and corrupt-event invariants hold | Pass | Focused tests in `tests/test_runtime_contracts.py` and `tests/test_durable_runtime.py`, including spec-digest mismatch, approval interrupt, cancellation, deterministic lease expiry, event tampering, and truncated-event detection. |

## Current Claim Boundary

The generated artifact
`docs/evidence/external_v3_against_v4_manifest.calibration.json` remains
`not-ready`. It now additionally blocks on a missing report task-set hash and
120 missing v4 trial cells. It also preserves the prior blockers: 28 tasks
instead of 50, portfolio imbalance, zero discriminative tasks in the saved v3
run, 24 saturated tasks, incomplete cost telemetry, stale revision, one trial
instead of three, and incomplete report artifacts.

No agent benchmark, paid model, networked evaluator, or live provider call was
run for this audit.
