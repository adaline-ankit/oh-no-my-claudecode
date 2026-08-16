# ONMC — The Product Plan (2026 → 2027)

> **The product in one sentence:** the Reliability Ledger for coding agents —
> every artifact an agent produces or consumes (a PR, a memory, a skill, a
> model choice) gets a **measured, tamper-evident P&L on your own repo**, and
> everything else (gates, routers, registries) is a surface that consumes it.

Everyone else ships one of the arrows. The moat is the box:

```
                        ┌─────────────────────────────────┐
   verified runs ─────► │        THE LEDGER               │ ◄──── private repo-bench
   (receipts)           │  per-artifact measured lift,    │       (your git history,
                        │  CIs, provenance, verdicts      │        replayed nightly)
                        └───┬──────┬──────┬──────┬────────┘
                            ▼      ▼      ▼      ▼
                       merge    memory   skill   model
                       gate     curation router  routing
```

It exists because three things nobody else has assembled sit underneath:
tamper-evident receipts, a per-repo living benchmark, and an experiment kernel
with real statistics. Legend: `[x]` shipped · `[~]` partial · `[ ]` build.

---

## 1. The engine (built — this is what makes the product possible)

- [x] **Receipts** — tamper-evident, offline-verifiable, coverage-graded ("verified" ⇒ changed lines executed by passing tests), false-green detection, enforcement trace
- [x] **Private repo-bench** — compile YOUR git history into a living benchmark (revert-fix + real-test gates); dogfooded: 5 replayable tasks mined from this repo on first run
- [x] **Experiment kernel** — seeded trials, bootstrap CIs, paired deltas
- [x] **Attribution** — leave-one-out measured lift per artifact (memory/skill/anything), EARNING / UNPROVEN / HARMFUL verdicts, retirement candidates
- [x] **Enforcement** — reference monitor on by default; traversal/exfil/destructive → BLOCKED, never verified
- [x] **Learning gate** — nothing becomes active memory without sanitize → scope → shadow-eval → promotion record; rollback always
- [x] Retrieval competitive: hybrid BM25+dense+RRF, sqlite-vec store, reranker, blast-radius graph expansion
- [x] Evidence-weighted skill router (relevance proposes, ledger disposes; HARMFUL never loads)
- [x] Measured internal result: **0.20 → 0.47 pass@1 (+0.267, CI excludes zero), −26% cost, 90 runs**

## 2. Product surface A — **Trust Gate** (first revenue, ship first)

*"Your agents ship 50 PRs a day. How many can you prove?"*

- [ ] **GitHub Action/App: `onmc verify` as a required PR check** — receipt artifact + plain-English `explain` comment (~80% glue over `nomistakes`+`prbadge`)
- [ ] Quantified false-negative rate (how often we block a good PR — the first buyer question)
- [ ] Auto-merge tier: receipt green + low risk ⇒ merge without a human
- [ ] Receipt signing (sigstore) + frozen public receipt schema (auditor-grade)
- 💰 Infra: GitHub App registration + Marketplace listing; sigstore identity

## 3. Product surface B — **Private SWE-bench** (the platform sell)

*"Which agent/model/config actually works on OUR code — measured nightly."*

- [x] Repo→benchmark compiler
- [ ] Nightly scheduled runs (GH Action first, hosted runners later) + trend line
- [ ] Agent/model comparison report (uses existing A/B suite + kernel; per-task pairing)
- [ ] Corpus hygiene: dedupe, leakage labels, saturation detection (a prior corpus saturated 24/24 both arms — detect and refresh)

## 4. Product surface C — **Earned Memory & Skills** (the groundbreaking claim)

*"Memory hubs store. Self-improvers claim. Skill packs promise. We measure."*

