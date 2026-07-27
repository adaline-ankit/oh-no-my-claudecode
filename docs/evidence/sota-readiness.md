# ONMC SOTA Readiness Audit

- commit: `08a3969f292e3626bcf5e01c008f8096d8c5820f`
- publication ready: `false`
- claim decision: `not-ready`
- proven requirements: `2/19`
- partial: `15`
- blocked: `2`
- missing: `0`

## Requirements

| Req | Status | Evidence | Next gate |
|---|---|---|---|
| R1 | `partial` | `docs/evidence/runtime-delegation.json`, `src/oh_no_my_claudecode/runtime/contracts.py` | fault-injection crash/resume audit across every RunSpec node |
| R2 | `proven` | `docs/evidence/runtime-delegation.json` | keep audit green after each workflow PR |
| R3 | `partial` | `docs/evidence/runtime-delegation.json`, `src/oh_no_my_claudecode/runtime/contracts.py` | add typed input/output schema audit for every side-effecting node |
| R4 | `partial` | `src/oh_no_my_claudecode/runtime/fanout.py`, `src/oh_no_my_claudecode/durable_runtime/store.py` | run 24h soak plus fault injection for cancellation and resume |
| R5 | `partial` | `src/oh_no_my_claudecode/verifier`, `docs/evidence/verifier_external_v2_report.json` | pass external false-green sensitivity/specificity gate |
| R6 | `partial` | `docs/evidence/verifier_external_v2_report.json` | make verifier calibration ready in publication bundle |
| R7 | `partial` | `src/oh_no_my_claudecode/sandbox`, `src/oh_no_my_claudecode/harness_run/sandboxing.py` | add isolation audit artifact proving autonomous runs declare and enforce sandbox mode |
| R8 | `partial` | `src/oh_no_my_claudecode/loop/receipt.py` | add receipt replay/export audit with hash-chain verification |
| R9 | `partial` | `src/oh_no_my_claudecode/retrieval_eval`, `src/oh_no_my_claudecode/retrieval` | run held-out retrieval eval with recall/nDCG/context-efficiency thresholds |
| R10 | `partial` | `src/oh_no_my_claudecode/retrieval/core.py` | add context-selection audit artifact and downstream smoke |
| R11 | `partial` | `src/oh_no_my_claudecode/learning` | run promote/reject audit on held-out protected suite |
| R12 | `blocked` | `datasets/experiment/portfolio_external_v4.json`, `src/oh_no_my_claudecode/experiment/harbor_adapter.py` | freeze 50-task, 5-arm, 3-seed, 3-config Harbor manifest |
| R13 | `blocked` | `docs/evidence/sota-report.json`, `docs/evidence/publication-work-plan.json` | fill all R13 report coverage fields and raw artifact index |
| R14 | `partial` | `src/oh_no_my_claudecode/autoroute/trajectory.py`, `src/oh_no_my_claudecode/experiment/routing.py` | run router regret benchmark against static baselines |
| R15 | `partial` | `src/oh_no_my_claudecode/learning/prediction.py`, `src/oh_no_my_claudecode/experiment/kernel.py` | require prediction-backed experiment manifest before promotion |
| R16 | `proven` | `docs/evidence/product-smoke.json`, `docs/evidence/sota-report.json` | keep root help collapsed and validate external activation task |
| R17 | `partial` | `src/oh_no_my_claudecode/loop/adapters.py`, `src/oh_no_my_claudecode/runtime/adapter_capabilities.py` | run adapter conformance suite with honest capability labels |
| R18 | `partial` | `src/oh_no_my_claudecode/missioncontrol/runtime.py` | add Mission Control artifact proving no synthetic progress |
| R19 | `partial` | `pyproject.toml` | add dependency-audit artifact for default and recommended extras |

## Blocked Publication Gates

- `benchmark_plan`
- `portfolio_coverage`
- `calibration`
- `report_coverage`
- `verifier_calibration`
