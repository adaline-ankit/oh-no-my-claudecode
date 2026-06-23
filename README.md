# oh-no-my-claudecode (`onmc`)

[![CI](https://github.com/adaline-ankit/oh-no-my-claudecode/actions/workflows/ci.yml/badge.svg)](https://github.com/adaline-ankit/oh-no-my-claudecode/actions)
[![Latest release](https://img.shields.io/github/v/release/adaline-ankit/oh-no-my-claudecode)](https://github.com/adaline-ankit/oh-no-my-claudecode/releases/latest)
[![PyPI version](https://badge.fury.io/py/oh-no-my-claudecode.svg)](https://pypi.org/project/oh-no-my-claudecode/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Autonomous coding loops that remember what your repo learned and prove when work is done.**

ONMC runs Claude Code or Codex against a goal, injects relevant repository memory on every
iteration, warns about known dead-ends, executes your real verifier, enforces time/cost/token
limits, and writes a tamper-evident run receipt.

Use the execution loop, the memory layer, or both. ONMC is local-first, cross-agent, and works
without a hosted account.

```bash
pip install oh-no-my-claudecode
cd your-repo
onmc setup
```

## Why ONMC

Coding agents are capable. Their surrounding workflow still has four expensive gaps:

| Gap | ONMC answer |
|---|---|
| Every session starts cold | Repo memory compiled from git, docs, code, PRs, and transcripts |
| Autonomous loops repeat failed ideas | `guard` injects recorded dead-ends before each attempt |
| "Done" can mean the model stopped talking | `loop` requires convergence plus your verifier to mark a run verified |
| Agent work is hard to inspect or reproduce | Trace, eval, replay, benchmark, and hash-chained run receipts |

ONMC does not replace Claude Code or Codex. It gives them durable repository knowledge,
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

### 3. Preview an autonomous run

```bash
onmc loop \
  --goal "fix checkout coupon failures" \
  --agent claude \
  --verify "pytest -q" \
  --dry-run
```

Remove `--dry-run` when the plan looks right. Work on a branch: a real loop invokes the selected
agent and can edit the repository.

```bash
onmc loop \
  --goal "fix checkout coupon failures" \
  --agent claude \
  --verify "pytest -q" \
  --max-iterations 6 \
  --max-cost-usd 2.00 \
  --max-wall-seconds 900
```

Use `--agent codex` to run `codex exec` instead. Claude Code or Codex must already be installed and
authenticated. Missing binaries fail cleanly.

## What happens inside a loop

```text
goal
  -> compile repo brief + relevant memories
  -> inject known failed approaches
  -> run Claude Code or Codex
  -> run your verifier
  -> record prediction, outcome, files, tokens/cost when available
  -> learn win or failed approach
  -> continue, converge, or stop at a hard limit
  -> write receipt under .agent-memory/receipts/
```

A run is `verified` only when the loop converged **and** the final verifier exited successfully.
Model claims alone never produce verified status.

Receipts bind the goal, agent, model, verifier result, git tree, diff, loop spec, output digest,
limits, and iteration chain with SHA-256. Receipts are tamper-evident, not cryptographically signed.

## What ships in v0.36

| Capability | Command | What it gives you |
|---|---|---|
| Accountable autonomous loop | `onmc loop` | Real Claude/Codex execution, dead-end avoidance, verifier gates, hard limits |
| Portable repo brain | `onmc sync --commit` | Human-readable `.agent-memory/` JSON that travels through git |
| Failure recall | `onmc recall`, `onmc guard` | Past incidents, fixes, and approaches not to repeat |
| Task context | `onmc brief`, `onmc codegraph` | Compact, task-specific context instead of broad file dumping |
| Run proof | loop receipts | Hash-chained evidence with verifier and repository state |
| Replay Lab | `onmc replay run ... --compare` | Re-run memory decisions over a recorded trace, offline |
| Memory evals | `onmc eval run`, `onmc eval compare` | CI-gate recall quality and measure memory contribution |
| Trace Observatory | `onmc trace` | Session events, memory hit rate, loop signals, estimated token ROI |
| Agent config audit | `onmc audit` | CI-gateable scan for permissions, secrets, hooks, MCP, prompt-injection risks |
| MCP trust policy | `onmc mcp` | Classify recorded/stdin MCP calls as allow, block, or approval required |
| GitHub workflow pack | `onmc gh-aw init` | Issue context, PR preflight, merged-PR learning, weekly memory audit |
| Visual inspection | `onmc ui`, `onmc tui`, `onmc wiki` | Local dashboard, terminal browser, and Obsidian knowledge graph |
| Cross-agent integration | `onmc plug` | Claude Code, Codex, Cursor, OMC, and OMX adapters |

### Release progression

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
| Execute | `loop`, `solve`, `review`, `teach` |
| Verify | `check`, `guard`, `recall`, `audit`, `eval`, `replay`, `benchmark` |
| Observe | `trace`, `savings`, `report`, `hud`, `statusline` |
| Integrate | `plug`, `hooks`, `serve --mcp`, `gh-aw`, `mcp` |
| Share | `wiki --format obsidian`, `ui --export`, `.agent-memory/` |

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
