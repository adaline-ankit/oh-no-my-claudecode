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

## Wave 3 — non-paid infrastructure complete (2026-07-24, main `508a129`)

All buildable (non-paid) blueprint infrastructure is now on `main`, additive and
green:

| PR | Capability | Evidence |
|---|---|---|
| #387/#388 | M4 monitor + verifier **wired into `onmc run`** (advisory default; enforced-DENY blocks; verifier false-green downgrade) | 5 wiring tests; 44 harness tests unchanged |
| #389 | enforced-**viable** monitor policy (`_monitor_policy`: repo-scoped fs + verifier cmd allowed) + headless-writable claude adapter | enables real enforced mode |
| #390 | M3 **live** — opt-in gated memory ingestion through the promotion gate (no active memory without a promotion record) | 10 tests |
| #391 | M4-F **adapters** — coverage → reachability + subprocess mutant-runner (plug into the `verifier_false_green_check` seam) | 15 tests |
| #392 | M6 **harness** — external-portfolio runner + audited corpus schema, fixture-tested, **zero paid calls** (`CliAgentAdapter` raises `CredentialsRequiredError`) | 17 tests |

Fresh-`main` re-verify: ruff + `mypy --strict` clean (18 files), **153 mission
tests pass**. No benchmark regression (retrieval baseline unchanged).

## M6 handoff — the one boundary autonomy cannot cross

M6 external proof is **built and ready to run** but deliberately **not executed
autonomously**, for two hard reasons:

1. **Cost** — a real portfolio (≥3 repos × ≥3 trials × 3 conditions ≈ 270 live
   agent runs ≈ **~$100+**) exceeds the blueprint's ">$10 → estimate + approve"
   rule.
2. **Credentials** — real runs need agent CLIs + API keys, which are never
   entered autonomously.

To run it: populate a **VALID-audited** corpus (real external-repo tasks with
leakage metadata), implement `CliAgentAdapter` against the agent CLIs with
credentials present, and invoke `PortfolioRunner`. Results are labeled `external`
**only** when `audit_status == VALID` and `trials > 1`; otherwise they stay
`internal`. Until then every claim in this doc is `implemented` / `internal` —
**no "SOTA" or "improves Claude Code" claim is made.**


## Real-agent A/B pilot — measured null-to-negative result (2026-07-24)

Two bounded live pilots using the repo's own `run_ab` (real `claude`, sonnet,
$1.00/run cap, objective HIDDEN gate written only after the agent finishes;
permission flag narrowed to `--permission-mode acceptEdits`):

| Run | cc_alone (bare Claude) | cc_onmc (ONMC memory) | delta |
|---|---|---|---|
| N=3 x1 trial | **1/3** | 0/3 | **-1** |
| N=6 x1 trial | **2/6** | 1/6 | **-1** |
| pooled | **3/9** | 1/9 | **-2** |

**Verdict: no measured benefit from ONMC memory context on these tasks.** At
N=6 single-trial the difference is inside binomial noise, so the honest reading
is *null-to-negative*, not "ONMC is worse". **No SOTA claim is made or implied.**

Treatment was verified applied (cc_onmc prompt 1084 chars incl. the convention
answer vs 158 chars bare; compiled context 915 chars via the production recall
compiler). Budget was not binding (runs used $0.29-0.48 of a $1.00 cap).

**Robust secondary signal (9/9 runs):** cc_onmc consistently cost ~20% less
($0.29-0.36 vs $0.32-0.43). Hypothesis to test: the injected prior lesson makes
the agent terminate earlier -- cheaper, less exploration, not more correct.

**Instrument failures found and fixed en route** (each invalidated an earlier
run; reported rather than banked): (1) a $0.25/run cap killed 7/8 agents
mid-work; (2) the gate's `python -m pytest` was unresolvable in the venv; (3) a
hand-rolled driver skipped the hidden-gate-test step. Only results after all
three fixes are reported above.

**What a real claim needs:** >=10 tasks x 3 trials x 2-3 conditions with
bootstrap CIs and per-task pairing (~$21+ at observed per-run cost) -- above the
blueprint's $10 auto-spend ceiling, so it requires explicit budget approval.


## Full A/B benchmark with CIs — SIGNIFICANT win, internal evidence (2026-07-24)

90 live runs: **15 frozen private-knowledge tasks x 2 conditions x 3 trials**,
seeded-randomized execution order, real `claude` (sonnet), objective HIDDEN gate
written only after the agent finishes, real bare-agent control, 0 exclusions.
Statistics computed with ONMC's own `experiment.stats` (bootstrap CI + paired
deltas). Total cost **$32.38**.

