# ONMC SOTA Progress

Living record of the SOTA blueprint execution. Every row states its **evidence
level**: `implemented` (code + green tests), `internal` (measured on our own
fixtures/corpus), `external` (measured on outside repos), or `reproducible`
(externally reproducible per the blueprint claim protocol). No "SOTA" or
"improves Claude Code" claim is made until a row reaches `reproducible`.

## Baselines (re-measured, not assumed)

| Date | Main SHA | Suite | Result | Evidence |
|---|---|---|---|---|
| 2026-07-24 | `cb89e93` | retrieval code split (BM25 vs hybrid) | BM25 R@5 **0.95** / R@10 **1.0** / MRR **0.8101** / nDCG **0.8574** / p50 **0.44 ms**; hybrid R@5 0.875 / nDCG 0.8082 / p50 10.4 ms | internal |

**Entitlement check:** BM25 still beats hybrid on the frozen code split, and
`HybridRepositoryCandidateProvider.retrieval_mode` defaults to `"bm25"` (hybrid
opt-in). The default is correctly the measured winner — no wrongly-defaulted
hybrid. dataset_sha `8e8f6d52…`.

## Capability matrix (main @ `cb89e93`)

| Capability | Main state | Open-PR overlap | Measured evidence | Missing gate | Evidence level |
|---|---|---|---|---|---|
| Harness typed stages + run-policy + hardened proof gate | merged **#374** | (my #376 closed/superseded) | tests on main | enforced (non-advisory) capability path; external proof | implemented |
| Context/RAG: citations, taint, budget modes, BM25-first | merged **#375** (= HEAD) | — | baseline above | held-out end-task success on external repos | implemented / internal |
| Loop vacuous-pass gate + `ChangeProbe` | merged **#318/#351/#358** | #339 (superseded) | tests on main | swarm-orchestrator port; permissions hint | implemented |
| Golden path (`run`/`explain`/`doctor`) + release `--check` | **in flight #378** | — | none yet | fresh-user smoke; adapter conformance | (pending) |
| Shared experiment contracts | **merged #379** | — | 13 unit tests | consumed by kernel/envelope/learning | implemented |
| Experiment kernel (M1) | **merged #381** | — | 17 unit tests | real-adapter trials; external portfolio | implemented |
| Complete run envelope (M1) | **merged #382** | reuses `trace/`+`tool_broker.redaction`+`harness_run.receipt` | 8 unit tests (+46 trace unaffected) | live-run capture at scale | implemented |
| Eval-gated repository learning (M3) | **merged #383** | — | 15 unit + challenge sets | wired through memory/loop; held-out promotion | implemented |
| **`onmc run` vertical wiring** (monitor + verifier live) | **merged #387** | — | 5 wiring tests + 44 harness unchanged | live wiring of real adapters + enforced-by-default where safe | implemented / wired |

**Integration (landed 2026-07-24, main `330b77e`).** Merged in order
#379→#381→#382→#383 via the ruleset lander (update-branch → 7 required checks
green → squash `--admin`). Re-verified from a **fresh `main` checkout**: `ruff`
clean, `mypy --strict` clean (14 files), **53/53** focused tests pass. No
benchmark regression (additive new modules; retrieval baseline unchanged). This
is `implemented`/`internal` — not yet external or reproducible product evidence.

**M4 landed (2026-07-24).** `enforcement/` (#385) + `verifier/` (#384) merged via
the ruleset lander; re-verified fresh `main`: ruff+mypy clean (7 files), **52**
M4 tests pass, and 131 existing enforcement + 45 verifier tests unaffected. The
ReferenceMonitor *composes* `tool_broker`/`mcp_trust` (never loosens a broker
DENY; provenance is recorded but never consulted in a verdict, so injected prose
cannot flip a decision). Still `implemented`, not external: the monitor and
verifier are libraries — wiring them into live `onmc run` execution and real
coverage/mutant-runner adapters is the next behavioral-change workstream.

**M4 wired into `onmc run` (#387, main `82f6ad7`).** The `ReferenceMonitor` now
runs on every executing run — guarding the observed change-set effects and
recording its decision trace on `HarnessResult.enforcement_trace` — and the
independent verifier is folded into `proof_complete` as an extra false-green
gate. **Additive and behavior-preserving by default:** advisory monitor (records,
never blocks) + dormant verifier (no-op without coverage/contract evidence), so
the 44 existing harness tests are unchanged; 5 new wiring tests prove advisory
recording, enforced-mode blocking (opt-in → `BLOCKED`, never verified), and a
false-green downgrade. Enforced enforcement + real coverage/mutant adapters
remain opt-in/next. Still `implemented`/`internal`.
| Enforced capability path (M4-E) | **merged #385** + **wired into `onmc run` #387** | — | 21 tests + 5 wiring tests | enforced-by-default (currently advisory default); container isolation profile | implemented |
| Injection/attack challenge suite (M4-Sec) | **merged #385** | reuses `learning.sanitize` | indirect injection, traversal, destructive cmd, secret exfil, malicious-repo, policy-bypass — each denied → no side effect | AgentDojo/InjecAgent full corpus | implemented |
| Independent verifier (M4-F) | **merged #384** — `verifier/` reachability + mutation + contract-review | builds on `proof_graph` false-green | 31 tests + false-green challenge set | real coverage/mutant-runner adapter; browser/visual | implemented |
| Experiment kernel real adapters + external portfolio (M6) | — | — | — | ≥3 repos, ≥3 trials, CIs, controls | not started |

## Open-PR reconciliation

| PR | Topic | Verdict | Reason |
|---|---|---|---|
| #374 | harness policy/proof | canonical (merged) | won the policy/proof reconciliation |
| #375 | context/RAG | canonical (merged) | current HEAD |
| #376 | alt policy/proof (ours) | closed | superseded by #374 |
| #378 | golden-path + release | review, don't duplicate | in flight (Codex) — Milestones 5/6 |
| #339 | loop/swarm change-probe | close as superseded (subset cherry-pick optional) | loop gate already on main; swarm port + permissions hint may still be unique |
| #350 | continuity eval | revise-or-supersede | overlaps merged #351 A/B harness — isolate the continuity-specific delta |
| #245 | UI dashboard | defer (P1) | conflicting, 19d stale, not P0 |

## Coordination note

A parallel autonomous agent (Codex) is executing the same blueprint on this repo
(#374, #375 merged the same day; #378 open). To honor truth rules #12/#14 and
"no two PRs invent competing contracts," this effort scopes to **new/additive
surfaces Codex is not on** (`experiment/`, `learning/`, additive `trace/`
files) and freezes shared contracts (#379) rather than re-implementing merged
P0 work.

## Reproduce

```bash
uv sync
uv run onmc retrieval-eval --split code --json   # re-measure the baseline
uv run pytest tests/test_experiment_contracts.py -q
```