- [x] Gated ingestion (no promotion record → no active memory)
- [x] Per-memory measured lift + evidence-based retirement (poison is measured out — vs the literature's 100% conversational-relapse rate)
- [x] Evidence-weighted skill routing
- [ ] Wire `retirement_candidates` → gate rollback (close the loop live)
- [ ] Skill-pack attribution runs over `agent-skills`-format packs → **measured-badge skill registry**
- [ ] Earned-memory export adapter: ledger-approved subset published to any hub (mem0/Tencent-style) — *be the filter in front of every store*
- [ ] "Provable self-improvement" scripted demo: flywheel promotes → attribution measures → receipt seals

## 5. Product surface D — **Fleet Control** (enterprise tier)

- [x] Org policy file + outcome-learned routing (`autoroute`)
- [ ] Versioned policy packs (protected suites, egress, spend caps) — publish once, fleet consumes
- [ ] Org kill switch (audited)
- [ ] A2A receipt exchange (needs signing)
- [ ] EU-AI-Act audit exports from the receipt registry

## 6. Hosted plane 💰 (only what must be hosted; local-first stays the moat)

- [ ] Receipt registry: start at zero servers (signed receipts on a git ref), graduate to hosted when a team pays
- [ ] Hosted nightly bench runners (tier 2)
- [ ] Fleet-shared earned memory over MCP (tier 3 — the network effect: more verified runs → better shared memory → better agents)
- [x] PyPI distribution (since v0.107)
- [ ] Docs site + 90-second demo (run → receipt → explain)
- [ ] Opt-in telemetry (verified-rate, gate outcomes) — trains 2027 routing

## 7. Money — the $1M ARR shape

| Tier | Price | Who | Needs |
|---|---|---|---|
| OSS CLI | $0 | every dev (funnel) | done |
| Team | ~$20/dev/mo | eng leads drowning in agent PRs | surfaces A+B |
| Platform | $2–5k/mo | teams running fleets | surfaces B+C hosted |
| Compliance | ~$50k/yr | CISO / EU AI Act | surface D + signed registry |

Blend to $1M: ~30–50 teams + 5–8 compliance accounts. De-risk ladder:
Action installs → 10 design partners (measure FN rate) → 3 paying teams →
$100k → $1M. **No certainty is claimed — each rung is a cheap kill-test.**

## 8. Evidence gates (claims we may make, per rung)

- [x] "implemented / internal": everything above marked `[x]`
- [ ] External benchmark (≥3 outside repos, ≥3 trials, ~$35–50) → unlocks public comparative claims
- [ ] Design-partner FN rate → unlocks selling the gate
- Never claimed without the rung: "SOTA", "improves Claude Code", percentages

## 9. Deliberately NOT building

- Another LLM code reviewer (agent-reviews-agent recurses the trust problem)
- Agent runtime/orchestrator (Anthropic's home turf; prime-agent's crowd)
- Memory *storage* (47k-star incumbents; we filter, not store)
- Generic routing infra (NVIDIA Switchyard exists; we interop)
- Hosted agent execution; dashboards beyond local `ui` until someone pays

## 10. Trend radar — GitHub weekly trending, 2026-08-16 (refresh weekly)

| Trending (stars/wk) | Signal | Our move |
|---|---|---|
| `semantica` 5.3k — "Accountable AI" infra | accountability is a category now | we are its evidence engine |
| `TencentDB-Agent-Memory` 4.0k, `macro` 2.4k | team memory hubs mainstream | be the filter, not the store |
| `prime-agent` 8.5k — self-improving agent | hottest claim, zero proof discipline | "self-improving, **and can prove it**" |
| `agent-skills` 3.3k | skills marketplace forming | measured-badge registry (surface C) |
| `Switchyard` (NVIDIA) | routing commoditizing | interop, don't compete |
| `code-graph-rag` 1.7k | code-KG retrieval commoditizing | have it (blast-radius); maintain |

## Order of operations (next 3 moves)

1. **Surface A wedge**: GitHub Action `onmc-verify` (distribution + first revenue path)
2. **Close the C loop**: retirement→rollback wiring + skill-pack attribution (the groundbreaking demo)
3. **Evidence rung**: external benchmark run (unlocks every public claim)
