# Harness Command Migration

ONMC has one execution harness. Commands do not each become independent harnesses.
They become workflows, graph nodes, operator surfaces, or deprecated extras.

## Target Runtime

The target Mission graph is:

```text
intake
  -> retrieve
  -> contract
  -> decompose
  -> policy
  -> execute single | fan out workers
  -> integrate
  -> verify
  -> repair (conditional loop)
  -> prove
  -> learn candidate
  -> eval gate
  -> receipt
```

Every executable node must have typed inputs and outputs, durable state,
idempotency for side effects, an explicit budget, and a falsifiable completion
condition. A node name without work behind it is not a harness stage.

LangGraph is the planned runtime adapter because its checkpointing, interrupts,
conditional edges, subgraphs, and dynamic fan-out match this state machine.
Adoption is blocked until the dependency is pinned in `uv.lock` and exercised by
the normal test matrix. The current `HarnessController` remains the production
runtime until that gate is met.

## Command Classes

### Workflows

These are user outcomes. They may own a complete graph:

- `run`: canonical general-purpose harness.
- `mission`: user-facing plan/execute view over `run`, not a second runtime.
- `autopilot`: full execute, verify, prove, and learn workflow.
- `nomistakes`: protected PR-gate workflow.
- `fixci`: CI-repair specialization.
- `nightshift`: durable long-running workflow.
- `land`: verified integration workflow.

Workflow acceptance rule: it must execute real graph nodes and end in a
verifier-backed receipt. Otherwise it becomes a node, diagnostic, or is removed.

### Graph Nodes

These perform one bounded operation and should be called by workflows:

- Context: `recall`, `guard`, `brief`, `pack`, `codegraph`, `codeindex`,
  `conventions`, `reuse`, `sessionsearch`.
- Planning: `contract`, `spec`, `estimate`, `route`, `claim`, `preflight`.
- Execution support: `loop`, `swarm`, `budget`, `leash`, `mcp`.
- Verification: `check`, `audit`, `verifydiff`, `coverage`, `proptest`, `eval`.
- Proof and learning: `attest`, `approve`, `memstage`, `memory promote`,
  `skillguard`, `selfimprove`.

Node acceptance rule: deterministic output where possible, typed provenance,
explicit failure, and no marketing claim that it controls the full run.

### Operator And Observability Surfaces

These inspect or control running workflows but do not become agent loops:

- `ui`, `tui`, `missioncontrol`, `hud`, `statusline`.
- `trace`, `timeline`, `ledger`, `cost`, `evolution`, `scorecard`.
- `swarm status`, `swarm list`, `swarm abort`.
- `doctor`, `explain`, `why`, `report`.

Surface acceptance rule: display only observed state. Never infer `verified`
from an agent summary or from the presence of a receipt file.

### Integration And Storage

These remain infrastructure:

- `setup`, `hooks`, `plug`, `serve --mcp`.
- `ingest`, `sync`, `mine`, `import`, `federation`.
- `claude-md`, `agentcontext`, `skill export`.

Infrastructure acceptance rule: idempotent, reversible, local-first, and honest
about optional providers and missing credentials.

### Remove From Primary Product

These may remain hidden demos temporarily but must not define ONMC:

- `achievements`, `persona`, `quest`, `soundboard`, `vibe`.
- `roast`, `highlight`, `badge`, `prbadge`, and social-share variants.

Removal rule: if a command does not improve execution, verification, learning,
integration, or diagnosis, hide it from primary help and deprecate it.

## Migration Gates

1. Add a typed node contract and register existing core functions as nodes.
2. Make `mission --execute` delegate to the shared harness.
3. Arm strict interactive sessions from `UserPromptSubmit`; block `Stop` until
   a non-vacuous change passes a detected repository verifier, with bounded
   retries and a wall-clock circuit breaker.
4. Replace static task nodes with executable transitions.
5. Add dependency-aware fan-out and deterministic fan-in.
6. Add persisted approval interrupts and resume.
7. Add held-out eval gating before learning promotion.
8. Stream graph events to UI from the same durable state.
9. Benchmark plain Claude, context-only, single-agent harness, and selective
   swarm under matched models, budgets, repositories, and seeds.
10. Replace the runtime only after graph parity tests and a public-repository
   execution pass.

## Non-Goals

- Do not wrap every command in an LLM loop.
- Do not maintain two permanent orchestration runtimes.
- Do not call advisory routing enforcement.
- Do not call Claude-native inline swarm ONMC-controlled execution.
- Do not claim SOTA without matched outcome evidence.
