# U11/U12 governed learning and adapter parity evidence

Date: 2026-07-26  
Branch: `codex/u11-u12-parity-learning`  
Base: refreshed `origin/main` at `7f30934197ece425a26bccaf57c1218c01e19b9c`

## Scope

This is an independent, local-only slice of U11 and U12. It adds:

- a complete, machine-readable capability row for Claude, Codex, and OpenCode;
- recorded fixtures that exercise the existing one-shot adapters without provider calls;
- classified failures for unsupported or asymmetric provider capabilities;
- a quarantined-by-default learning registry;
- a promotion manifest requiring a pre-registered prediction, frozen dataset revision,
  measured held-out result, protected-suite non-regression result, provenance, scope, and
  rollback pointer;
- idempotent promotion plus rollback that preserves the prediction and evidence.

No paid or live provider calls were made.

## Recorded adapter matrix

`supported` means the current loop adapter implements the capability completely.
`partial` is intentionally not treated as comparable support.

| Provider | Start | Observe | Cancel | Resume | Cost |
|---|---|---|---|---|---|
| Claude | supported | supported | partial: process timeout only | unsupported | partial: only when `total_cost_usd` is emitted |
| Codex | supported | supported | partial: process timeout only | unsupported | unsupported |
| OpenCode | supported | supported | partial: process timeout only | unsupported | unsupported |

The full matrix also labels model selection, effort, structured output, usage, and tool
limits. Every provider declares every field, so matrix declaration coverage is 100%.
That does **not** mean every provider supports every capability. Shared comparisons include
only fields marked `supported` in every arm; cost, usage, cancellation, resume, effort, and
structured output are excluded from the three-provider shared set today.

Recorded fixtures:

- `tests/fixtures/adapter_conformance/claude.json`
- `tests/fixtures/adapter_conformance/codex.json`
- `tests/fixtures/adapter_conformance/opencode.json`

Each fixture pins a recorded CLI-version label, start invocation, observation payload, cost
expectation, and the explicit cancellation/resume limitation. The tests inject the recordings
through `CommandRunner`; they also fail if a live subprocess path is used.

## Governed promotion contract

A candidate is registered as `quarantined` before evaluation. It can become `promoted` only
when all of these fields pass:

1. a component-specific, falsifiable metric prediction;
2. a non-empty frozen dataset revision;
3. a measured held-out result matching the candidate evaluation;
4. improvement greater than the pre-registered minimum effect;
5. both the manifest and evaluation confirm protected-suite non-regression;
6. non-empty provenance and bounded scope;
7. a non-empty rollback pointer.

Incomplete, training-only, held-out-regressing, protected-regressing, or mismatched candidates
remain quarantined with machine-readable reasons. Re-submitting the same candidate and manifest
is idempotent. Reusing the candidate id with a different manifest is rejected. Rollback makes
the candidate inactive while retaining its prediction, dataset revision, evidence, and pointer.

## Verification

Focused contract suite:

```text
PYTHONPATH=src:. <venv>/bin/pytest -q \
  tests/test_loop_adapters.py \
  tests/test_adapter_conformance.py \
  tests/test_learning*.py \
  tests/test_experiment_kernel.py \
  tests/test_runtime_contracts.py

184 passed in 3.87s
```

Focused style and types:

```text
<venv>/bin/ruff check .
All checks passed!

<venv>/bin/mypy src
Success: no issues found in 591 source files
```

## Remaining gaps

- The current adapters are synchronous one-shot processes. Cancellation is timeout-based, not
  handle-based, and no adapter exposes resumable session identity.
- Codex and OpenCode cost remains unknown. Claude cost is only partially available. A matched
  cost claim across these adapters is therefore refused.
- These fixtures establish deterministic parser and declared-contract conformance, not live CLI
  compatibility. Live smoke remains opt-in and was intentionally not run.
- The governed registry is currently in-process. Durable persistence and runtime event emission
  remain follow-up integration work.
- Existing legacy learning entry points still use the earlier promotion gate. Wiring every
  production memory and harness path through `GovernedPromotionService` is not claimed here.
- This evidence supports these U11/U12 slices only. It does not satisfy the plan's external
  adapter-parity, held-out benchmark, or SOTA promotion gates.
