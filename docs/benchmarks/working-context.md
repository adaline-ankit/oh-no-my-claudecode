# Working-context benchmark protocol

Protocol recorded before the first run. These are internal, synthetic experiments,
not SWE-bench scores or proof that an agent is reliable on arbitrary repositories.
All failures and ties must remain in the published report.

Latest: [2026-09-19 results, raw rows, and coding artifacts](results/2026-09-19-working-context/README.md).

## Component benchmark

Run `python scripts/benchmark-working-context.py --output /tmp/context.json`.
Default matrix: 100, 1,000, and 10,000 memories; seeds 7, 19, 41; three arms:

- `legacy_pinned`: existing prompt recall in full Markdown (native hooks normally use
  terse rendering), with the same goal and constraints prepended.
- `adaptive`: current working-context compiler, including freshness and delivery deduplication.
- `adaptive_always`: identical compiler, forced to deliver every packet (deduplication ablation).

Each stream starts in a fresh Git repository and SQLite database. All arms receive
identical memories and a 6,000-character budget. Arm order is shuffled by seed.
Optional embedding reranking is disabled for this component comparison. Adaptive
arms receive `cache.py` as the active file, exercising source-reference lookup too.
Thirteen events cover initial delivery, five unchanged repeats, an edit preserving
mtime, restoration, deletion, recreation, quarantine, promotion, and compaction.
The fixture independently declares whether its one relevant claim remains eligible.
Quality checks inspect the current packet. Delivery checks require a full packet on
initial delivery, each state transition, and compaction; unchanged adaptive repeats
must emit nothing. A compiler that always emits nothing fails the delivery oracle.
The baseline has no source freshness policy; its expected failures characterize that
specific missing capability, not inferior reasoning by Claude or Codex.

Report all raw event rows, corpus and implementation hashes, environment, p50/p95
compiler latency, valid-claim omissions, invalid-claim inclusion, constraint/budget
failures, and emitted characters. Setup and native hook process startup are excluded
from latency. Repeated events are correlated; do not claim statistical significance
or call these independent coding tasks. Character savings are not measured LLM token
or billing savings. Noise is unrelated to the query; retrieval difficulty is modest.

## Live coding pilot

Use Codex's existing login with isolated, fresh repositories. Both arms can read the
same current contract and historical notes. The treatment additionally receives an
ONMC packet compiled from those notes and explicit constraints. Current contracts
are authoritative in both arms. Hold model, reasoning effort, timeout, files, and
task prompt constant; alternate arm order. Record all attempts, provider failures,
wall time, available usage, patches, and external test outcomes. No retries selected
for favorable outcomes. Test sources live outside the agent workspace and run only
after the agent exits. Grading copies only `solution.py` to a fresh directory, preloads
stdlib test dependencies, and requires all six tests with no skips. Fixtures and
grading contracts are frozen before model calls. Other runs share a host; this is not
an adversarial sandbox. Raw traces support checking which files the agent accessed.

Run the frozen pilot (six calls, at most 180 seconds each by default):

```bash
python scripts/benchmark-working-context-live.py --check-fixtures
python scripts/benchmark-working-context-live.py \
  --model YOUR_CODEX_MODEL --output /tmp/onmc-live-pilot
```

`--output` must be a new directory. The model is explicit; effort defaults to medium.
User config is ignored for reproducibility; existing Codex authentication is retained.
Compare raw `turn.completed` input, cached-input, and output usage separately. Do not
subtract cached usage or invent dollar estimates. These tasks exercise one initial
packet per fresh run, not native Claude hooks or long-session compaction.

This small pilot measures feasibility and directional effects, not population-level
accuracy. A tie is a valid result. Do not equate adapter output, successful process
exit, or self-reported completion with passing external tests. Infrastructure failures
must be separated from task failures. Costs remain unknown unless reported by provider.

## Existing retrieval benchmark

Run `onmc retrieval-eval --split all --json` without modifying frozen datasets.
Report recall, nDCG, latency, and skips. Keep BM25, hybrid, and dense comparisons even
when a more elaborate retriever loses. Those retrieval scores do not measure coding
success or this working-context feature specifically.
