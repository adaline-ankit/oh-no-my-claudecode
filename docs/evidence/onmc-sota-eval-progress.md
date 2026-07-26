# ONMC SOTA Eval Progress

Last updated: 2026-07-26

## Current Claim Status

ONMC now has the first implementation slice of the canonical runtime contract from
`docs/plans/onmc-sota-harness-evals-rag-plan.md`.

This is evidence for a stronger harness foundation:

- Existing `onmc run` plans can compile into a canonical `RunSpec`.
- Every side-effecting runtime node must declare idempotency, timeout, budget, and capabilities.
- Invalid graph edges and cycles fail before execution.
- The native backend replays completed runs from persisted node results without re-running handlers.
- Saved external benchmark reports can now be calibrated for discriminativeness and cost coverage
  before any quality or cost claim is made.
- `scripts/calibrate_external_report.py` can audit saved report JSON without invoking agents or
  spending model tokens.
- The calibration script can optionally compare a report against the frozen portfolio manifest so
  stale reports cannot be cited for newer task sets.
- Saved reports and manifests now include an offline benchmark planning gate: task count, total
  cells, minimum claim-sized task count, estimated spend, and budget-ceiling readiness.
- Manifest-gated reports now include an offline portfolio coverage gate: task-kind spread, repo
  spread, metadata completeness, and dominance checks so a benchmark cannot be inflated by one
  easy task shape.
- Calibration artifacts now include a single top-level `claim_readiness` verdict that combines
  benchmark power, portfolio coverage, calibration quality, and cost telemetry.
- Manifest-gated artifacts now include a `portfolio_gap_plan` that converts failed power/coverage
  gates into exact task-addition requirements.
- The native runtime now recovers a node result that was written immediately before a crash and
  does not re-run the node handler, closing a duplicate-side-effect recovery gap.
- Native runtime runs now persist a `RunSpec` manifest and reject replay/resume when the requested
  spec digest differs from the stored one, preventing stale-result reuse across task changes.
- Side-effecting runtime nodes now require a first-class `completion_condition`, and successful
  side-effecting results require digest-backed completion evidence before the backend accepts them.
- Side-effecting runtime nodes now carry an explicit `retry_policy` in the canonical `RunSpec`,
  preserving the harness DAG retry contract across backend implementations.
- The native runtime now executes bounded retry policy for retryable handler exceptions and failed
  node results, records durable retry metadata, and writes only the terminal node result.
- The native runtime now has dependency-aware execution layers and optional bounded fan-out via
  `max_workers`, with deterministic fan-in order and sibling cleanup on parallel contract errors.
- Runtime nodes can now declare `approval_required`; the native backend persists run/node approval
  interrupts before side effects and resumes after durable approval without duplicate execution.
- The native runtime now treats durable cancellation as terminal, refuses to restart cancelled runs,
  and propagates node-level skips to pending downstream graph nodes.
- Side-effecting native runtime nodes now acquire durable node leases while handlers run, release
  leases after execution, recover persisted results that still have active leases, and reacquire a
  fresh deterministic lease if a process crashes after lease release but before result persistence.
- OTel GenAI span export now preserves measured `input_tokens` and `output_tokens` when trace events
  provide them, and explicitly marks legacy total-token-only fallback splits as estimated instead of
  presenting them as measured usage.
- OTel GenAI span export now preserves measured event duration when trace events provide `end_ts`,
  `duration_seconds`, or `duration_ms`, and explicitly marks the legacy instant-event 1ms span
  fallback as estimated.
- Native runtime execution now emits best-effort `runtime_node` trace events for each executed
  node when an ONMC trace session is active, including measured duration, run/node identity,
  node status, retry attempts, side-effect flags, approval requirement, and declared capabilities.
- OTel GenAI export now flattens `runtime_node` events into stable `onmc.runtime.*` span
  attributes, including run/node identity, node status/error, retry attempts, dependency labels,
  side-effect and approval flags, declared tools/commands, filesystem/network capabilities, and
  secret-count metadata without exporting secret names.
- OTel span export now includes deterministic `traceId` and `spanId` fields so repeated exports
  preserve stable correlation identity and all events from the same ONMC trace session share a
  trace identifier while each event keeps a distinct span identifier.
- OTel export now attaches runtime DAG dependency links between `runtime_node` spans when dependency
  spans are present in the same run, preserving fan-out/fan-in graph structure for trace backends
  that support span links.
- Native runtime approval interrupts now emit `runtime_node` trace events before returning control,
  with `interrupted` status, run/node identity, side-effect and approval flags, and the persisted
  approval reason.
