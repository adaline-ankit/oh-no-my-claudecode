# oh-no-my-claudecode (`onmc`)

[![CI](https://github.com/adaline-ankit/oh-no-my-claudecode/actions/workflows/ci.yml/badge.svg)](https://github.com/adaline-ankit/oh-no-my-claudecode/actions)
[![Latest release](https://img.shields.io/github/v/release/adaline-ankit/oh-no-my-claudecode)](https://github.com/adaline-ankit/oh-no-my-claudecode/releases/latest)
[![PyPI version](https://badge.fury.io/py/oh-no-my-claudecode.svg)](https://pypi.org/project/oh-no-my-claudecode/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**The coding harness that measures itself — and tells you when it loses.**

Every Claude Code wrapper claims it makes the agent better. Almost none publish a
number. ONMC is built the other way round: it runs Claude Code, Codex, or
OpenCode against a goal, then **refuses to call the work done** until an
independent verifier says so — and ships the benchmark harness that can prove, or
disprove, its own value on your repository.

What it actually does on every run:

- **Blocks false "done."** An independent verifier checks the repository state, not
  the agent's prose. Deleted tests, weakened assertions, unreached changes, and
  vacuous passes are rejected.
- **Mediates side effects.** A reference monitor composes capability policy over
  filesystem, command, network, and secret access. A denied effect leaves no trace.
- **Survives interruption.** Hash-chained durable events, checkpoints, idempotent
  side effects, and resume — a crash does not repeat completed work.
- **Writes a receipt.** Tamper-evident, canonical, verifiable offline. `verified`
  is computed from evidence, not asserted by a model.
- **Gates what it learns.** No repository memory becomes active without held-out
  evidence, provenance, scope, and a rollback path.
- **Measures itself.** Experiment kernel with paired deltas and bootstrap
  confidence intervals, plus Harbor integration for agent-neutral trials.

One command is the product: `onmc run`. Local-first, cross-agent, no hosted
account.

## Evidence status — read this before believing anything

**ONMC does not claim state-of-the-art performance, and does not claim to beat a
bare agent.** Current honest status:

| Claim | Status |
|---|---|
| Beats bare Claude Code on external tasks | **Not shown.** The one external run was a **tie** (6/9 vs 6/9) at ~26% higher latency. |
| Retrieval: hybrid/embeddings beat BM25 on code | **Disproven on our data.** BM25 R@5 **0.950** / nDCG **0.857** vs hybrid 0.875 / 0.808. BM25 stays the default. |
| Retrieval: hybrid helps on *memory* (prose) | **Measured +18% nDCG** — which is why memory, not code search, is where retrieval work continues. |
| Never reports a false green | Held across every real-agent run so far, including runs where the fix was correct and ONMC still refused to claim verified. |
| Publication-grade benchmark | **Blocked.** Task corpus saturates (a prior run scored 24/24 in *both* arms), cost coverage is incomplete, and raw artifacts are missing. |

The [external benchmark report](docs/evidence/sota-report.md) is deliberately not
publication-ready, the [reproduction guide](docs/evidence/reproduce.md)
regenerates that verdict locally, and a claim gate in CI **rejects stronger
language** until every pre-registered gate passes. If you catch this README
overclaiming, that is a bug — please file it.

Why say all that out loud? Because the measurement machinery is the point. A
harness that cannot show its own null results cannot be trusted with yours.

## Install (one line)

```bash
curl -fsSL https://raw.githubusercontent.com/adaline-ankit/oh-no-my-claudecode/main/install.sh | bash
```

The installer detects `uv` → `pipx` → `pip`, installs `oh-no-my-claudecode`, then runs
`onmc setup` to wire up hooks and MCP integration. Safe to re-run (idempotent). Never uses `sudo`.

### Alternative: manual install

```bash
# uv (recommended — isolated, fast)
uv tool install oh-no-my-claudecode
cd your-repo && onmc setup

# pipx
pipx install oh-no-my-claudecode
cd your-repo && onmc setup

# pip
pip install oh-no-my-claudecode
cd your-repo && onmc setup
```

## Why ONMC

Coding agents are capable. Their surrounding workflow still has expensive gaps:

| Gap | ONMC answer |
|---|---|
| Every session starts cold | Repo memory compiled from git, docs, code, PRs, and transcripts |
| Autonomous loops repeat failed ideas | `guard` injects recorded dead-ends before each attempt |
| "Done" can mean the model stopped talking | `run` requires convergence plus your verifier and proof receipt to mark a run verified |
| Agent work is hard to inspect or reproduce | Tamper-evident receipts with git tree hash, model/tool hashes, iteration chain, and reproducibility envelope |
| No proof of agent improvement over time | `evolution` compares cost and iterations across runs; receipt-backed trend showing cheaper and faster loops |
| Expensive models do all the work | Cost-split execution: `--plan-with <expensive> --execute-with <cheap>` runs precise planning once, cheap execution per iteration |
| PRs need a hard "do not merge unless proven" gate | `nomistakes` runs audit/eval/autopilot and approves only with a verified receipt |

ONMC does not replace Claude Code, Codex, or OpenCode. It gives them durable repository knowledge,
bounded execution, and evidence.

## Five-minute first win

### 1. Build the repo brain

```bash
onmc setup
```

Setup scans the repository, builds structured memory, generates agent context, installs supported
hooks/MCP configuration, shows the first useful recall, and ends with a capability
checklist plus the canonical next command. Confirm readiness any time with:

```bash
onmc status
```

No provider required. Use `onmc setup --no-llm` for a fully deterministic first run.

### 2. Run one task

Preview the exact runtime contract without spending tokens or changing files:

```bash
onmc run "fix checkout coupon failures"
```

The plan compiles a typed task DAG, retrieves minimal cited repo context, checks
agent and verifier capabilities, declares proof requirements, and assigns durable
state. Execute that exact runtime explicitly:

```bash
onmc run "fix checkout coupon failures" --execute \
  --agent codex \
  --verifier "pytest -q tests/checkout" \
  --max-cost-usd 2.00 \
  --isolate
```

### 3. Watch the same run

`mission` is the detailed plan view; Mission Control replays the durable event
stream and accepts “verified” only from a valid proof receipt:

```bash
onmc mission "fix checkout coupon failures"
onmc missioncontrol
onmc ui
```

The equivalent Claude Code hook and Codex entry paths compile the same `RunSpec`;
they do not start separate orchestration systems.

### 4. Inspect memory when you need it

```bash
onmc brief --task "fix checkout coupon failures"
onmc guard --task "fix checkout coupon failures"
onmc why src/checkout/service.py
```

Advanced presets such as `autopilot`, `nomistakes`, `loop`, and `swarm` remain
callable and are listed by `onmc commands --all`. They are specialized controls
over the same proof and receipt boundaries, not the default onboarding path.

For example, the lower-level loop remains available when its extra controls are
needed:

```bash
onmc loop \
  --goal "fix checkout coupon failures" \
  --agent claude \
  --verify "pytest -q" \
  --max-iterations 6 \
  --max-cost-usd 2.00 \
  --max-wall-seconds 900
```

Use `--agent codex` or `--agent opencode` to swap agents. Use `--isolate` to run in
an isolated git worktree so failed attempts don't pollute your working tree. Use
`--resume` to pick up from the last checkpoint.

### 5. Gate a PR with No-Mistakes mode

`nomistakes` is the merge gate: it runs deterministic preflight, lets the agent act
inside an isolated worktree, verifies with your command, and approves only when ONMC
writes a verified receipt.

```bash
onmc nomistakes "fix failing checkout CI" \
  --agent claude \
  --verify "pytest -q" \
  --eval-fail-under 80 \
  --max-cost-usd 3.00
```

Autonomy levels are explicit:

- `L0` observe only
- `L1` advise only
- `L2` act, verify, learn, and produce a receipt
- `L3` extended autonomous gate with the same receipt requirement
- `L4` reserved for future human-approved merge automation

## The full cycle: KNOW → (PLAN) → ACT → PROVE → LEARN

`onmc autopilot` orchestrates one command:

```text
KNOW   → compile repo brief + recall guard (dead-ends) + user profile (preferences)
PLAN   → [optional] expensive model produces a precise implementation plan
ACT    → memory-grounded autonomous loop (avoids recorded dead-ends, stops at limits)
PROVE  → receipt + verified/not-verified verdict + cost (receipt is tamper-evident)
LEARN  → capture session memory + skill_promote + consolidate brain
         → "Your brain grew: +N memories · +N skills · N dead-ends known"
```

Loop iteration details:

```text
Each ACT iteration:
  -> inject known failed approaches
  -> run Claude Code, Codex, or OpenCode
  -> run your verifier
  -> record prediction, outcome, files, tokens/cost when available
  -> decide: win, loss, or unknown
  -> continue, converge, or stop at a hard limit
```

A run is **verified** only when the loop converged **and** the final verifier exited successfully.
Model claims alone never produce verified status.

**Receipts** (written to `.agent-memory/receipts/`) bind goal, agent, model, verifier result,
git tree hash, diff SHA, loop spec, output digest, limits, and iteration chain with SHA-256.
Receipts include a reproducibility envelope (model IDs, tool/prompt hashes, runtime) so runs can
be reproduced. They are tamper-evident (not cryptographically signed).

## Current capabilities

| Capability | Command | What it gives you |
|---|---|---|
| Adaptive execution harness | `onmc run "<task>"` | Safe plan-first task DAG, cited repo RAG, policy decisions, durable execution, verifier-backed proof graph, and resume |
| No-Mistakes PR gate | `onmc nomistakes "<goal>"` | Audit + optional eval + isolated autopilot + verifier + receipt verdict; exits nonzero unless approved |
| Full autopilot cycle | `onmc autopilot "<goal>"` | One-verb KNOW→(PLAN)→ACT→PROVE→LEARN; ends with "your brain grew" summary. Use `--plan-with <model> --execute-with <model>` for cost-split |
| Compounding proof | `onmc evolution` | Shows agent getting cheaper/fewer-iterations across runs, receipt-backed trend |
| Accountable autonomous loop | `onmc loop` | Real Claude/Codex/OpenCode execution, dead-end avoidance, verifier gates, hard limits |
| Loop isolation & resume | `onmc loop --isolate --resume` | Run in fresh git worktree; roll back on failure. Resume interrupted runs from last checkpoint |
| Loop templates | `onmc loop --template ci-healer` | Ready-to-run templates: ci-healer, pr-babysitter, issue-to-pr |
| Tamper-evident receipts | loop/autopilot receipts | Git tree/diff SHA, hash chain, reproducibility envelope (model/tool/config hashes) for reproducibility |
| Portable repo brain | `onmc sync --commit` | Human-readable `.agent-memory/` JSON that travels through git |
| Failure recall | `onmc recall`, `onmc guard` | Past incidents, fixes, and approaches not to repeat |
| Task context | `onmc brief`, `onmc codegraph` | Compact, task-specific context instead of broad file dumping |
| Replay Lab | `onmc replay run ... --compare` | Re-run memory decisions over a recorded trace, offline |
| Memory evals | `onmc eval run`, `onmc eval compare` | CI-gate recall quality and measure memory contribution |
| Trace Observatory | `onmc trace` | Session events, memory hit rate, loop signals, estimated token ROI |
| Skill export | `onmc skill export` | Export learned skills as Agent Skills SKILL.md (agentskills.io standard, 16+ tools supported) |
| Agent config audit | `onmc audit` | CI-gateable scan for permissions, secrets, hooks, MCP, prompt-injection risks |
| MCP trust policy | `onmc mcp` | Classify recorded/stdin MCP calls as allow, block, or approval required |
| GitHub workflow pack | `onmc gh-aw init` | Issue context, PR preflight, merged-PR learning, weekly memory audit |
| Visual inspection | `onmc ui`, `onmc tui`, `onmc wiki` | Local dashboard, terminal browser, Mission Control live view, and Obsidian knowledge graph |
| Cross-agent integration | `onmc plug` | Claude Code, Codex, Cursor, OpenCode adapters for headless loop/autopilot |

### Release progression

- **v0.48:** No-Mistakes PR gate and `autopilot --isolate`
- **v0.47:** durable loop checkpoint/resume and ready-to-run loop templates
- **v0.36:** guided setup and first-run dashboard welcome
- **v0.35:** deterministic session replay with memory-vs-cold comparison
- **v0.34:** tamper-evident receipts, cost limits, wall-time limits, proof-based completion
- **v0.33:** MCP trust policy and call classification
- **v0.32:** real headless Claude Code and Codex loop adapters
- **v0.31:** memory-aware GitHub Agentic Workflow scaffolding
- **v0.30:** deterministic memory eval suite and CI regression gates
- **v0.29:** agent-configuration security audit
- **v0.28:** measured repo-brain benchmarks plus labelled deterministic simulation
- **v0.27:** session trace observatory and OpenTelemetry JSON export
- **v0.26:** memory-grounded autonomous loop engine
- **v0.24-v0.25:** knowledge-gap actions, user profile MCP, memory federation, and natural-language MCP queries

See [CHANGELOG.md](CHANGELOG.md) for exact release notes.

## Real workflows

### Never retry yesterday's failed fix

```bash
onmc recall "InvalidSignatureError"
onmc guard --task "repair Firebase JWT middleware"
```

When an attempt fails, ONMC stores the approach and evidence. Future briefs and loop iterations
surface it as a dead-end instead of rediscovering it.

### Prove the brain contributes

```bash
onmc eval create \
  --query "fix cache invalidation" \
  --expect-file src/cache.py \
  --expect-deadend "per-worker cache"

onmc eval compare --baseline 10
onmc eval run --fail-under 80
```

Both commands are deterministic and exit nonzero below the requested threshold, so they can gate CI.

### Replay a recorded session

```bash
onmc trace start --label "checkout repair"
# Work normally with ONMC-enabled agent hooks and commands.
onmc trace stop
onmc trace report

onmc replay run <trace-id> --compare
```

Replay re-runs recall and guard decisions against the current brain. It makes memory changes testable
without calling an LLM.

### Add repo-aware GitHub automation

```bash
onmc gh-aw init --dry-run
onmc gh-aw init
```

This writes four workflows: issue context, PR preflight, merged-PR learning, and weekly memory audit.
Generated workflows use constrained permissions, pinned actions, and comment-only safe outputs.

### Audit agent configuration and MCP calls

```bash
onmc audit . --fail-on high
onmc mcp policy init
onmc mcp check tool-calls.jsonl --fail-on approval_required
```

`onmc audit` is static. `onmc mcp check` classifies JSONL records or stdin against local policy; it
is designed for hooks and CI pipelines, not as a transparent network proxy.

## Works with your coding agent

```bash
onmc plug claude-code
onmc plug codex
onmc plug cursor
onmc plug omc
onmc plug omx
onmc plug all
```

| Agent | Integration |
|---|---|
| Claude Code | Project hooks, `.mcp.json`, `CLAUDE.md`, slash commands, plugin marketplace |
| Codex | `AGENTS.md`, compact briefs, MCP registration, headless loop adapter |
| Cursor | `.cursor/rules/onmc.md` |
| OMC / OMX | Generated adapter guide over ONMC memory commands |
| Cloud agents | Restore committed `.agent-memory/` in ephemeral environments |

Claude Code marketplace install:

```text
/plugin marketplace add adaline-ankit/oh-no-my-claudecode
/plugin install oh-no-my-claudecode@onmc
/reload-plugins
```

Turn ONMC into the active, verifier-gated Claude Code runtime for this
repository:

```bash
onmc wrap --strict --default-active
```

For actionable coding prompts, strict wrapping automatically arms a bounded
completion contract. Claude cannot finish until ONMC observes a real workspace
change and the detected repository verifier passes. Low-risk implementation
questions use a recommended reversible default; material security, production,
payment, deletion, migration, compliance, and credential decisions still
reach the user. The guard returns control after six blocked completion attempts
or 45 minutes, so a broken verifier cannot create an infinite agent loop.

Codex MCP registration:

```bash
codex mcp add onmc -- onmc serve --mcp
```

ONMC exposes 12 MCP tools, including `recall`, `search_memory`, `get_brief`, `guard_task`,
`record_attempt`, `record_memory`, `get_coverage`, `get_digest`, `get_skills`, `get_profile`, and
`ask`.

See [integration guides](docs/integrations/README.md).

## Memory travels with git

```bash
onmc sync --commit
git add .agent-memory/ CLAUDE.md
git commit -m "chore: sync agent memory"
```

Fresh clone:

```bash
onmc init
onmc sync --restore
```

```text
.onmc/            local SQLite, traces, logs, evals; gitignored
.agent-memory/    portable JSON, skills, receipts, latest brief; commit selectively
CLAUDE.md         generated project context; commit if your team uses it
```

The format is documented in [AGENT-MEMORY-SPEC.md](AGENT-MEMORY-SPEC.md). Any tool can implement a
reader or writer. Validate an export with `onmc spec validate`.

## Proof, without hiding methodology

```bash
onmc benchmark
onmc bench
```

`onmc benchmark` labels every result:

- **MEASURED:** recall latency, hits per query, brain composition, terse-vs-verbose reduction,
  TOON-vs-JSON reduction
- **SIM:** repeated-failure, wasted-attempt, and context-token deltas from the deterministic harness

The built-in five-task simulation currently reports repeated-failure rate `100% -> 0%`, nine fewer
wasted attempts, and `-97%` context-token proxy usage. These are synthetic harness results, not a
claim about every production repository. Run `onmc benchmark` against your own brain for measured
repo-specific numbers.

### Outcome A/B: ONMC + Claude Code vs Claude Code alone

The benchmarks above measure ONMC's *internal* primitives (recall, guard, context size). The harder,
more honest question is whether ONMC changes the *outcome* of real coding tasks. `onmc eval ab` runs
that comparison — SWE-bench-style tasks (revert a real bug-fix, keep its test), each solved twice:
once by Claude Code alone, once by Claude Code + ONMC, scored by an objective gate.

```bash
onmc eval ab --public-repo  # live: pinned public repo, identical Claude settings
onmc eval ab --fixture      # deterministic harness regression only; not product evidence
```

**Latest public-repository smoke result (2026-07-18, one paired run):**

| Task | Result | Tokens | Turns | Reported cost | Wall time |
|---|---|---:|---:|---:|---:|
| Claude Code alone | pass | 4,628 | 23 | $0.473 | 111.6s |
| Claude Code + ONMC recall | pass | 2,679 | 13 | $0.233 | 57.5s |
| ONMC reduction | same correct outcome | **42.1%** | **43.5%** | **50.8%** | **48.4%** |

Method: both conditions used Claude Code Sonnet with medium effort, a $1 per-condition cap, fresh
clones of `encode/httpx` at pre-fix commit `df5345140e09ac6c2de0d9589bcd6f3e31c6aa3f`, and the same
task. The harness applied only the upstream regression test from fix `6d852d319acd`; the production
fix was absent. Both agents changed only `httpx/_client.py` (`+10/-0`) and passed the two fail-to-pass
cases plus six stable preservation cases. ONMC's extra context was a repository lesson seeded into
an isolated SQLite brain and retrieved through the production recall compiler.
The harness rejects any condition that modifies the protected upstream regression-test file.

This is an **efficiency win, not a solve-rate claim**. One paired run is a smoke result, not a
statistically stable benchmark. The harness reports correctness, regressions, tokens, turns, cost,
time, diff scope, prompt hash, and pinned-repository provenance so repeated trials can establish or
refute the claim. Fixture results remain labelled and are never counted as live evidence.

## Local-first and safety boundaries

- Core memory, brief, guard, audit, eval, replay, benchmark, and sync paths work without an LLM.
- Optional providers are used only after explicit configuration; secrets stay in environment variables.
- Dashboard binds to `127.0.0.1` by default and makes no external asset requests.
- `.onmc/` remains local. Review `.agent-memory/` before committing because memories and receipts may
  contain repository details.
- Autonomous loops edit real files. Use a branch/worktree, a narrow verifier, and explicit budgets.
- MCP policy classification helps enforce a pipeline policy but is not a process sandbox.
- `ONMC_LEARNING=0` is the kill switch for active learned behavior: no learned candidate
  activates and promotion is suppressed. See
  [environment variables](docs/environment-variables.md) for what it does and does not cover.

## Command map

| Need | Commands |
|---|---|
| Start | `setup`, `doctor`, `status`, `ui`, `tui` |
| Understand | `brief`, `why`, `blame`, `codegraph`, `ask`, `onboard`, `digest` |
| Remember | `ingest`, `mine`, `capture`, `memory`, `consolidate`, `sync`, `pull` |
| Execute | `autopilot`, `loop`, `solve`, `review`, `teach` |
| Verify | `check`, `guard`, `recall`, `audit`, `eval`, `replay`, `benchmark` |
| Measure | `evolution`, `savings` |
| Observe | `trace`, `report`, `hud`, `statusline` |
| Integrate | `plug`, `hooks`, `serve --mcp`, `gh-aw`, `mcp` |
| Share | `wiki --format obsidian`, `ui --export`, `.agent-memory/`, `skill export` |

Full generated options: [docs/cli-reference.md](docs/cli-reference.md).

## Python API

```python
import onmc

repo = onmc.init(".")
repo.ingest()
brief = repo.brief(task="fix checkout coupon failures", style="compact", max_tokens=500)
memories = repo.memory.search(files=["src/checkout/service.py"])
task = repo.task.start(title="Fix checkout coupon failures")
repo.sync.commit()
```

## Documentation

- [Demo: two agents, one brain](docs/demo.md)
- [Shipped capabilities](docs/shipped-capabilities.md)
- [CLI reference](docs/cli-reference.md)
- [Harness command migration](docs/harness-command-migration.md)
- [Environment variables](docs/environment-variables.md)
- [Architecture](docs/architecture.md)
- [Memory model](docs/memory-model.md)
- [Dashboard](docs/ui-dashboard.md)
- [Agent-native workflows](docs/agent-native-workflows.md)
- [Launch kit](docs/launch/README.md)

## Development

```bash
git clone https://github.com/adaline-ankit/oh-no-my-claudecode
cd oh-no-my-claudecode
pip install -e ".[dev]"
ruff check .
mypy src
pytest --cov=oh_no_my_claudecode --cov-report=term-missing
python scripts/generate-cli-reference.py --check
python -m build
python -m twine check dist/*
```

## Where we need help

These are the highest-value open problems, ranked. Each is scoped, measurable, and
has the surrounding machinery already built — you would be filling a specific gap,
not designing from scratch.

**1. Compaction survival (biggest unclaimed gap in the ecosystem)**
When Claude Code compacts context, detail is destroyed — including which approaches
already failed, so the agent retries them. The `PreCompact` hook exists and
`hooks/pre_compact.py` is scaffolded. Build: harvest failed approaches, decisions,
and open threads *before* compaction, then re-inject after it.
*Measure:* repeat-failure rate post-compaction.

**2. Ranked memory injection**
`CLAUDE.md` is static text loaded whole, every session, relevant or not. Replace it
with task-aware retrieval at `SessionStart`: hybrid BM25+dense, top-k, hard token
budget, and **abstention** when confidence is low. Our data says hybrid earns +18%
nDCG on prose — this is where it belongs.
*Measure:* tokens saved and downstream pass rate, via `onmc retrieval-eval`.

**3. Discriminative task corpus (unblocks every benchmark claim)**
Our portfolio saturates — a prior run scored 24/24 in both arms, which carries zero
information. Needed: tasks mined from real git history (`bug-fix commit` + `the test
that proves it` = free, leak-resistant ground truth), plus the missing classes —
deception/false-green, misleading context, retrieval abstention, cross-file
location. Calibration must **reject** any task both arms always pass.

**4. Live permission decisions for unattended runs**
Today `hooks/pre_tool_use.py` is advisory-only and the reference monitor runs
post-hoc. Wire the policy engine into a live `PreToolUse` decision so overnight runs
work **without** `--dangerously-skip-permissions`: allow repo-scoped edits, deny
destructive/network/secret, queue the rest for morning review.

**5. Verifier calibration corpus**
The false-green verifier (mutation, reachability, protected-test integrity,
contract review) has no external calibration set. Needed: real fixes vs deceptive
patches, then published sensitivity/specificity with confidence intervals. This is
also the most publishable result in the repo.

Ground rules that make contributions land: reuse existing contracts instead of
adding parallel ones, add the test with the behavior, and **never widen a claim past
its evidence** — the claim gate will reject it, and so will review.

## Contributing

Issues and pull requests welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), then look for
[`good first issue`](https://github.com/adaline-ankit/oh-no-my-claudecode/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).

## License

MIT. See [LICENSE](LICENSE).
