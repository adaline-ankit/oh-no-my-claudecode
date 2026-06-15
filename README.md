# oh-no-my-claudecode (`onmc`)

[![CI](https://github.com/adaline-ankit/oh-no-my-claudecode/actions/workflows/ci.yml/badge.svg)](https://github.com/adaline-ankit/oh-no-my-claudecode/actions)
[![PyPI version](https://badge.fury.io/py/oh-no-my-claudecode.svg)](https://pypi.org/project/oh-no-my-claudecode/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![AI-Ready](https://img.shields.io/badge/AI--Ready-ONMC-6B7280)](https://github.com/adaline-ankit/oh-no-my-claudecode)

> Repo-native memory for AI coding agents.  
> Your agent knows your codebase history, not just its current state.

---

## Get started

```bash
pip install oh-no-my-claudecode
onmc setup
```

That's it. `onmc setup` reads your git history, extracts architectural decisions and invariants, generates `CLAUDE.md`, and connects to Claude Code — all in one interactive wizard.

---

## What it does

Your coding agent starts every session like it has never seen your codebase before. It doesn't know why the code looks the way it does, what was tried and failed, or which files are dangerous to change. **ONMC fixes that.**

It reads your git history, docs, and code structure with an LLM and builds a structured memory store. That memory travels with the repo. Every agent — Claude Code, Cursor, Codex — gets it.

---

## Install as a Claude Code plugin

ONMC ships a Claude Code plugin manifest. Point Claude Code at this repo and it
registers the MCP server and hooks automatically:

```bash
# 1. Install the package
pip install oh-no-my-claudecode

# 2. Run setup (generates CLAUDE.md, installs hooks, registers MCP)
onmc setup

# 3. Or add to .mcp.json manually (the MCP server entry)
#    command: onmc  args: ["serve", "--mcp"]
```

The plugin manifest lives at [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json).
A single-plugin marketplace entry is at [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json)
for registering this repo as a Claude Code plugin source.

---

## Works with every coding agent

| Agent | Integration |
|---|---|
| **Claude Code** | `CLAUDE.md` + `onmc hooks install` + `onmc serve --mcp` + [plugin manifest](.claude-plugin/plugin.json) |
| **Cursor** | Pipe `onmc brief` output to `.cursorrules` |
| **Codex / other agents** | [`AGENTS.md`](AGENTS.md) — run `onmc brief`, `onmc guard`, `onmc serve --mcp` at session start |
| **Cloud agents** (Codex, GitHub Coding Agent) | `onmc sync --restore` in container startup |
| **Gitpod / Codespaces** | Add `onmc sync --restore` to `.gitpod.yml` |

MCP tools exposed by `onmc serve --mcp`: **`search_memory`**, **`guard_task`**, **`get_brief`**.

See [Agent-Native Workflows](docs/agent-native-workflows.md) for the supported
Claude Code, Codex, MCP, and cloud-agent boundaries.

---

## Commands

For full generated help output, see [CLI Reference](docs/cli-reference.md).

### Setup and health

```bash
onmc setup              # full onboarding wizard — run this first
onmc doctor             # health check: memory freshness, hooks, MCP, CLAUDE.md
onmc report             # markdown agent-readiness report for PRs and handoffs
onmc status             # repo root, ingest state, memory counts
```

### Memory extraction

```bash
onmc ingest             # scan git history, docs, source — extract structured memory
onmc ingest --files x   # re-ingest specific files
onmc ingest --install-hook  # auto-ingest on every commit
onmc mine               # extract memory from Claude Code session transcripts
onmc mine --github      # extract decisions and gotchas from GitHub PRs
```

### Memory management

```bash
onmc memory list                    # browse all memory
onmc memory list --kind hotspot     # filter by kind
onmc memory list --type did_not_work
onmc memory show <id>               # full record with provenance
onmc memory confirm <id>            # mark as verified useful
onmc memory reject <id>             # mark as wrong or stale
onmc memory edit <id>               # update the summary
onmc memory add <task_id> --type fix --title "..." --summary "..."
```

### CLAUDE.md

```bash
onmc claude-md generate  # generate CLAUDE.md from memory store
onmc claude-md update    # refresh stale sections, preserve user-written ones
onmc claude-md preview   # show what would be generated without writing
onmc claude-md --watch   # auto-regenerate when memory changes
```

### Tasks and attempts

```bash
onmc task start --title "..." --description "..."
onmc task list / show / status / end
onmc attempt add <task_id> --summary "..." --kind fix_attempt --status tried
onmc attempt list / show / update
```

### Brief compilation

```bash
onmc brief --task "fix the cache invalidation bug"
onmc brief --task "fix the cache invalidation bug" --style caveman --max-tokens 400 --stdout
onmc codegraph --max-files 25
# LLM-ranked, annotated with relevance reasons
# Written to .onmc/compiled/ and rendered in terminal
```

### Agent modes (optional LLM)

```bash
onmc solve --task "..." --task-id <id>     # next best engineering approach
onmc review --task "..." --input-file plan.md
onmc teach --task "..."                     # staff-engineer explanation
onmc teach --task "..." --interactive       # follow-up Q&A loop
```

### Claude Code integration

```bash
onmc hooks install      # compaction hooks — context survives every compact
onmc hooks status
onmc serve --mcp        # MCP server: memory tools + resources for mid-session use
```

### Git-portable memory

```bash
onmc sync --commit      # export memory to .agent-memory/ (commit this)
onmc sync --restore     # restore memory on a fresh machine or cloud env
onmc sync --install-hook
```

### LLM provider

```bash
onmc llm configure --provider anthropic --model claude-sonnet-4-5
onmc llm status
```

---

## Python API

```python
import onmc

repo = onmc.init(".")
repo.ingest()
brief = repo.brief(task="fix the cache invalidation bug")
compact = repo.brief(task="fix the cache invalidation bug", style="compact", max_tokens=500)
graph = repo.codegraph(max_files=25)
memories = repo.memory.search(files=["src/cache.py"])
report = repo.report()
task = repo.task.start(title="Fix cache bug")
repo.sync.commit()
```

---

## How memory travels with your repo

```bash
onmc sync --commit
git add .agent-memory/
git commit -m "chore: export agent memory"
git push
```

Any machine that clones this repo — cloud agent, new teammate, ephemeral container — runs:

```bash
onmc init && onmc sync --restore
```

And gets the full memory store instantly. No accounts. No cloud. No config.

---

## Local state

```text
.onmc/            ← gitignored (binary SQLite + logs)
.agent-memory/    ← commit this (readable JSON exports)
CLAUDE.md         ← commit this (generated by onmc claude-md generate)
```

---

## Does it actually help?

Run the built-in benchmark (deterministic, no LLM, works on any machine):

```bash
onmc bench
```

Output on the built-in synthetic scenario (5 engineering tasks, seeded memory store):

```
                  onmc bench — onmc-builtin-v1
┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━┓
┃ Metric                 ┃ Without memory ┃ With memory ┃ Delta ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━┩
│ Repeated-failure rate  │           100% │          0% │ -100% │
├────────────────────────┼────────────────┼─────────────┼───────┤
│ Wasted attempts        │              9 │           0 │    -9 │
├────────────────────────┼────────────────┼─────────────┼───────┤
│ Context tokens (proxy) │           4000 │         107 │  -97% │
├────────────────────────┼────────────────┼─────────────┼───────┤
│ Tasks resolved         │              5 │           5 │    +0 │
└────────────────────────┴────────────────┴─────────────┴───────┘

Headline deltas: repeated-failure rate: 100% → 0%  |  context tokens: -97%
                 wasted attempts: -9
```

**How it works:** `onmc bench` is a deterministic proof harness — no LLM is
called.  It simulates an agent executing 5 tasks under two conditions: without
onmc memory and with memory (brief + recall injected).  With memory, the agent
skips recorded dead-ends (`failed_approach` memories) and uses a compact brief
instead of rediscovering context from scratch.

Run against your repo's real memory:

```bash
onmc bench --repo-memory
```

Results are written to `.onmc/compiled/<ts>-bench.md`.  Use `--json` for
machine-readable output.

> **Honest caveat:** this is a deterministic simulation with a synthetic
> scenario — not a live-LLM evaluation.  The numbers are reproducible and
> identical across runs.  Future work: replace the policy with a real LLM
> judge that calls a model and measures generation quality.

---

## Platform support

macOS and Linux are the primary supported platforms. Windows has smoke-test CI coverage.

---

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

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Good first issues are labeled in the tracker.

Areas actively looking for contributors:
- Cursor hook adapter
- Embedding-based memory ranking (opt-in)
- VS Code extension for brief display
- Semantic transcript-to-task linking

---

## License

MIT. See [LICENSE](LICENSE).