| Condition | pass@1 | 95% CI (bootstrap) | mean cost/run |
|---|---|---|---|
| `cc_alone` (bare Claude Code) | **9/45 = 0.200** | [0.089, 0.311] | $0.4138 |
| `cc_onmc` (ONMC memory context) | **21/45 = 0.467** | [0.311, 0.622] | $0.3056 |

**Paired per-task delta: +0.267, 95% CI [+0.022, +0.489] — the CI excludes zero,
so the effect is statistically significant.** ONMC also reduced cost ~26%.
Per-task consistency: **8 improved, 5 unchanged, 2 regressed** (not an outlier
artifact).

### Honest scope of this claim

* Evidence level: **`internal`, statistically significant** — NOT `external` and
  NOT `reproducible` per the blueprint protocol.
* The corpus is **authored in-repo** and is *designed* to require private
  repository conventions an agent cannot know a priori. It is a fair test of the
  **memory-transfer** claim, but it is favorable by construction and is **not** a
  general coding-ability benchmark. It does **not** establish "ONMC improves
  Claude Code" in general.
* Reaching `external` still requires >=3 real outside repositories with a
  VALID-audited corpus (the `PortfolioRunner` from #392 is built for exactly
  this).
* The lower CI bound (+0.022) is close to zero, so the effect *size* remains
  uncertain (somewhere between ~+2pp and ~+49pp) even though its *direction* is
  significant.

### Correction to the earlier pilot

The earlier N=3/N=6 single-trial pilots reported 3/9 vs 1/9 (null-to-negative)
and the prediction was "no accuracy win". That was **underpowered and wrong** —
at 3 trials with paired analysis the direction reverses and becomes significant.
Recorded as a correction rather than quietly replaced.

## FIRST EXTERNAL EVALUATION — vertical path proven, accuracy benefit NOT measurable (2026-07-25)

Main `b7bf16f`. **18 live cells: 3 real external repositories x 2 conditions x 3
trials**, seeded single-function regressions adjudicated by each repository's OWN
upstream test suite, real bare-agent control, fresh clone per cell, randomized
order, pinned non-editable ONMC snapshot (`code_sha_under_test`
`b7bf16f147becc22faf127b599921f4827570863`). Total spend **$9.657** of a $10
ceiling. **0 infra failures, 0 budget-stopped cells, 0 exclusions.**
Raw artifact: `datasets/experiment/reports/external_v1_2026-07-25.json`.

| Condition | pass@1 | 95% CI | pass^k | mean cost/run | mean latency |
|---|---|---|---|---|---|
| `bare-agent` (bare Claude Code) | **9/9 = 1.000** | [1.00, 1.00] | 1.000 | **$0.498** | **53.3 s** |
| `onmc-current` (full `onmc run`) | **9/9 = 1.000** | [1.00, 1.00] | 1.000 | $0.630 | 70.1 s |

**Paired per-task delta: 0.000, 95% CI [0.000, 0.000] — not significant.**

### Honest verdict

**This is a null result on accuracy and a negative result on cost.** Both arms
solved every task on every trial, so the corpus has a **ceiling effect** and
cannot discriminate between the conditions at all — the delta is exactly zero by
construction, not because the two are known to be equal. On these tasks ONMC cost
**+26.6%** ($0.630 vs $0.498) and took **+31.6%** longer (70.1 s vs 53.3 s) for
identical repository outcomes. Per truth rule 19 the negative result is recorded
and the **stronger baseline is retained**: nothing here justifies defaulting a
user into ONMC for single-function bugfixes.

**No SOTA claim. No "improves Claude Code" claim.** The earlier internal 90-run
memory-transfer win (+0.267, CI [+0.022, +0.489]) is *not* replicated here and
must not be reported as if it were — that corpus tests private-convention recall,
which these tasks do not require at all.

### What this DOES establish (evidence level: `external`)

The P0 vertical path executes end-to-end on repositories ONMC has never seen: 9/9
ONMC cells ran the complete DAG
(understand -> retrieve -> plan -> claim -> execute -> verify -> repair -> prove -> learn -> completed),
each converging in **1 iteration** with `verified=True` read back from the
persisted receipt, adjudicated by upstream tests rather than agent prose.
**0 false greens** (a pass that edited a test file is scored a failure; none
occurred). This is the first `external`-level evidence that the runtime works
outside our own fixtures.

