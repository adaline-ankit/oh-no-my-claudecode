# ONMC External Benchmark Evidence Report

> **NOT PUBLICATION-READY**

This report is generated from committed evidence. A successful generation does not imply that an external performance claim passed.

## Verdict

- experiment: `external-v3`
- task set: `external-v3-2026-07-25`
- publication ready: `false`
- claim decision: `refuse`
- safe statement: ONMC records harness evidence, but external improvement claims are blocked until these gates pass: benchmark_plan, portfolio_coverage, calibration, report_coverage.

## Condition Results

| Condition | Pass@1 | 95% CI | Mean latency (ms) | Mean cost (USD) | Cost cells |
|---|---:|---:|---:|---:|---:|
| bare-agent | 1.0000 | [1.0000, 1.0000] | 106258.6000 | 0.6352 | 13/24 |
| onmc-current | 1.0000 | [1.0000, 1.0000] | 102712.9000 | 0.8796 | 24/24 |

## Paired Delta

- baseline: `bare-agent`
- treatment: `onmc-current`
- paired tasks: `24`
- mean delta: `0.0000`
- 95% CI: `[0.0000, 0.0000]`
- significant: `false`

## Cost Coverage

- status: `INCOMPLETE`
- reported usable cells: `37/48`
- mean measured cell cost: `0.7938`

Cost claims remain blocked whenever either arm has missing telemetry.

## Leakage Audit

- status: `INCOMPLETE`
- manifest notes present: `true`
- report notes present: `false`
- notes match: `false`
- independent audit recorded: `false`

## Raw Artifact Index

- complete: `false`
- indexed cells: `0/48`
- missing entries: `96`

## Publication Blockers

- at least 50 discriminative tasks are required; found 28
- five benchmark arms are required; missing context-only, onmc-single-agent, selective-swarm, trajectory-routed
- three seeds must be pre-registered in publication.seeds
- three agent/model configurations must be pre-registered in publication.agent_model_configurations
- multiple languages must be declared in publication.languages
- publication.leakage_audit must record a passed independent audit with hidden material unavailable to the agent
- only 28 task(s); requires 50 for a 0.150 paired pass-rate delta planning target
- per-cell cost estimate missing; budget risk is unknown
- task kind 'refactor' has 1 task(s); requires 3
- task kind 'long-running' has 1 task(s); requires 3
- task kind 'feature' is 67.9% of portfolio; maximum is 60.0%
- only 0 discriminative task(s); requires 10
- 24 task(s) saturated across conditions
- cost telemetry incomplete for: bare-agent
- task_set_revision mismatch: manifest=external-v4-2026-07-25, report=external-v3-2026-07-25
- trial count mismatch: manifest=3, report=1
- report missing leakage/reproducibility fields: report.leakage_notes, report.environment, report.failure_taxonomy, report.token_telemetry, report.trajectory_artifacts, report.verifier_artifacts
- report metadata mismatch: report.code_sha
- 4 manifest task(s) missing from report
- report coverage missing raw_trajectories: raw trajectory artifacts are missing or incomplete
- report coverage missing verifier_artifacts: verifier output artifacts are missing or incomplete
- report coverage missing token_use: token telemetry is missing or incomplete
- report coverage missing cost_coverage: one or more usable cells lack measured cost
- report coverage missing failure_taxonomy: failure taxonomy is missing or incomplete
- report coverage missing leakage_audit: leakage notes are missing
- report coverage missing environment_manifest: environment manifest is missing
