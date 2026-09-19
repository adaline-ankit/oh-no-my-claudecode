# Roadmap

This roadmap separates implemented code on `main` from the work still needed to
establish reliable long-session behavior. It is not a release schedule.

## Implemented on main

- Adaptive working context: session goals, constraints, decisions, hypotheses,
  and next steps; source-content freshness checks; bounded packets; repeat
  suppression; Claude hooks and explicit-session CLI/MCP access.
- Authored-instruction protection for automatic `CLAUDE.md` refresh.
- Local repository memory: deterministic ingest, optional LLM extraction,
  provenance, ranking, briefs, guardrails from failed attempts, and Git sync.
- Canonical execution entry point: `onmc run`, typed task plans, explicit
  execution, durable state, configured verifier evidence, and proof receipts.
- Optional advanced verification, receipt attestation, provider integrations,
  multi-agent/runtime adapters, and observability. These are separate capabilities,
  not promises about the default run.
- Reproducible component, retrieval, and live-agent benchmark harnesses;
  publication gates that retain negative and inconclusive outcomes.

See the [capability catalog](shipped-capabilities.md) for entry points and the
[working-context guide](working-context.md) for current limits. Adaptive working
context requires installation from Git until the next package release.

## Next hard problems

| Work | Why it matters | Evidence needed |
|---|---|---|
| Held-out long-session coding evaluation | Component correctness does not prove better coding | Frozen tasks, repeated paired runs, independent grading, usage and failure traces |
| Child-agent working state and handoff | Parent and child agents need separate goals with deliberate sharing | Isolation, fan-out/fan-in, interrupted delivery, and adversarial handoff tests |
| More expressive source anchors | File-level invalidation is safe but coarse | Symbol/range anchors with rename, generated-file, and multi-file change cases |
| Better recovery after delivery failure | Hooks can fail after state records a delivery | Observable acknowledgment/retry behavior without repeat floods |
| Semantic memory conflict evaluation | Explicit contradiction edges do not discover every contradiction | Human-reviewed conflict corpus and precision/recall with abstention |
| MCP 2 migration | The current implementation deliberately caps MCP below 2 | Update renamed APIs and run server/client integration coverage before lifting the cap |

## Further exploration

- Native working-context integration for additional coding agents, guided by their
  supported lifecycle interfaces.
- Better usage/cost coverage where agent CLIs expose stable fields.
- Human review flows for stale memories and promotion decisions.
- Full Windows behavior testing beyond the current smoke gate.
- Independent external replications and published repository case studies.

## Product boundaries

ONMC should remain useful locally, without a hosted account, mandatory vector
service, or model call for every context refresh. It assists the coding agent;
perfect instruction adherence and general correctness are not achievable promises.