### Four instrument bugs found and fixed BEFORE any number was banked

Every one would have produced a confidently wrong benchmark. Each was found by
reading why a cell lost, not by a unit test:

1. **The verifier could not run.** `verifier_argv` starts with a bare `python`,
   which resolved to ONMC's own uv venv — an interpreter that cannot import the
   target repo's test deps. On `tenacity` the agent produced the exactly-correct
   one-line fix and the cell was still recorded a loss
   (`stop_reason=verifier-unavailable`). Fixed with a per-cell venv bound through
   PATH (`6d74b8d`).
2. **A broken verifier was indistinguishable from a broken build.** The only gate
   asserted the verifier FAILS after the regression — which a never-runnable
   verifier also satisfies. Added a pristine-passes gate; that is what surfaced
   (1) (`6622879`).
3. **`attrs` was adjudicated by the wrong suite** (`test_make.py` while its
   regression was in `_funcs.py`), so the seeded break never touched the
   adjudicating tests (`6622879`).
4. **The monitor was silently zeroing the treatment arm.** With the verifier
   outside the checkout, `onmc run` printed
   `Policy: agent:claude=allow, verifier=deny` and aborted before executing while
   the bare arm ran unimpeded. The monitor was RIGHT — it allowlists verifier
   commands by argv prefix. Fixed in the harness, **not** by weakening policy;
   loosening it would have benchmarked a product ONMC does not ship (`6d74b8d`).

A fifth validity problem was caught mid-flight: the portfolio's ONMC venv was an
*editable* install, so source edits made during a run changed the code under later
cells. The first pass was **discarded ($0.55)** and re-run against a pinned
non-editable snapshot.

### Product gaps this evaluation exposed and fixed

* **`onmc explain` could not see a real `onmc run`.** The `HarnessRunReceipt` was
  built, returned in memory and dropped, while `explain` reads
  `.agent-memory/receipts/run-*.json`. After a completed external run it still
  said "No run receipts yet". Now persisted (`deea22b`).
* **Run cost was invisible.** `onmc run` reported no spend, tokens or turns in
  `--json` or rendered output. Now reported, as `int | None` / `float | None` so
  "unknown" is never rendered as `$0.00` (`b7bf16f`).
* **A committed fix was scored a vacuous pass.** The change probe used
  `git status --porcelain` only, so an agent that edited AND committed left an
  identical signature; it now folds in the HEAD sha (`3975830`).

### Known limits of this run

* **3 tasks, one task class.** All three are single-function bugfix reverts. The
  blueprint's other classes (cross-file feature, refactor, ambiguity,
  retrieval-abstention, misleading context, long-running) are **not** covered.
  20-50 audited tasks remain the target; this is 3.
* **Ceiling effect** means this design cannot detect a benefit even if one exists.
  The next corpus must be hard enough that bare Claude Code fails a meaningful
  fraction of cells.
* **Not turn-matched by design:** ONMC is a loop (`--max-iterations 4`) versus one
  bare shot. All 9 ONMC cells converged in 1 iteration so the allowance was never
  used, but the arms are not turn-equalised.
* **`bare-agent` cost is missing for 1 of 9 cells** (8/9 reported); ONMC cost for
  all 9 was recovered from the persisted receipts after the live stdout capture
  truncated the field.
* ONMC's observed diff is 4 lines vs the bare arm's 2, because `onmc init` appends
  `.onmc/` to `.gitignore`. Benign bookkeeping, not a scope violation, but the
  arms' diffs are not byte-comparable.

## SECOND external run: 24 tasks / 6 repos — THIRD ceiling effect, claim abandoned (2026-07-25)

