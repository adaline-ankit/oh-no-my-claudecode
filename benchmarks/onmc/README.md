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
