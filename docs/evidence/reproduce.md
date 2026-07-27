# Reproducing ONMC benchmark evidence

This guide regenerates the committed U14 evidence without model calls. It does
not run the paid publication matrix and does not turn fixture output into an
external claim.

## Prerequisites

- Python 3.11 or newer.
- The repository checked out at the commit named by the evidence bundle.
- Development dependencies installed from the lock file.
- Optional for the Harbor non-vacuity smoke: Docker and Harbor already
  installed locally.

Create the local environment once:

```bash
uv sync --extra dev --frozen
```

## 1. Validate the frozen portfolio

```bash
.venv/bin/python scripts/validate_benchmark_manifest.py \
  datasets/experiment/portfolio_external_v4.json \
  --out /tmp/onmc-manifest-validation.json
```

Expected result today: `structurally_valid` is `true` and
`publication_ready` is `false`. To make a release gate fail on that honest
verdict, add `--require-publication-ready`; exit status `2` means the manifest
is valid but the U14 publication requirements are not met.

## 2. Regenerate zero-cost product/runtime gates

```bash
.venv/bin/python scripts/run_product_smoke.py \
  --json-out /tmp/onmc-product-smoke.json

.venv/bin/python scripts/run_runtime_delegation_audit.py \
  --json-out /tmp/onmc-runtime-delegation.json
```

Expected result today: both artifacts report `ready: true`, `model_calls: 0`,
and `agent_execution_attempted: false`.

## 3. Regenerate the report and raw-artifact index

```bash
.venv/bin/python scripts/generate_benchmark_report.py \
  datasets/experiment/reports/external_v3_stage1_2026-07-25.json \
  --manifest datasets/experiment/portfolio_external_v4.json \
  --product-smoke /tmp/onmc-product-smoke.json \
  --runtime-delegation /tmp/onmc-runtime-delegation.json \
  --json-out /tmp/onmc-sota-report.json \
  --markdown-out /tmp/onmc-sota-report.md \
  --artifact-index-out /tmp/onmc-raw-artifacts.json
```

The JSON and Markdown are deterministic for fixed inputs. Compare them with the
committed artifacts:

```bash
diff -u docs/evidence/sota-report.json /tmp/onmc-sota-report.json
diff -u docs/evidence/sota-report.md /tmp/onmc-sota-report.md
diff -u docs/evidence/raw-artifacts.json /tmp/onmc-raw-artifacts.json
```

The raw-artifact index is intentionally incomplete until every usable cell
provides both `trajectory_path` and `verifier_path` under the declared artifact
root. Paths that escape that root are rejected.

## 4. Regenerate the R1-R19 readiness audit

```bash
.venv/bin/python scripts/run_sota_readiness_audit.py \
  --json-out /tmp/onmc-sota-readiness.json \
  --markdown-out /tmp/onmc-sota-readiness.md
```

Expected result today: the audit names every R1-R19 requirement, its evidence,
and the next gate. It is intentionally not a SOTA claim.

## 5. Exercise the external claim gate

```bash
.venv/bin/python scripts/gate_external_claim.py \
  /tmp/onmc-sota-report.json \
  --claim "ONMC is state-of-the-art, better, and cheaper."
```

Expected exit status: `2` (`refuse`). The response lists the failed quality,
cost, SOTA, and report-coverage gates and provides a safe evidence statement.

## 6. Run the free Harbor export smoke

This creates a two-task Harbor dataset and a bounded `nop` plan. It makes no
agent or model call:

```bash
rm -rf /tmp/onmc-harbor-u14-smoke
.venv/bin/python scripts/export_harbor_tasks.py \
  datasets/experiment/portfolio_external_v4.json \
  --out /tmp/onmc-harbor-u14-smoke \
  --limit-tasks 2 \
  --seed-regressions \
  --smoke-plan \
  --smoke-trials 1 \
  --max-cells 4 \
  --agent nop \
  --model local
```

If Harbor and Docker are already available, run one seeded task with the `nop`
agent. A failing verifier is the expected non-vacuity signal because no agent
repairs the planted regression:

```bash
harbor run \
  -p /tmp/onmc-harbor-u14-smoke/onmc/tenacity-bugfix-find-ordinal \
  -a nop \
  -m local \
  --env docker \
  -n 1 \
  -y \
  --jobs-dir /tmp/onmc-harbor-u14-jobs
```

Do not substitute a paid agent or cloud sandbox without an approved manifest
budget and explicit authorization.

## 7. Install the built artifact and run the release smoke

```bash
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
.venv/bin/python scripts/release_artifact_smoke.py --dist-dir dist --offline
```

The smoke creates a disposable environment, installs the wheel, checks the
console entrypoint, and runs one explicitly labelled fixture comparison. It
makes zero model calls and proves packaging plus the fixture path only.

## What remains before publication

A publishable run still needs a frozen current-revision report with at least 50
discriminative tasks, three seeds, all five benchmark arms, three agent/model
configurations, multiple languages, complete cost telemetry, raw ATIF and
verifier artifacts, an independent leakage audit, powered paired uncertainty,
and signed release artifacts. Estimate the final matrix cost and obtain explicit
approval before launching any paid cell.