- Native runtime graph cancellation now emits `runtime_node` trace events for downstream pending
  nodes that are cancelled after an upstream skip, preserving the visible DAG stop reason for
  Mission Control and OTLP consumers.

This is not yet evidence that ONMC is better than plain Claude Code or Codex on external coding
tasks. That requires the later Harbor/external benchmark waves in the plan.

## Validation Run

Commands run on 2026-07-26:

```text
python -m pytest -q tests/test_runtime_contracts.py tests/test_harness_run.py tests/test_durable_runtime.py
```

Result:

```text
33 passed
```

```text
ruff check src/oh_no_my_claudecode/runtime src/oh_no_my_claudecode/harness_run/models.py tests/test_runtime_contracts.py
```

Result:

```text
All checks passed
```

```text
python -m mypy src/oh_no_my_claudecode/runtime src/oh_no_my_claudecode/harness_run/models.py
```

Result:

```text
Success: no issues found in 5 source files
```

Mypy also reported pre-existing unused optional-dependency override notes for `ag2`, `autogen`, and
`crewai`; these were not introduced by this runtime slice.

```text
python -m pytest -q tests/test_experiment_contracts.py tests/test_experiment_kernel.py tests/test_experiment_portfolio.py tests/test_runtime_contracts.py
```

Result:

```text
51 passed
```

```text
python -m pytest -q tests/test_experiment_calibration.py tests/test_experiment_contracts.py tests/test_experiment_kernel.py tests/test_experiment_portfolio.py tests/test_external_corpus.py tests/test_runtime_contracts.py
```

Result:

```text
67 passed
```

```text
python -m pytest -q tests/test_experiment_power.py tests/test_experiment_calibration.py
```

Result:

```text
14 passed
```

```text
python -m pytest -q tests/test_experiment_coverage.py tests/test_experiment_power.py tests/test_experiment_calibration.py
```

Result:

```text
18 passed
```

```text
python -m pytest -q tests/test_experiment_coverage.py tests/test_experiment_calibration.py tests/test_experiment_claim.py tests/test_experiment_power.py
```

Result:

```text
22 passed
```

```text
python -m pytest -q tests/test_runtime_contracts.py tests/test_durable_runtime.py tests/test_harness_run.py
```

Result:

```text
35 passed
```

```text
python -m pytest -q tests/test_runtime_contracts.py tests/test_durable_runtime.py tests/test_harness_run.py tests/test_harness_policy_proof.py
```

Result:

```text
63 passed
```

```text
python -m pytest -q tests/test_runtime_contracts.py tests/test_durable_runtime.py tests/test_harness_run.py tests/test_harness_policy_proof.py
```

Result:

```text
65 passed
```

```text
python -m pytest -q tests/test_runtime_fanout.py tests/test_runtime_contracts.py tests/test_durable_runtime.py tests/test_harness_run.py tests/test_harness_policy_proof.py
```

Result:

```text
68 passed
```

```text
python -m pytest -q tests/test_runtime_fanout.py tests/test_runtime_contracts.py tests/test_durable_runtime.py tests/test_harness_run.py tests/test_harness_policy_proof.py
```

Result:

```text
70 passed
```

```text
python -m pytest -q tests/test_runtime_fanout.py tests/test_runtime_contracts.py tests/test_durable_runtime.py tests/test_harness_run.py tests/test_harness_policy_proof.py
```

Result:

```text
72 passed
```

```text
python -m pytest -q tests/test_runtime_contracts.py tests/test_runtime_fanout.py
```

Result:

```text
17 passed
```

```text
python -m pytest -q tests/test_runtime_fanout.py tests/test_runtime_contracts.py tests/test_durable_runtime.py tests/test_harness_run.py tests/test_harness_policy_proof.py
```

Result:

```text
73 collected tests passed
```

```text
python -m pytest -q tests/test_runtime_contracts.py tests/test_trace.py
```

Result:

```text
68 passed
```

```text
ruff check src/oh_no_my_claudecode/runtime tests/test_runtime_contracts.py
```

Result:

```text
All checks passed
```

```text
python -m mypy src/oh_no_my_claudecode/runtime
```

Result:

```text
Success: no issues found in 5 source files
```

Mypy again reported pre-existing unused optional-dependency override notes for `ag2`, `autogen`,
and `crewai`; these were not introduced by this runtime slice.

```text
python -m pytest -q tests/test_runtime_fanout.py tests/test_runtime_contracts.py tests/test_durable_runtime.py tests/test_harness_run.py tests/test_harness_policy_proof.py tests/test_trace.py
```

Result:

```text
127 collected tests passed
```

