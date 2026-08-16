# ONMC 2027 Checklist — build today, used in 2027

Premise (from measured 2026 trends): by 2027 agents author most PRs, human
review has structurally collapsed (5.3× pickup lag, 31% merged unreviewed),
EU AI Act enforcement is routine, and fleets of heterogeneous agents
(claude/codex/opencode) run unattended. What 2027 buys is **proof**, not more
generation. Everything below is ordered by that bet.

Legend: `[x]` shipped · `[~]` partial · `[ ]` build next · 💰 = pay/infra setup

## 1. Proof layer (the moat — receipts as the artifact of record)

- [x] Tamper-evident, offline-verifiable run receipts (SHA-256 canonical)
- [x] Coverage-graded verification (changed lines must be executed by passing tests)
- [x] False-green detection (reachability, mutation, agent-claims-never-count)
- [x] Enforced reference monitor + decision trace in the receipt
- [ ] **Receipt signing** (sigstore/minisign) — 2027 auditors need *who* attests, not just *what*
- [ ] **Receipt schema v3 as a portable public spec** (`onmc formats` exists; freeze + version + publish JSON Schema)
- [ ] Receipt chain: link retry/supersede lineage across attempts (durable_runtime has attempts; surface in receipt)

## 2. Merge gate product (the wedge)

- [~] `nomistakes` PR gate + `prbadge` (local; needs the hosted handshake)
- [ ] **GitHub App / Action: `onmc verify` as a required PR status check** — posts receipt artifact + `explain` comment. Shortest path to product; ~80% is glue over nomistakes
- [ ] Quantified **false-negative rate** (how often the gate blocks a good PR) — the number every buyer asks first
- [ ] Auto-merge tier: policy says "receipt green + risk low → merge without human" (this is what 50-PR/day fleets need in 2027)

## 3. Fleet & policy (multi-agent is the 2027 default)

- [x] Org policy file (`policy.toml`) + per-repo enforcement
- [x] Outcome-learned routing (`autoroute` from verified receipts, not keywords)
- [ ] **Policy packs**: versioned, distributable org policies (protected suites, egress, spend caps) — one repo publishes, fleet consumes
- [ ] Kill switch: org-level "stop all agent merges now" (one flag, audited)
- [ ] A2A receipt exchange: agent B trusts agent A's receipt without re-verifying (needs signing first)

## 4. Evidence (what makes any 2027 claim sellable)

- [x] Experiment kernel: seeded trials, bootstrap CIs, paired deltas
- [x] Internal significant result: 0.20 → 0.47 pass@1 (+0.267, CI excludes zero), −26% cost, 90 runs
- [x] M6 external-portfolio harness (audited corpus schema, claim-level gating)
- [ ] **External benchmark run** (≥3 outside repos, ≥3 trials) — the gap between "internal" and a public claim (~$35–50)
- [ ] Publish methodology + raw artifacts (reproduction command already pinned via Harbor contract)

## 5. Retrieval (already competitive; finish the last item)

- [x] Hybrid BM25+dense+RRF, citations, taint, budget modes (BM25-first — measured)
- [x] sqlite-vec persistent vector store, reranker, query decomposition
- [x] Blast-radius graph expansion (callers + covering tests join context)
- [ ] Failure-driven re-retrieval (retrieve again on failed verify — last M2 item; hot loop engine, do carefully)

## 6. Infra to set up now 💰 (cheap today, compounding by 2027)

- [x] PyPI distribution (shipping since v0.107)
- [ ] **GitHub App registration** + marketplace listing (free tier) — the distribution channel
- [ ] **Signing keys / sigstore identity** for receipts (org identity is the 2027 trust anchor)
- [ ] **Hosted receipt registry** — start lazy: signed receipts committed to a git ref (`refs/onmc/receipts`), zero servers; graduate to hosted store only when a team pays
- [ ] Docs site + 90-second demo video of `onmc run` → receipt → `explain`
- [ ] Opt-in anonymous telemetry (verified-rate, gate outcomes) — the dataset that trains 2027 routing

## 7. Deliberately NOT building

- Another LLM code reviewer (agent-reviews-agent recurses the trust problem)
- Agent runtime/orchestrator (crowded; Anthropic's home turf — we verify, not run)
- Hosted agent execution (cost sink; local-first is the differentiator)
- Dashboards beyond the existing local `ui` until a paying team asks

## Order of operations (next 3 moves)

1. GitHub Action `onmc-verify` (wedge, mostly glue)
2. Receipt signing + frozen public schema (unlocks registry + A2A)
3. External benchmark run (unlocks the public claim)
