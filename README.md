# oh-no-my-claudecode (`onmc`)

[![CI](https://github.com/adaline-ankit/oh-no-my-claudecode/actions/workflows/ci.yml/badge.svg)](https://github.com/adaline-ankit/oh-no-my-claudecode/actions)
[![Latest release](https://img.shields.io/github/v/release/adaline-ankit/oh-no-my-claudecode)](https://github.com/adaline-ankit/oh-no-my-claudecode/releases/latest)
[![PyPI version](https://badge.fury.io/py/oh-no-my-claudecode.svg)](https://pypi.org/project/oh-no-my-claudecode/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Autonomous coding loops that remember what your repo learned and prove when work is done.**

ONMC runs Claude Code, Codex, or OpenCode against a goal, injects relevant repository memory on every
iteration, warns about known dead-ends, executes your real verifier, enforces time/cost/token
limits, and writes a tamper-evident run receipt.

Use the execution loop, the memory layer, or both. ONMC is local-first, cross-agent, and works
without a hosted account.

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

Coding agents are capable. Their surrounding workflow still has four expensive gaps:

| Gap | ONMC answer |
|---|---|
| Every session starts cold | Repo memory compiled from git, docs, code, PRs, and transcripts |
| Autonomous loops repeat failed ideas | `guard` injects recorded dead-ends before each attempt |
| "Done" can mean the model stopped talking | `loop` and `autopilot` require convergence plus your verifier to mark a run verified |
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
hooks/MCP configuration, shows the first useful recall, and offers the local dashboard.

No provider required. Use `onmc setup --no-llm` for a fully deterministic first run.

### 2. Ask what the repo already knows

```bash
onmc brief --task "fix checkout coupon failures"
onmc guard --task "fix checkout coupon failures"
onmc why src/checkout/service.py
onmc ui
```

### 3. Run the full loop

The simplest way — one command runs the complete KNOW→PLAN(opt)→ACT→PROVE→LEARN cycle:

```bash
onmc autopilot "fix checkout coupon failures" \
  --verify "pytest -q" \
  --max-cost-usd 2.00
```

This compiles the brief, injects dead-ends, runs Claude Code in a loop, verifies success,
records a receipt, and captures what the repo learned.

Prefer `--plan-with` + `--execute-with` to split cost: expensive model plans once,
cheap model executes:

```bash
onmc autopilot "fix the cache invalidation bug" \
  --plan-with claude-opus-4-5 \
  --execute-with claude-haiku-4-5 \
  --verify "pytest -q" \
  --max-cost-usd 2.00
```

Or use the lower-level `onmc loop` for more control:

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

### 4. Gate a PR with No-Mistakes mode

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

## What ships in v0.48

| Capability | Command | What it gives you |
|---|---|---|
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
onmc eval ab            # live: runs the agent in both conditions
onmc eval ab --fixture  # deterministic replay for CI
```

**Honest results so far (live, n small):**

| Regime | Task type | Claude Code alone | + ONMC | Delta |
|---|---|:--:|:--:|:--:|
| Easy bug-fix (cold repo) | localized fix, failing test | 3/3 solved | 3/3 solved | **parity** (+12% tool-calls) |
| Convention memory (ONMC's designed sweet-spot) | add a fn respecting a repo `__all__` contract | 2/2 compliant | 2/2 compliant | **parity** |

**We do not yet have a measured per-task win over Claude Code alone**, and we publish that plainly.
On these tasks a capable model infers code-visible conventions and locates code itself, so ONMC's
context/memory is redundant. ONMC's value must be *earned* on the regimes where the model can't
shortcut: conventions **not visible in code** (tribal/external knowledge), **large unfamiliar repos**
where finding code is the bottleneck, and **expensive multi-iteration dead-ends**. Those are the next
benchmark. The eval harness is shipped so the claim is always backed by reproducible numbers — never
asserted. (An earlier internal eval used a rigged baseline that auto-failed the cold condition; the
A/B harness uses a real cold baseline instead.)

## Local-first and safety boundaries

- Core memory, brief, guard, audit, eval, replay, benchmark, and sync paths work without an LLM.
- Optional providers are used only after explicit configuration; secrets stay in environment variables.
- Dashboard binds to `127.0.0.1` by default and makes no external asset requests.
- `.onmc/` remains local. Review `.agent-memory/` before committing because memories and receipts may
  contain repository details.
- Autonomous loops edit real files. Use a branch/worktree, a narrow verifier, and explicit budgets.
- MCP policy classification helps enforce a pipeline policy but is not a process sandbox.

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

## Contributing

Issues and pull requests welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), then look for
[`good first issue`](https://github.com/adaline-ankit/oh-no-my-claudecode/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).

## License

MIT. See [LICENSE](LICENSE).
