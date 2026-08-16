# World-class feature map — every proven idea, landed on ONMC's setup

Method: take each system that demonstrably cracked something (the interview
top-10 across evals/RAG/memory/context/inference/post-training/safety/routing)
and ask one question: *what does this idea become when it lands on a substrate
that has receipts, a private benchmark, and per-artifact measured lift?* The
answers below are ranked; ★ marks the five that are genuinely novel — nobody
can copy them without rebuilding our spine.

## ★1. Verified Cascade ✅ SHIPPED (experiment/cascade.py) — speculative decoding at task scale (from spec-dec + FrugalGPT)

Speculative decoding's shape: cheap generator proposes, expensive verifier
accepts/rejects, exactness preserved. We have the verifier — the completion
gate + repo-bench gate are *acceptance tests for entire patches*.

**Feature:** `onmc cascade` — a cheap model attempts the task first; the gate
verifies; only on gate-fail does the expensive model take over (optionally
seeded with the cheap attempt's diff as a draft). Every acceptance is
receipt-sealed, so the cost saving is *measured*, not vibes: "cascade saved
41% of spend at equal verified pass-rate, CI [x, y]."
**Lands on:** completion gate (H1), evolve harness (R4: cascade-vs-direct is a
`HarnessVariant` tournament), cost tracking (E3).
**Why world-class:** RouteLLM routes on predicted difficulty; FrugalGPT
cascades on judge scores. Nobody cascades on *executed verification* — the
only acceptance signal that can't be gamed.

## ★2. RLVR Export ✅ SHIPPED (evals/rlvr_export.py) — your repo's verified history as a training set (from RLVR/GRPO + LoRA)

The frontier converged on "reward only what can be verified." Our receipts ARE
verifiable rewards at software-engineering grain: trajectory + executed-test
outcome + coverage grade + cost.

**Feature:** `onmc export-rlvr` — emit (prompt, trajectory, verified-reward)
tuples from the receipt store in a trainer-ready format, filtered to
gate-verified episodes only (false-greens excluded *by construction*). Teams
LoRA-tune a repo-specialist model on their own verified history; repo-bench
then measures whether the tune actually lifted (the eval for the training the
export enabled — the loop closes).
**Lands on:** receipts (H1), attestation (H7 — training-data provenance!),
repo-bench (E2) as the post-tune eval.
**Why world-class:** everyone wants RLVR data; nobody has a *provenance-clean,
false-green-filtered* source of it per private repo.

## ★3. Agent Arena ✅ SHIPPED (experiment/arena.py) — Bradley-Terry on your own repo (from LMSYS Arena)

Arena's crack: paired battles + Elo when absolute scores lie. Our A/B harness
already produces paired per-task outcomes between agent configs.

**Feature:** `onmc arena` — every pair of harness variants/agents/models that
ran the same repo-bench tasks feeds a Bradley-Terry rating; the repo gets a
private leaderboard with uncertainty bands (kernel bootstrap). New variant?
It plays the champion (R4) and enters the ladder.
**Lands on:** evolve (R4) supplies the paired scores; stats kernel (E1) the
CIs; OTLP (H8) renders the ladder in any dashboard.
**Why world-class:** public leaderboards rank models on other people's code.
No product gives a team an Elo ladder on *their* codebase.

## ★4. Outcome-driven context eviction ✅ SHIPPED (context_engine/eviction.py) (from MemGPT + Generative Agents)

MemGPT treats context as RAM with paging; Generative Agents score memories by
recency × importance × relevance — with *importance guessed by an LLM*.

**Feature:** context paging where importance = **measured lift**. Eviction
order: HARMFUL (never admitted) → UNPROVEN-stale (M8 windows) → low-lift →
high-lift last; load-bearing constraints (R1 set) are unevictable. Recency and
relevance from existing recall; importance is the ledger's number, not an
opinion.
**Lands on:** router (M5) generalizes to an eviction ranker; compaction gate
(R1) protects the floor; attribution (M3) supplies importance.
**Why world-class:** the first eviction policy with an evidence-based
importance term — "we page out what provably doesn't pay."

## ★5. Judge Audit ✅ SHIPPED (evals/judge_audit.py) — calibrate any LLM judge against executed truth (from G-Eval literature)

The judge literature's cracks (position bias, verbosity bias, self-preference)
are measurable — *if* you own ground truth. We do: executed-test outcomes on
repo-bench, plus our own G3 measurement (judge AUROC 0.485 ≈ chance) as the
founding war story.

**Feature:** `onmc judge-audit <judge-config>` — run the judge over verified
and false-green episodes from the receipt store; report AUROC, bias decomposition
(verbosity correlation, self-family preference), calibration curve. Verdict:
"this judge adds signal / is chance / is worse than chance on your repo."
**Lands on:** receipts as labeled ground truth; kernel for CIs.
**Why world-class:** every eval platform sells judges; nobody sells the
instrument that tells you whether a judge works *on your distribution*.

## The rest of the map (strong, not unique — build after the five)

| Source idea | ONMC feature | Lands on |
|---|---|---|
| SWE-bench-Verified rot | **Bench doctor**: re-run gate 3× at fix-state (flake), saturation + leakage labels, validity report per task | E2/E5 |
| Inspect (evals-as-code) | repo-bench tasks as versioned solver/scorer code; export adapter | E7 |
| Contextual Retrieval | prepend blast-radius/context header to memories & chunks *before* embedding (fix the index, cache makes it cheap) | M7/H5 |
| GraphRAG | community summaries over codeindex graph → "global" questions (architecture, themes) earned from structure | H5 + codeindex |
| Lost in the Middle | context assembler places constraints + verifier info at edges; middle for bulk | context_engine |
| Prompt caching | stable-prefix layout: order injected context by stability (constitution → earned memories → task); measure cache-hit savings | context_engine |
| Outlines | JSON-schema-constrained emission of iteration contracts/receipts from agents that support it | loop contracts |
| Constitutional AI | **repo constitution**: one versioned, machine-checkable constraint set consumed by compaction gate + monitor + policy packs | R1/H2/D-track |
| CaMeL | taint labels in the monitor: capability separation so untrusted-content readers can't reach side-effectful tools | H2 |
| ColBERT | (experiment only) symbol-level late interaction ≈ our hierarchy's granularity axis; measure before building | R3 |
| SGLang/vLLM lesson | serving-side; adopt via providers, not build | — |
| DPO lesson | reframe-the-objective: keep gates closed-form (already our style) | — |

## Sequencing

1. **Verified Cascade** — immediate cost story, pure composition.
2. **Judge Audit** — small, devastating demo (G3 already proved the need).
3. **Arena** — turns R4 output into a product surface.
4. **RLVR Export** — biggest strategic arc (training flywheel), needs schema care.
5. **Eviction** — after M8/M5 usage data accumulates.