```text
git diff --check
```

Result:

```text
No whitespace errors
```

For the downstream cancellation trace slice:

```text
python -m pytest -q tests/test_runtime_contracts.py tests/test_trace.py
```

Result:

```text
68 passed
```

```text
ruff check src/oh_no_my_claudecode/runtime tests/test_runtime_contracts.py
```

Result:

```text
All checks passed
```

```text
python -m mypy src/oh_no_my_claudecode/runtime
```

Result:

```text
Success: no issues found in 5 source files
```

Mypy again reported pre-existing unused optional-dependency override notes for `ag2`, `autogen`,
and `crewai`; these were not introduced by this runtime slice.

```text
python -m pytest -q tests/test_runtime_fanout.py tests/test_runtime_contracts.py tests/test_durable_runtime.py tests/test_harness_run.py tests/test_harness_policy_proof.py tests/test_trace.py
```

Result:

```text
127 collected tests passed
```

```text
git diff --check
```

Result:

```text
No whitespace errors
```

```text
ruff check src/oh_no_my_claudecode/runtime tests/test_runtime_contracts.py tests/test_runtime_fanout.py
```

Result:

```text
All checks passed
```

```text
python -m mypy src/oh_no_my_claudecode/runtime src/oh_no_my_claudecode/harness_run/models.py
```

Result:

```text
Success: no issues found in 6 source files
```

Mypy again reported pre-existing unused optional-dependency override notes for `ag2`, `autogen`,
and `crewai`; these were not introduced by the lease slice.

```text
git diff --check
```

Result:

```text
No whitespace errors
```

```text
python -m pytest -q tests/test_trace.py
```

Result:

```text
46 passed
```

```text
ruff check src/oh_no_my_claudecode/trace tests/test_trace.py
```

Result:

```text
All checks passed
```

```text
python -m mypy src/oh_no_my_claudecode/trace
```

Result:

```text
Success: no issues found in 6 source files
```

Mypy again reported pre-existing unused optional-dependency override notes for `ag2`, `autogen`,
and `crewai`; these were not introduced by the OTel slice.

```text
python -m pytest -q tests/test_trace.py tests/test_runtime_contracts.py
```

Result:

```text
60 passed
```

```text
git diff --check
```

Result:

```text
No whitespace errors
```

```text
python -m pytest -q tests/test_trace.py
```

Result:

```text
49 passed
```

```text
ruff check src/oh_no_my_claudecode/trace tests/test_trace.py
```

Result:

```text
All checks passed
```

```text
python -m mypy src/oh_no_my_claudecode/trace
```

Result:

```text
Success: no issues found in 6 source files
```

Mypy again reported pre-existing unused optional-dependency override notes for `ag2`, `autogen`,
and `crewai`; these were not introduced by the OTel duration slice.

```text
python -m pytest -q tests/test_trace.py tests/test_runtime_contracts.py
```

Result:

```text
63 passed
```

```text
git diff --check
```

Result:

```text
No whitespace errors
```

```text
python -m pytest -q tests/test_runtime_contracts.py tests/test_trace.py
```

Result:

```text
65 passed
```

```text
ruff check src/oh_no_my_claudecode/runtime src/oh_no_my_claudecode/trace tests/test_runtime_contracts.py tests/test_trace.py
```

Result:

```text
All checks passed
```

```text
python -m mypy src/oh_no_my_claudecode/runtime src/oh_no_my_claudecode/trace
```

Result:

```text
Success: no issues found in 11 source files
```

Mypy again reported pre-existing unused optional-dependency override notes for `ag2`, `autogen`,
and `crewai`; these were not introduced by the runtime trace slice.

```text
python -m pytest -q tests/test_runtime_fanout.py tests/test_runtime_contracts.py tests/test_durable_runtime.py tests/test_harness_run.py tests/test_harness_policy_proof.py tests/test_trace.py
```

Result:

```text
124 collected tests passed
```

```text
git diff --check
```

Result:

```text
No whitespace errors
```

```text
python -m pytest -q tests/test_trace.py
```

Result:

```text
51 passed
```

```text
ruff check src/oh_no_my_claudecode/trace tests/test_trace.py
```

Result:

```text
All checks passed
```

```text
python -m mypy src/oh_no_my_claudecode/trace
```

Result:

```text
Success: no issues found in 6 source files
```

Mypy again reported pre-existing unused optional-dependency override notes for `ag2`, `autogen`,
and `crewai`; these were not introduced by the runtime-node OTel attribute slice.

```text
python -m pytest -q tests/test_runtime_contracts.py tests/test_trace.py
```

Result:

