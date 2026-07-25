# Environment Variables

ONMC's default behavior needs no configuration. A small set of `ONMC_*`
environment variables changes what it injects, captures, or activates at runtime.
They are read from the process environment rather than `.onmc/config.yaml`, so
they can be scoped to a single command:

```bash
ONMC_LEARNING=0 onmc autopilot "fix the failing cache test"
```

Provider credentials are separate. Secrets stay in provider-specific environment
variables and are never written to local config.

Other `ONMC_*` variables exist for plumbing — notification sinks, LLM timeouts,
dashboard token, embedder and reranker selection. Those are described in command
help and the [CLI reference](cli-reference.md). This page covers the switches
that change agent-visible behavior.

## Kill Switches

These default to ON. Accepted off-values are case-insensitive and differ slightly
per switch, so they are listed for each one.

### `ONMC_LEARNING`

The single kill switch for active learned behavior.

- default: on
- off: `0`, `false`, `no`, or `off`

When it is off:

- no learned candidate activates, so learned content cannot influence an agent
- promotion is suppressed, so no candidate becomes eligible for promotion

Both halves are enforced in `oh_no_my_claudecode.learning`: the activation check
refuses every candidate and reports the kill switch as the reason, and the
promotion gate rejects every promotion.

**What this switch covers today.** `ONMC_LEARNING` governs ONMC's eval-gated
learning machinery — the promotion gate and the activation check. In the evidence
levels used by ONMC's own progress record, that machinery is `implemented` (code
plus green tests) and nothing beyond it: routing ONMC's production memory write
paths through the gate is still in progress. ONMC's learning is therefore **not
fully eval-gated today**. The switch and the gate are authoritative wherever a
call site consults them, but code that reads or writes the memory store directly
has not adopted them yet and is unaffected. Treat `ONMC_LEARNING=0` as the switch
for learned behavior specifically, not as a blanket off-switch for ONMC memory —
for that, see `ONMC_AUTOCAPTURE` and `ONMC_RECALL_MIN_SCORE` below.

### `ONMC_FIREWALL`

The context firewall, which routes hook observability events to a side sink
instead of the agent's context window.

- default: on
- off: `0`, `false`, or `no`

Turning it off restores the earlier in-context behavior and stops sink emission.
Recalled memories and skills — and any real safety block — stay in context either
way, and hooks always exit 0 and never block the session.

### `ONMC_AUTOCAPTURE`

SessionEnd auto-capture, which mines the just-ended session transcript into
durable memory (decisions, fixes, invariants) with `source_type=session`.

- default: on
- off: exactly `0`

Auto-capture always exits 0 and never blocks the session. `onmc capture` runs the
same extraction manually.

### `ONMC_EMBEDDINGS`

Local embeddings rerank, which layers semantic cosine similarity over FTS5
search. The built-in embedder is deterministic and dependency-free, so this is on
by default.

- default: on
- off: exactly `0`
- `1`, any other value, or unset: on

## Recall Tuning

These two tune the per-prompt recall hook. Both fall back to their default if the
value cannot be parsed.

### `ONMC_RECALL_MIN_SCORE`

Relevance gate for per-prompt recall. If the top-scored memory does not reach
this score, nothing is injected at all.

- default: `1.5`
- `0.0` disables the gate

### `ONMC_RECALL_MAX_CHARS`

Character budget for the injected recall block. Entries are kept
highest-scored-first and the tail is dropped with a short trailing note.

- `0` opts out of the cap entirely
- unset uses the recall hook's built-in default cap
