# PRD — Ledger-OS: the memory, eval & harness layer for coding agents

> One sentence: **every retention and evolution decision an agent system makes —
> what to remember, distill, compact, retrieve, load, or ship — must earn its
> place with measured, sealed evidence.**
>
> Companions: `coding-agent-frontier-2026.md` (research basis),
> `onmc-2027-checklist.md` (business surfaces). This PRD is the build contract.

## Users

1. **Agent operators** (teams running Claude Code/Codex fleets on real repos) —
   want fewer false-greens, provable improvement, no memory rot.
2. **Harness researchers** — want a substrate where memory/context/eval claims
   are measurable and reproducible.
3. (later) **Compliance owners** — want the attested audit trail.

## The three layers and their features

### Layer 1 — Memory (earn, measure, retire)

| # | Feature | Status | Acceptance gate |
|---|---|---|---|
| M1 | Gated ingestion (sanitize→scope→shadow→promote) | ✅ shipped | poison with findings can never reach a sink |
| M2 | Sanitizer hardening (exec-fetch, key prefixes) | ✅ shipped | e2e strings 9/9 |
| M3 | Attribution ledger (leave-one-out lift + CIs) | ✅ shipped | harmful memory measurably negative |
| M4 | Procedural distillation (R2) | ✅ shipped | unverified runs never teach |
| M5 | Evidence-weighted skill routing | ✅ shipped | HARMFUL never loads |
| M6 | Retirement→rollback wiring | ✅ shipped | HARMFUL verdict ⇒ sink removal + gate rollback, one call — met |
| M7 | Hosted store (Supabase, RLS, pgvector) | ✅ shipped | retire = timestamp, never delete |
| M8 | Temporal validity windows (Graphiti-style) | ✅ shipped | stale memory queryable by time, expires from recall — met |
| M9 | Memory export adapters (mem0/Zep) | ✅ shipped | earned flows out with evidence; harmful/unmeasured refused by name — met |

### Layer 2 — Eval (the repo's own truth)

| # | Feature | Status | Acceptance gate |
|---|---|---|---|
| E1 | Experiment kernel (seeded bootstrap CIs, paired) | ✅ shipped | deterministic under seed |
| E2 | repo-bench compiler (history → private benchmark) | ✅ shipped | round-trip: bug fails gate, fix passes |
| E3 | A/B harness + measured +0.267 pass@1 | ✅ shipped (internal) | paired, seeded, cost tracked |
| E4 | Compaction-policy scoring (lift per token freed) | ✅ shipped | decay-rejecting, CI-ranked, fail-closed — met |
| E5 | Corpus hygiene (saturation, leakage labels) | ✅ shipped | saturated + dead tasks auto-flagged across trials — met |
| E6 | External benchmark run (3 repos × 3 trials) | next (~$40) | flips claims internal→external |
| E7 | SWE-bench-format export | ✅ shipped | jsonl instances from real mined tasks; patch inversion round-trips — met |

### Layer 3 — Harness (fail-closed, self-evolving, attested)

| # | Feature | Status | Acceptance gate |
|---|---|---|---|
| H1 | Fail-closed completion gate + false-green detection | ✅ shipped | no verifier ⇒ never verified |
| H2 | Reference monitor (enforced default) + injection suite | ✅ shipped | deny ⇒ no side effect |
| H3 | Coverage-graded verification (changed lines executed) | ✅ shipped | unexecuted change ⇒ unverified |
| H4 | Verified compaction gate (R1) | ✅ shipped | lost constraint ⇒ rejected, named, repairable |
| H5 | Hierarchical retrieval interfaces (R3) | ✅ shipped | every view tagged for attribution |
| H6 | CI-gated harness evolution (R4) | ✅ shipped | noise provably never promotes |
| H7 | in-toto/DSSE attestation | ✅ shipped | cosign/gh-attestation-compatible shape |
| H8 | OTLP export (verdicts/ledger/enforcement) | ✅ shipped | renders in any OTel backend |
| H9 | Provable self-improvement demo | ✅ shipped | `python -m oh_no_my_claudecode.demo.self_improvement` — met |
| H10 | Sigstore keyless signer impl | ✅ shipped (adapter) | optional `attest` extra; live rekor signature needs OIDC identity (user) |
| H11 | Product-gate bytecode hardening | ✅ shipped | gates never write or trust bytecode caches — met |

## Architecture (data flow)

```
 agent run ──receipt──► [H1 gate + H3 coverage] ──verified──► episodic store
     │                                                        │
     │ context grows                                          ▼
     ▼                                            [M4 distill workflows]
 [H4 compaction gate] ◄─policy scores── [E4]                  │
     │                                                        ▼
     ▼                                     [M1 gate: sanitize→shadow→promote]
 compacted view                                               │
                                                              ▼
 [H5 retrieval ifaces] ──tagged──► [M3 attribution on E2 repo-bench]
     ▲                                      │ EARNING / HARMFUL
     └────routing weights── [M5 router] ◄───┤
                                            ▼
                              [M6 retire] + [H6 evolve] ──► [H7 attest] ─► [M7 hosted / H8 OTLP]
```

## Milestones

- **M-now — ✅ COMPLETE (2026-08-17):** M6 · M8 · E4 · H9 · H11 · M2 all landed;
  every loop the research agenda opened is closed.
- **M-next — ✅ buildable half COMPLETE (2026-08-17):** H10 · E5 · E7 · M9 landed.
- **Blocked on user resources:** E6 external run (~$40 approval) · live sigstore
  signing (OIDC identity) · Supabase creds · hosted nightly runs (E2B account).

## Non-goals

Dashboards (OTel export instead) · storage engines (Supabase/sqlite instead) ·
LLM-judge scoring (executed tests only) · auto-spend without explicit approval.

## Risks

Sanitizer is pattern-based (bypassable — mitigated by shadow-eval + attribution
as second/third gates) · repo-bench task validity rots (E5) · single-repo
evidence until E6 runs.