```text
66 passed
```

```text
python -m pytest -q tests/test_runtime_fanout.py tests/test_runtime_contracts.py tests/test_durable_runtime.py tests/test_harness_run.py tests/test_harness_policy_proof.py tests/test_trace.py
```

Result:

```text
125 collected tests passed
```

```text
git diff --check
```

Result:

```text
No whitespace errors
```

```text
python -m pytest -q tests/test_trace.py
```

Result:

```text
52 passed
```

```text
ruff check src/oh_no_my_claudecode/trace tests/test_trace.py
```

Result:

```text
All checks passed
```

```text
python -m mypy src/oh_no_my_claudecode/trace
```

Result:

```text
Success: no issues found in 6 source files
```

Mypy again reported pre-existing unused optional-dependency override notes for `ag2`, `autogen`,
and `crewai`; these were not introduced by the OTel span identity slice.

```text
python -m pytest -q tests/test_runtime_contracts.py tests/test_trace.py
```

Result:

```text
67 passed
```

```text
python -m pytest -q tests/test_runtime_fanout.py tests/test_runtime_contracts.py tests/test_durable_runtime.py tests/test_harness_run.py tests/test_harness_policy_proof.py tests/test_trace.py
```

Result:

```text
126 collected tests passed
```

```text
git diff --check
```

Result:

```text
No whitespace errors
```

```text
python -m pytest -q tests/test_trace.py
```

Result:

```text
53 passed
```

```text
ruff check src/oh_no_my_claudecode/trace tests/test_trace.py
```

Result:

```text
All checks passed
```

```text
python -m mypy src/oh_no_my_claudecode/trace
```

Result:

```text
Success: no issues found in 6 source files
```

Mypy again reported pre-existing unused optional-dependency override notes for `ag2`, `autogen`,
and `crewai`; these were not introduced by the OTel dependency-link slice.

```text
python -m pytest -q tests/test_runtime_contracts.py tests/test_trace.py
```

Result:

```text
68 passed
```

```text
python -m pytest -q tests/test_runtime_fanout.py tests/test_runtime_contracts.py tests/test_durable_runtime.py tests/test_harness_run.py tests/test_harness_policy_proof.py tests/test_trace.py
```

Result:

```text
127 collected tests passed
```

```text
git diff --check
```

Result:

```text
No whitespace errors
```

```text
python -m pytest -q tests/test_runtime_fanout.py tests/test_swarm.py tests/test_mission.py
```

Result:

```text
60 passed
```

```text
ruff check src/oh_no_my_claudecode/experiment src/oh_no_my_claudecode/runtime src/oh_no_my_claudecode/harness_run/models.py scripts/run_external_eval.py scripts/calibrate_external_report.py tests/test_experiment_calibration.py tests/test_experiment_power.py tests/test_runtime_contracts.py
```

Result:

```text
All checks passed
```

```text
python -m mypy src/oh_no_my_claudecode/experiment src/oh_no_my_claudecode/runtime src/oh_no_my_claudecode/harness_run/models.py
```

Result:

```text
Success: no issues found in 11 source files
```

```text
git diff --check
```

Result:

```text
No whitespace errors
```

## Benchmark Meaning

This is a harness-correctness benchmark, not a model-quality benchmark.

| Gate | Result | Meaning |
|---|---:|---|
| Runtime contract validation | Pass | Unsafe graph specs are rejected before execution. |
| Durable replay | Pass | Re-running a completed graph returns persisted results without new node execution. |
| Crash-window recovery | Pass | A persisted node result is reconciled without re-running the handler after a crash. |
| RunSpec digest lock | Pass | Resuming with a changed task/graph contract is rejected before handlers run. |
| Completion evidence lock | Pass | Successful side-effecting nodes cannot complete without digest-backed completion evidence. |
| Retry policy contract | Pass | Harness DAG retry policy is serialized into side-effecting runtime nodes. |
| Native retry execution | Pass | Retryable exceptions and failed results are retried within policy and recorded in durable history. |
| Dependency-aware fan-out | Pass | Ready nodes can run in bounded parallel layers and fan in deterministically before dependents. |
| Approval interrupt | Pass | Approval-required nodes persist run/node interrupts before side effects and resume after approval. |
| Cancellation semantics | Pass | Cancelled runs do not restart and skipped nodes cancel pending downstream work. |
| Existing harness compatibility | Pass | Current `HarnessController` tests still pass. |
| Durable store invariants | Pass | Existing event-sourced runtime behavior still passes. |
| Eval infrastructure smoke | Pass | Experiment contract/kernel/portfolio tests still pass. |
| Calibration gate | Pass | Saturated tasks and incomplete cost telemetry are explicitly rejected for claims. |
| Benchmark planning gate | Pass | Underpowered or unbudgeted paid eval plans are flagged before launch. |
| Portfolio coverage gate | Pass | Skewed task-kind/repo portfolios are flagged before they can support a claim. |
| Unified claim readiness | Pass | One machine-readable verdict names every blocked external-claim gate. |
| Portfolio gap plan | Pass | Failed gates produce exact corpus expansion requirements. |
| External agent quality | Not run | No claim yet against Claude Code/Codex alone. |

