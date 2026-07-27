# ONMC SOTA Final DR

Status: active fan-out, final decision record for consolidation.

## Decision

ONMC should not grow by adding more shallow commands. ONMC should become an
agent-neutral runtime layer above Claude Code, Codex, and OpenCode, with one
canonical execution contract, measured context, verifier-backed completion, and
evidence strong enough to reject overclaims.

## Current Baseline

- `v0.113.0` tag created from main.
- `v0.113.0` release workflow passed end-to-end, including PyPI publish and
  PyPI install verification.
- Latest main has two post-release evidence commits:
  - `docs: record onmc sota fanout decision`
  - `docs(evidence): add sota readiness audit`
- Publication evidence now includes runtime delegation audit.
- Runtime delegation audit is ready:
  - `mission`: 9-node `RunSpec`, digest validated.
  - `wrap`: 9-node `RunSpec`, digest validated.
  - `swarm`: 3-node fan-out/fan-in `RunSpec`, digest validated.
- SOTA readiness audit exists and is intentionally not publication-ready:
  - proven requirements: 2
  - partial requirements: 15
  - blocked requirements: 2
  - missing requirements: 0
  - ready requirements: 2/19
- Publication readiness remains false by design until external benchmark matrix
  passes task count, arm count, seeds, cost telemetry, raw artifacts, and leakage
  audit gates.

## Live PR State

Current fan-out PRs:

1. [#413](https://github.com/adaline-ankit/oh-no-my-claudecode/pull/413)
   `test(runtime): cover LangGraph DAG and cancellation parity`
   - lane: LangGraph/DAG backend
   - status: CI running on Python 3.11, 3.12, and 3.13
   - local smoke: `tests/test_langgraph_backend.py` passed with 12 passed,
     1 skipped
   - action: merge after CI green
2. [#414](https://github.com/adaline-ankit/oh-no-my-claudecode/pull/414)
   `feat(experiment): gate publication on routing evidence`
   - lane: trajectory router
   - status: CI running
   - action: review after checks complete
3. [#415](https://github.com/adaline-ankit/oh-no-my-claudecode/pull/415)
   `feat(experiment): bind verifier evidence to publication`
   - lane: verifier/evidence
   - status: merge conflict
   - action: update from main, resolve conflict, rerun focused tests, then
     merge before router if green
4. [#416](https://github.com/adaline-ankit/oh-no-my-claudecode/pull/416)
   `feat(cli): unify setup and task onboarding`
   - lane: one-command UX
   - status: CI running
   - action: review after checks complete; merge late because it changes user
     surface
5. [#417](https://github.com/adaline-ankit/oh-no-my-claudecode/pull/417)
   `feat(experiment): pin Harbor reproduction contract`
   - lane: Harbor/repro benchmark
   - status: CI queued/running
   - action: review after checks complete; merge after verifier/router evidence

Current main checks for `docs(evidence): add sota readiness audit`:

- CodeQL: green
- Scorecard: green
- Pages: green
- CI: still running

## Active Sessions

Nine independent sessions are allowed to continue in separate worktrees. They
must open or update their own PRs only; they must not release.

- RAG/context engine: `019f9f82-383e-7811-855c-537de978ffff`
- Trajectory router: `019f9f82-3acd-70d2-9d37-c84d0e5f50f1`
- LangGraph/DAG backend: `019f9f82-35d4-7902-8139-77d1dcf33aee`
- Sandbox/isolation: `019f9f84-e2c4-7e50-b6db-37a555218b5f`
- Verifier/evidence: `019f9f84-e54e-7230-8d7d-c1de1e43bebf`
- Telemetry/Mission Control: `019f9f84-e899-7803-9fd9-3261e840d91b`
- Harbor/repro benchmark: `019f9f85-4bc5-7753-8d62-71704386230b`
- One-command UX: `019f9f82-3e02-7d11-8af9-b1d9c40fa2d3`
- Swarm graph/runtime fanout: `019f9f84-e075-7f42-8679-288b00b3991e`

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
