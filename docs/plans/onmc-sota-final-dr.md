# ONMC SOTA Final DR

Status: active fan-out.

## Decision

ONMC should not grow by adding more shallow commands. ONMC should become an
agent-neutral runtime layer above Claude Code, Codex, and OpenCode, with one
canonical execution contract, measured context, verifier-backed completion, and
evidence strong enough to reject overclaims.

## Current Baseline

- `v0.113.0` tag created from main.
- Publication evidence now includes runtime delegation audit.
- Runtime delegation audit is ready:
  - `mission`: 9-node `RunSpec`, digest validated.
  - `wrap`: 9-node `RunSpec`, digest validated.
  - `swarm`: 3-node fan-out/fan-in `RunSpec`, digest validated.
- Publication readiness remains false by design until external benchmark matrix
  passes task count, arm count, seeds, cost telemetry, raw artifacts, and leakage
  audit gates.

## Parallel Lanes

Each lane must refresh from latest main, preserve dirty work, skip already-built
features, implement only its own area, run focused integration/e2e smoke, commit,
push, and open a PR. No lane releases.

1. RAG/context engine
   - measured retrieval policy
   - provenance/confidence/token-budget reporting
   - hybrid fallback
   - eval-gated promotion artifact

2. Trajectory router
   - model decisions from observed traces
   - shadow routing
   - regret/cost report
   - publication artifact

3. LangGraph/DAG backend
   - optional backend over canonical `RunSpec`
   - deterministic parity
   - interrupt/resume/cancel where feasible
   - safe fallback without optional dependency

4. Sandbox/isolation
   - isolated default for autonomous runs
   - sandbox manifest in `RunSpec`
   - safe fallback when Docker/Harbor absent
   - verifier artifact proves isolation mode

5. Verifier/evidence
   - no prose-only completion
   - protected-test and policy gates
   - verifier calibration
   - negative/mutation controls

6. Telemetry/Mission Control
   - observed runtime graph only
   - evidence/cost/context/decision panels
   - no synthetic progress
   - compact terminal fallback

7. Harbor/repro benchmark
   - pinned container eval manifest
   - raw trajectory/verifier artifact checks
   - leakage boundary
   - reproduce docs

8. One-command UX
   - one setup, one task path
   - clear checklist/status
   - primary help stays small
   - docs grounded in shipped features

9. Swarm graph/runtime fanout
   - dependency-aware fan-out/fan-in
   - cancellation/abort/resume semantics
   - receipt aggregation
   - claim conflict handling

## Fan-In Rule

Merge PRs in this order:

1. Verifier/evidence
2. Sandbox/isolation
3. RAG/context engine
4. Trajectory router
5. Swarm graph/runtime fanout
6. LangGraph/DAG backend
7. Telemetry/Mission Control
8. Harbor/repro benchmark
9. One-command UX

After every two merged PRs:

- regenerate evidence
- run focused integration battery
- run `onmc release --check --json`

After all lanes:

- run full CI
- run product smoke
- run runtime delegation audit
- run benchmark/evidence report generation
- release one final version only if CI and release workflow pass

## Stop Rule

Do not wait forever on one lane. If a PR is blocked:

- record blocker in this DR or follow-up report
- merge independent green PRs first
- return to blocked lane after fan-in

## Claim Rule

Allowed now:

> ONMC records and gates coding-agent runtime evidence across mission, wrap, and
> swarm workflows using canonical runtime contracts.

Not allowed yet:

> ONMC is SOTA or better than plain Claude Code.

That claim requires the full external benchmark matrix to pass.
