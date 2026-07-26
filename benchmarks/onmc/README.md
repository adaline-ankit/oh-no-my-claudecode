# ONMC Harbor Benchmark Adapter

This directory is the home for generated Harbor task bundles derived from ONMC
portfolio manifests.

ONMC remains the source of truth for:

- portfolio task identity,
- pinned repositories,
- verifier commands,
- experiment conditions,
- cost and telemetry labels,
- claim-readiness gates.

Harbor is used as the execution environment for agent-neutral trials. Exported
tasks follow Harbor's task-directory shape: `instruction.md`, `task.toml`,
`environment/Dockerfile`, and `tests/test.sh`. Imported results must include
ATIF trajectory artifacts, verifier artifacts, reward/pass state, and measured
metrics before they enter ONMC reports.

## Publication workflow

All commands below are offline unless the operator explicitly launches Harbor
with a real agent:

```bash
python scripts/validate_benchmark_manifest.py \
  datasets/experiment/portfolio_external_v4.json

python scripts/generate_benchmark_report.py \
  datasets/experiment/reports/external_v3_stage1_2026-07-25.json \
  --manifest datasets/experiment/portfolio_external_v4.json \
  --verifier-calibration docs/evidence/verifier_external_v2_report.json \
  --json-out docs/evidence/sota-report.json \
  --markdown-out docs/evidence/sota-report.md \
  --artifact-index-out docs/evidence/raw-artifacts.json

python scripts/gate_external_claim.py docs/evidence/sota-report.json \
  --claim "ONMC is state-of-the-art, better, and cheaper."
```

The claim gate exits `2` when strong language outruns the evidence. Report
generation still exits successfully for incomplete runs so maintainers can
inspect the missing gates. Add `--require-publication-ready` when CI or a
release candidate must fail closed.

The U14 publication metadata lives in an optional `publication` object on the
portfolio manifest. A publication candidate must pre-register:

- all five arms: bare agent, context only, canonical single-agent ONMC,
  trajectory-routed ONMC, and selective swarm;
- at least three seeds and three agent/model configurations;
- at least 50 discriminative tasks across multiple repositories and languages;
- an independent leakage audit proving hidden material was unavailable to the
  agent.

These fields do not make a claim valid by themselves. The completed report must
also pass calibration, cost coverage, verifier calibration, raw-artifact, and
confidence-interval gates.

See [the reproduction guide](../../docs/evidence/reproduce.md) for the bounded
free smoke and [the current report](../../docs/evidence/sota-report.md) for the
honest blocker list.
