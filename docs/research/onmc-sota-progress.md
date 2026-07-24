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
| Shared experiment contracts | **PR #379** (this effort) | — | 13 unit tests | consumed by kernel/envelope/learning | implemented |
| Experiment kernel (M1) | **PR #381** (stacks #379) | — | 17 unit tests | real-adapter trials; external portfolio | implemented |
| Complete run envelope (M1) | **PR #382** (stacks #379) | reuses `trace/`+`tool_broker.redaction`+`harness_run.receipt` | 8 unit tests (+46 trace unaffected) | live-run capture at scale | implemented |
| Eval-gated repository learning (M3) | **PR #383** (stacks #379) | — | 15 unit + challenge sets | wired through memory/loop; held-out promotion | implemented |

**Integration cross-check (coordinator, independent — not worker self-report):**
locally stacking #379+#381+#382+#383 merges **conflict-free** (disjoint files by
design); combined `ruff` + `mypy --strict` (14 files) clean and **53/53** focused
tests pass together. Merge order must be **#379 first**, then #381/#382/#383. All
draft, awaiting review + full `quality` CI before any merge (rule 3: green tests
= implementation-green, not validated; rule 14: no merge without resolved review).
| Enforced capability + independent verifier (M4) | advisory only | — | — | broker/proxy enforcement; injection suite | not started |
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
