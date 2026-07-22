# ONMC execution harness

`onmc run TASK` is the public controller that composes ONMC's task compiler,
context planner, durable runtime, proof graph, policy broker, and existing
memory-grounded loop.

Planning is the safe default:

```bash
onmc run "fix cache invalidation" --plan-only
onmc run "fix cache invalidation" --json
```

The deterministic plan contains the run ID, typed DAG, cited repository context packet, proof
requirements, broker decisions, durable state path, and resume command. Planning
does not invoke an agent or verifier and does not create durable run state.

Execution must be explicit:

```bash
onmc run "fix cache invalidation" --execute \
  --agent codex \
  --model gpt-5 \
  --verifier "pytest -q tests/test_cache.py" \
  --max-iterations 5 \
  --max-cost-usd 2 \
  --isolate \
  --risk high \
  --context-budget 12000
```

Run `onmc init` before execution so the existing loop can use the repository's
memory store. The built-in policy allows the supported agent adapters and local
`pytest`, `python -m pytest`, `ruff`, and `mypy` verifier commands. Other
verifiers are visible in plan output but execution is denied unless an injected
policy explicitly allows them. Verifiers execute as parsed argument vectors,
never through a shell.

The same context packet shown during planning is injected into every execution
attempt with source citations. Secret-like files, binary files, generated state,
dependency directories, and oversized files are excluded from retrieval. Default
budget is 4,000 estimated tokens; raise `--context-budget` only when needed.

Every executing run persists append-only run and node transitions under the
plan's `state_path`. A resumable loop checkpoint is maintained by the existing
loop engine. Resume or inspect the same durable run with:

```bash
onmc run "fix cache invalidation" --execute --resume RUN_ID
```

A run is `completed` only when the existing loop converges and its final
configured verifier supplies proof-graph evidence. Agent assertions alone do
not satisfy proof requirements. Policy denial, loop exhaustion, agent errors,
and incomplete proof are reported as non-success statuses and return a non-zero
exit code during `--execute`.
