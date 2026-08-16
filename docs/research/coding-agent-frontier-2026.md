# The Coding-Agent Frontier (research survey, 2026-08) — and ONMC's research agenda

Survey of how 2026 coding agents actually work — context, memory, evals,
retrieval — with the open problems each field names, and the research project
those gaps point at. Sources are public posts/papers; claims here are *their*
claims unless marked measured-by-us.

## 1. Context architecture — compaction is the frontier

- Long sessions span **millions of tokens**; performance degrades with length
  ("context rot"). Compaction is now a *prerequisite* for long-horizon work.
- Claude Code: auto-compact near ~98% of the window. **Codex (GPT-5.x-Codex)
  trains compaction as a native objective** — the model prunes its own history.
- **OpenHands condensers**: nine pluggable strategies, composable; operate at
  the *view* level so the raw event stream is never modified → full replay even
  after aggressive compaction. (The right substrate design.)
- Research: Self-Compacting LM Agents; CompactionRL; DAG-based "context
  virtualization" with structurally lossless trimming.
- ⚠️ **The named open problem — "Governance Decay"**: compaction *silently
  erases safety constraints* in long-horizon agents. Nobody verifies what
  compaction loses.

## 2. Memory architecture — procedural is the prize

- Converged four-tier taxonomy: **in-context / episodic / semantic /
  procedural**. Memory is now an architectural component, not a longer prompt.
- The crux operation: **episodic → semantic distillation** (patterns across
  interactions distilled into reusable knowledge).
- **Procedural memory (workflows, tool habits, review conventions) is called
  the least developed and highest-impact tier.** CLAUDE.md/AGENTS.md is
  validated as lightweight declarative procedural memory.
- Storage: hybrid vector-graph recommended for complex loads.
- Named open problems: staleness in high-relevance memories; poisoning (100%
  conversational-relapse); **no benchmark measures procedural memory quality**.

## 3. Eval architecture — independence and liveness won

- **Terminal-Bench 2.0**: the canonical CLI-agent eval *because it is
  independently governed* — Anthropic, Cursor, Codex all publish against it and
  none controls it. Independence = trust. (Same thesis as our receipts.)
- **Harbor**: containerized multi-agent eval harness; converts native agent
  logs into evaluation trajectories. (We already pin a Harbor reproduction
  contract.)
- **SWE-bench Pro**: consistent ~20–25 pt drop vs Verified across all models —
  the cleanest public contamination/leakage signal in the field.
- Benchmarks are now **versioned & live** (Verified Q1'26 ≠ Q4'25); citation
  without version/date is considered invalid.
- Research direction: *Agentic Harness Engineering* — harnesses that evolve
  themselves from their own observability.

## 4. Retrieval — agentic search beat static RAG for code

- Claude Code's paradigm won: **direct corpus interaction** (grep/ls/cat in a
  plan-act-observe loop) over pre-built embedding indexes; research confirms
  ("Beyond Semantic Similarity").
- Hybrid BM25+dense+RRF beats either alone (matches our own measurement).
- **A-RAG**: hierarchical retrieval *interfaces* exposed to the model — the
  model chooses granularity (repo → file → symbol), rather than being fed
  chunks.
- Repository-level survey: the open problem is *cross-file dependency
  awareness* and retrieval that updates as the agent's understanding changes.

## The gap all four point at (nobody owns it)

Every frontier system decides **what to keep** — context to compact, memories
to store, workflows to distill, retrieval to trust — with *heuristics or
end-to-end training*. None can measure what a retention decision is worth, and
none can verify what a compaction destroyed. We have the two missing
primitives: a per-repo living benchmark (repo-bench) and per-artifact measured
lift (attribution).

## The research project: **an outcome-driven memory & context OS for coding agents**

> Working name: **Ledger-OS**. Thesis: *every retention decision — remember,
> distill, compact, retrieve — is an economic decision, and should be made
> against measured outcome lift, not heuristics.*

Four research tracks, each a paper-shaped question:

### R1. Verified compaction (attacks "Governance Decay")
Compaction gate: declare load-bearing constraints (policies, invariants, task
contract); after any compaction, an independent check proves the constraint
set survives; **measure** compaction policies by re-running repo-bench tasks
under each (lift-per-token-freed). OpenHands-style view-level design so the
raw stream is always replayable. *Novelty: nobody verifies compaction; we can
score it.*

### R2. Procedural distillation with an objective function
Pipeline: verified trajectories (receipts) → episodic store → **workflow
distillation** (the AWM idea) → candidates → attribution measures lift →
promote/retire. The survey says procedural memory lacks any quality benchmark —
attribution + repo-bench *is* that benchmark. *Novelty: the missing objective
function for the "highest-impact tier".*

### R3. Hierarchical agentic retrieval with measured trust
A-RAG-style interfaces (repo → blast-radius graph → symbol) where each
interface's *contribution to task success* is attributed, and retrieval trust
follows measured lift (skill-router generalized to retrieval tools).
*Novelty: retrieval strategies that earn their routing weight.*

### R4. Self-evolving harness with proof
The "harness engineering" direction + our receipts as the fitness signal:
harness variants (compaction policy × memory config × retrieval interface) are
*populations evaluated on repo-bench*, promoted only with CI-backed lift, every
promotion sealed in an attested receipt. *Novelty: self-improvement that is
checkable, vs trained-in-the-dark.*

### Evaluation plan (credibility by construction)
- Terminal-Bench 2.0 + SWE-bench-Pro-style contamination hygiene for external
  validity; repo-bench for per-repo statistical power; Harbor contract for
  reproduction; all claims versioned/dated; negative results retained.

### Build substrate (rent the rails)
Supabase/pgvector (hosted episodic+semantic store — shipped), OpenHands
condenser pattern (view-level, replayable), sqlite-vec local, OTel export
(shipped), in-toto attestations (shipped), E2B/Firecracker for eval isolation.

### Order
R2 first (all pieces exist; distillation is the only new part) → R1 (compaction
gate; highest novelty) → R3 → R4 (capstone).
