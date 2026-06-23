# oh-no-my-claudecode (`onmc`)

[![CI](https://github.com/adaline-ankit/oh-no-my-claudecode/actions/workflows/ci.yml/badge.svg)](https://github.com/adaline-ankit/oh-no-my-claudecode/actions)
[![PyPI version](https://badge.fury.io/py/oh-no-my-claudecode.svg)](https://pypi.org/project/oh-no-my-claudecode/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![AI-Ready](https://img.shields.io/badge/AI--Ready-ONMC-6B7280)](https://github.com/adaline-ankit/oh-no-my-claudecode)

**A git-portable, cross-agent memory brain for coding agents.**  
Your agent knows why the code is the way it is, what failed before, and never repeats a recorded dead-end — across Claude Code, Cursor, and Codex.

---

## The problem

Every Claude Code session starts blank. Your agent re-discovers that the cache layer can't be mocked, re-tries the auth approach that broke CI three sprints ago, and burns 4,000 context tokens reconstructing what you already knew. Every. Single. Session.

**onmc fixes that.** It reads your git history, session transcripts, and docs, builds a structured memory store in `.agent-memory/` (committable JSON), and injects the right knowledge at session start, on every prompt, and before context compaction. The brain travels with the repo — clone it anywhere and get full memory back in seconds.

---

## Proof it helps

Run the built-in benchmark — no LLM, no network, deterministic:

```bash
onmc bench
```

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

This is a **deterministic simulation** over a synthetic 5-task scenario — no live LLM is called, so results are reproducible in CI. The harness models an agent executing tasks under two conditions: without onmc (rediscovers context from scratch, retries known dead-ends) and with onmc (brief + recall injected, `failed_approach` memories block repeated mistakes). See [`docs/cli-reference.md`](docs/cli-reference.md) for `--repo-memory` to run against your own store, and `docs/demo.md` for a full walkthrough.

---

## What you get

- **`onmc why <file>`** — explains why a file looks the way it does, from stored memory + git history. Time-travel to any commit with `--at <commit>`.

- **`onmc guard --task "..."`** — surfaces recorded `failed_approach` / `did_not_work` memories as explicit "DO NOT retry these dead-ends" guidance before your agent starts. Also available as a `guard_task` MCP tool mid-session.

- **Auto-injected context via hooks** — `onmc hooks install` registers project-scoped Claude Code hooks: a boot digest on every `SessionStart`, relevant memories on every prompt (`UserPromptSubmit`), a compaction snapshot before `PreCompact`, and memory consolidation on `SessionEnd`. Context survives every compact.

- **Git-portable brain** — `onmc sync --commit` exports memory to `.agent-memory/` as committable JSON. Any machine that clones the repo runs `onmc sync --restore` and gets full memory instantly. No accounts, no cloud, no config. Works in Gitpod, Codespaces, and GitHub Coding Agent containers.

- **Obsidian knowledge graph** — `onmc wiki --format obsidian` turns repo memory into a local vault with provenance metadata, subsystem indexes, and linked decisions, invariants, gotchas, and failed approaches.

- **Claude Code plugin** — `onmc setup` generates `CLAUDE.md`, installs hooks, and registers the MCP server (`onmc serve --mcp`) exposing `search_memory`, `guard_task`, and `get_brief` tools. A plugin manifest lives at [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) for one-click registration.

---

## 30-second quickstart

```bash
pip install oh-no-my-claudecode
cd your-repo
onmc setup          # wizard: ingest git history, generate CLAUDE.md, install hooks + MCP
```

`onmc setup` detects your repo shape, optionally runs LLM-assisted extraction, generates `CLAUDE.md`, and wires Claude Code hooks and `.mcp.json` in one pass. Use `--no-llm` if you want a fully offline first run.

Then commit the brain so it travels with the repo:

```bash
onmc sync --commit
git add .agent-memory/ CLAUDE.md
git commit -m "chore: add onmc agent brain"
```

On a fresh clone or cloud agent container:

```bash
onmc init && onmc sync --restore   # full memory, zero re-discovery
```

---

## Works with every coding agent

Run `onmc plug <agent>` to wire onmc into your agent in one idempotent command:

```bash
onmc plug claude-code   # hooks + .mcp.json
onmc plug codex         # AGENTS.md stanza
onmc plug cursor        # .cursor/rules/onmc.md
onmc plug omc           # copy-paste OMC adapter
onmc plug omx           # copy-paste OMX adapter
onmc plug all           # claude-code + codex + cursor
```

| Agent | `onmc plug` | Manual integration |
|---|---|---|
| **Claude Code** | `onmc plug claude-code` | `CLAUDE.md` + `onmc hooks install` + `onmc serve --mcp` + [plugin manifest](.claude-plugin/plugin.json) |
| **Cursor** | `onmc plug cursor` | Pipe `onmc brief` output to `.cursorrules` |
| **Codex / GitHub Coding Agent** | `onmc plug codex` | [`AGENTS.md`](AGENTS.md) — run `onmc brief`, `onmc guard`, `onmc serve --mcp` at session start |
| **oh-my-claudecode (OMC)** | `onmc plug omc` | Copy-paste adapter in [docs/integrations/omc.md](docs/integrations/omc.md) |
| **oh-my-codex (OMX)** | `onmc plug omx` | Copy-paste adapter in [docs/integrations/omx.md](docs/integrations/omx.md) |
| **Cloud agents** (GitHub Coding Agent) | — | `onmc sync --restore` in container startup |
| **Gitpod / Codespaces** | — | Add `onmc sync --restore` to `.gitpod.yml` |

MCP tools exposed by `onmc serve --mcp`: **`search_memory`**, **`guard_task`**, **`get_brief`**.

See [Integration Guides](docs/integrations/README.md), [Agent-Native Workflows](docs/agent-native-workflows.md),
and [CLI Reference](docs/cli-reference.md) for full detail.

---

## Commands

For full generated help output, see [CLI Reference](docs/cli-reference.md).

### Setup and health

```bash
onmc setup              # full onboarding wizard — run this first
onmc doctor             # health check: memory freshness, hooks, MCP, CLAUDE.md
onmc report             # markdown agent-readiness report for PRs and handoffs
onmc status             # repo root, ingest state, memory counts
onmc ui                 # local dashboard: memory, tasks, graph, health
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
onmc wiki --format obsidian           # visual knowledge graph in Obsidian
```

Obsidian export defaults to `.onmc/obsidian/` so private repo memory stays local. Open that
directory as a vault, then use Graph View to explore relationships. See
[Obsidian Vault Export](docs/obsidian.md).

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

### Visual dashboard

```bash
onmc ui
onmc ui --no-open --port 9001
```

Dashboard stays local and read-only by default at `http://127.0.0.1:8765`.

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