Snapshot under test `3b58232` (non-editable install, pinned at run start). **48 live
cells: 24 audited tasks x 6 pinned upstream repositories x 2 conditions x 1 trial.**
Total spend **$29.37**. **0 infra failures, 0 budget-stopped cells, 0 false greens,
0 exclusions at run time** (5 candidate tasks had already been rejected by the
vacuity gate before spending — recorded in the manifest's `excluded_tasks`).
Raw artifact: `datasets/experiment/reports/external_v3_stage1_2026-07-25.json`.

| Condition | pass@1 | 95% CI | pass^k | mean cost/run | mean latency |
|---|---|---|---|---|---|
| `bare-agent` | 24/24 = **1.000** | [1.00, 1.00] | 1.000 | **$0.6352** | 106.3 s |
| `onmc-current` | 24/24 = **1.000** | [1.00, 1.00] | 1.000 | $0.8796 | **102.7 s** |

**Paired per-task delta: 0.000, 95% CI [0.000, 0.000] — not significant.**
Failure taxonomy: empty in both arms (nothing failed). ONMC was ~3% faster here but
cost **+38%**.

### Verdict: the SOTA claim is abandoned, not deferred

Three independent corpora have now saturated both arms:

| Corpus | Tasks | Repos | bare | ONMC | paired delta |
|---|---|---|---|---|---|
| external v1 (single-hunk reverts) | 3 | 3 | 9/9 | 9/9 | 0.000 [0.000, 0.000] |
| external v2 (multi-site reverts) | +3 | 3 | — | — | folded into v3 |
| external v3 (AST body removal, multi-site) | 24 | 6 | 24/24 | 24/24 | 0.000 [0.000, 0.000] |

The corpus was made progressively harder on purpose — single-site revert, then
multi-site revert, then whole-function removal requiring reimplementation, several
requiring two or three related functions to be found. **Bare Claude Code solved
every single one.** This is not evidence that ONMC and bare Claude Code are equal;
it is evidence that mechanically-seeded defects in small pure-Python libraries
cannot discriminate between them at all.

**Stages 2 and 3 (adding trials 2-3 and the ablation arms, ~$200 of an approved
~$320 budget) were NOT run.** Buying a third trial on a corpus measured at
100%/100% purchases a more precise zero. Recorded as a deliberate decision, not an
omission (rule 19: keep the stronger baseline; rule 20: remove scaffolding that no
longer adds measured value).

### Why a public-repo corpus structurally cannot prove ONMC's claim

ONMC's claim is not "better at coding" — it is *"better on a specific
repository"*, via retrieved repo context and promoted repo memory. That advantage
can only show up where the required knowledge is **not discoverable from the
repository itself**. But any convention discoverable inside a public repo is
equally discoverable by the bare agent reading the same repo. So on public
upstream corpora the treatment has nothing to add, and the only way to manufacture
a win is to *inject* private knowledge — which is precisely the
"favorable-by-construction" caveat already attached to the internal 90-run result.

The honest consequence: **an `external` memory-transfer claim requires genuinely
private repositories**, where the conventions are real institutional knowledge
rather than planted. That is the one remaining design that could reach a
defensible claim, and it needs repositories this agent does not have.

### Retrieval ablation (offline, free, frozen split `dataset_sha 8e8f6d52…`, 40 cases)

| Surface | R@5 | R@10 | MRR@10 | nDCG@10 | p50 latency | ctx tokens |
|---|---|---|---|---|---|---|
| **code-bm25** (default) | **0.950** | **1.000** | **0.8101** | **0.8574** | **0.18 ms** | 3299 |
| code-hybrid (BM25+dense+RRF) | 0.875 | 0.950 | 0.7637 | 0.8082 | 4.60 ms | **2887** |

BM25 wins every quality metric and is **~25x faster**; hybrid wins only on context
tokens. The shipped default is the measured winner, and hybrid's negative result is
retained rather than re-litigated. Memory split: `recall` MRR@10 0.8889, `guard`
R@5 0.7833; `search_memory` and `context_engine` surfaces **skipped — no cases in
the dataset**, so those two ablation cells are unmeasured, not passed.

**Ablations still NOT run:** dense-only and graph-only retrieval (no such
evaluation surface exists — only `code-bm25` and `code-hybrid` are implemented),
retrieval-vs-abstention, memory disabled/candidate/promoted, one-agent vs adaptive
harness, advisory vs enforced, and per-component verifier isolation.

## Reproduce

```bash
uv sync
uv run onmc retrieval-eval --split code --json   # re-measure the baseline
# re-run the external portfolio (paid; ~$10, hard-capped, records all fallbacks)
uv run python scripts/run_external_eval.py \
  --manifest datasets/experiment/portfolio_external_v1.json \
  --workdir /tmp/onmc-external --out /tmp/onmc-external/report.json \
  --trials 3 --max-total-usd 10.0 --max-cost-usd 1.0

uv run pytest tests/test_experiment_contracts.py tests/test_experiment_kernel.py \
  tests/test_experiment_portfolio.py tests/test_learning_gate.py \
  tests/test_learning_ingest.py tests/test_enforcement_monitor.py \
  tests/test_verifier_adapters.py tests/test_run_m4_wiring.py -q
```
