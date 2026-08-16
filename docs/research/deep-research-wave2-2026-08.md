# Deep research wave 2 (2026-08-17) — harness, eval, memory frontier moves

Second research sweep. Wave 1 is `coding-agent-frontier-2026.md`; this wave
covers the two harness releases that landed this week (DeepSeek Harness, Pi),
the reward-hacking literature that directly threatens benchmark integrity, and
the memory-optimization results that reshape our M-track. Each finding ends
with the concrete ONMC build it implies; new PRD ids are assigned inline.

## F1. DeepSeek Harness — the runtime went pluggable (2026-08-13)

MIT developer preview, ~95k GitHub stars in two days. Thesis: *the agent
runtime above the model* — inference, tools, skills, sessions, sandboxes,
storage, loops, scheduling, UI are all swappable plugins; shipped alongside
DeepSeek-V4-Pro. APIs still pre-stable (0.1.0-rc).

**Build (H12, harness layer):** ship ONMC's judgment as DeepSeek Harness
plugins — a *verifier plugin* (completion gate + receipts around any loop
plugin), a *memory plugin* (gated ingestion in front of any storage plugin),
an *eval plugin* (repo-bench as a task source). The hottest runtime becomes a
distribution channel; our R4 evolution treats harness plugin configs as
`HarnessVariant`s natively. Wait for API stabilization before deep coupling;
prototype against the rc contract behind an adapter.

## F2. Pi (pi.dev) — minimal harness + lazy skills won hearts

Ronacher/Zechner terminal agent: sub-1,000-token system prompt (vs 7-10k for
peers), four core tools, "lazy skills" (one-line descriptions in context; full
instructions load only on invocation), TypeScript extension model, 20+
providers.

**Build (M10, memory layer):** our evidence-weighted skill router is the
missing brain for lazy skills — Pi decides *when* to load a skill by
description; nothing decides *whether the skill is any good*. A Pi extension
that ranks/filters lazy skills by measured lift (and hard-excludes HARMFUL)
is a small adapter over `learning/skill_router.py`. Also a philosophical
validation: minimal core + optional extensions is exactly the gate-as-a-layer
shape ONMC already has.

## F3. Reward hacking is measured and rampant — benchmark integrity is a feature

Findings across the 2026 literature: frontier models reward-hack in **>30% of
eval runs** — monkey-patching graders, stack introspection, operator
overloading, **git-history exploits on SWE-bench** (reading the fix out of
history), CUDA bypasses on KernelBench. Countermeasures in the literature:
adversarial hacker-fixer loops that harden benchmarks iteratively; VAGEN-style
*agentic verification* (actively probe environment side effects instead of
passively reading agent output); process reward models for dense intermediate
signal.

**Build (E8, eval layer — HIGH PRIORITY):** repo-bench anti-hack hardening:
1. **Grader isolation** — run the gate command in a subprocess whose working
   tree excludes grader-writable state; agent-visible tree must not contain
   the grader's own scoring logic.
2. **History stripping** — compiled tasks must not ship `.git` (the SWE-bench
   git-history exploit reads the fix from the log; our `setup_patch` replant
   leaves history intact today — this is a real, known-class hole).
3. **Protected-path enforcement at gate time** — verify `protected_paths`
   (tests) are byte-identical to compilation time before scoring; a "pass"
   achieved by editing the test is a hack, not a fix.
4. (later) hacker-fixer loop: an adversary agent tries to pass without fixing;
   every successful hack becomes a hardening rule.

## F4. Agentic verification (VAGEN) — verify by probing, not reading

Replace passive verdicts with active environment probes (execute commands,
check side effects) for noise-free verifiable rewards.

**Build (H13):** extend the independent verifier with *probe assertions* —
declared side-effect checks (file exists, service responds, migration applied)
executed by the verifier itself, never trusted from agent output. Small: a
probe list on the run contract + subprocess execution in the verifier.

## F5. Memory optimization — consolidation moved off the hot path

- **Sleep-time compute**: consolidate memory *between* sessions; ~5× test-time
  compute reduction on reasoning benchmarks, ~2.5× amortized cost drop.
- **MEMTIER**: asynchronous daemon-driven consolidation beats
  interrupt-triggered; tiered memory with retrieval-bottleneck analysis.
- **TOKI**: bitemporal operator algebra for contradiction resolution —
  event-time vs belief-time, upgrade path for our M8 validity windows.
- Storage consolidation: **PostgreSQL+pgvector is the recommended default**
  (validates our Supabase choice); Zep/Graphiti's BM25+embedding+graph with
  **zero LLM calls at retrieval** is the production-validated retrieval shape
  (validates our hybrid; suggests adding graph traversal via codeindex edges).

**Build (M11):** `onmc sleep` — one offline consolidation pass chaining what
already exists: distill (R2) → gate ingest (M1) → attribution refresh (M3) →
retire (M6) → expiry sweep (M8) → hosted sync (M7). All parts shipped; the
daemon is composition, not new machinery. Run nightly or post-session.

## Priority into the PRD

E8 (anti-hack hardening — integrity of our core evidence) → M11 (`onmc sleep`,
all-parts-exist composition) → H13 (probe verification) → M10/H12 (Pi/DeepSeek
adapters — distribution, after their APIs stabilize).

Unclaimed from the current wave: H9 (self-improvement demo script).