## Saved External Report Calibration

The saved report `datasets/experiment/reports/external_v3_stage1_2026-07-25.json` was calibrated
offline on 2026-07-26.

Generated artifact:

```text
docs/evidence/external_v3_stage1_2026-07-25.calibration.json
```

Manifest-gated artifact:

```text
docs/evidence/external_v3_against_v4_manifest.calibration.json
```

Result:

```text
external_claim_decision: not-ready
blocked_gates: benchmark_plan, portfolio_coverage, calibration
decision: needs-discrimination
quality_claim_ready: false
cost_claim_ready: false
discriminative_tasks: 0
saturated_tasks: 24
incomplete_cell_count: 0
incomplete_cost_conditions: bare-agent
```

Benchmark planning envelope for the current v4 manifest, using an explicit planning estimate of
`$0.75` per cell and a `$300` ceiling:

```text
claim_ready: false
sample_size_ready: false
budget_ready: true
task_count: 28
conditions: 2
trials_per_cell: 3
total_cells: 168
min_tasks_required: 50
min_total_cells_required: 300
estimated_cost_usd: 126.0
estimated_required_cost_usd: 225.0
```

Portfolio coverage for the current v4 manifest:

```text
claim_ready: false
task_kind_coverage_ready: false
repo_coverage_ready: true
balance_ready: false
metadata_ready: true
task_kind_counts: bugfix=7, feature=19, refactor=1, long-running=1
repo_counts: attrs=7, itsdangerous=6, jmespath.py=6, tenacity=4, six=3, python-slugify=2
```

Portfolio gap plan for the current v4 manifest:

```text
current_tasks: 28
target_tasks: 50
minimum_total_additions: 22
suggested_minimum_additions_by_kind: refactor=2, long-running=2
unallocated_non_dominant_additions: 18
dominant_kind: feature
max_additional_dominant_kind_at_target: 11
```

Interpretation:

- The old public-repo benchmark cannot support an "ONMC improves Claude Code" claim.
- All 24 measured tasks saturated: both bare agent and ONMC passed them.
- Bare-agent cost telemetry was incomplete, so cost claims are also blocked.
- The v3 report is stale for the current v4 manifest: task-set revision mismatch, one trial instead
  of the manifest's three, and four v4 tasks missing.
- The current v4 manifest is still underpowered for the configured planning target: 28 tasks
  instead of the 50-task floor. It is budget-feasible under the explicit `$300` planning ceiling,
  but not claim-ready.
- The current v4 manifest is also not portfolio-balanced enough for a strong external claim:
  refactor and long-running each have only one task, and feature tasks are 67.9% of the portfolio
  against a 60% dominance ceiling.
- The unified claim gate blocks an external ONMC quality/cost claim on three gates:
  `benchmark_plan`, `portfolio_coverage`, and `calibration`.
- This is useful progress because the repo now has a programmatic gate that catches this failure
  mode instead of relying on manual judgment.

## Next Evidence Target

Next useful benchmark is U1 plus U7 from the SOTA plan:

1. Freeze a discriminative external task portfolio with at least 50 tasks, at least three refactor
   tasks, at least three long-running tasks, and no single task kind above the dominance ceiling.
2. Run bare agent vs ONMC-controlled agent on the same tasks.
3. Report pass rate, cost, latency, variance, confidence intervals, and incomplete cost coverage.
4. Publish raw manifests and trajectories before making product claims.

The current machine-generated next actions are:

```text
- Add at least 22 benchmark task(s) to reach the 50-task planning target.
- Rebalance the portfolio so required task kinds, repo spread, metadata, and dominance thresholds pass.
- Run a fresh, complete, discriminative benchmark report against the current manifest.
```

Concrete corpus expansion target:

```text
- Add 22 tasks total.
- Include at least 2 more refactor tasks.
- Include at least 2 more long-running tasks.
- Draft slot mix: 4 bugfix, 9 refactor, and 9 long-running tasks.
- At the 50-task target, add no more than 11 additional feature tasks.
```
